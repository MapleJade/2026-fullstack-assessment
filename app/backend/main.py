"""Variant PDP — FastAPI backend.

Three endpoints:
    GET  /api/products/{id}
    POST /api/cart/items
    GET  /api/cart

Idempotency: POST /api/cart/items accepts an Idempotency-Key header. The same
key, when replayed, returns the *original* response (success or error) with
no state change. Keys expire after 1 hour to bound memory use.

Concurrency safety: see models.py — each SKU has its own asyncio.Lock, so
two concurrent add-to-cart calls racing for the last unit of the same SKU
cannot both succeed.
"""

from __future__ import annotations

import secrets
import time
from collections import OrderedDict
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from models import Store, get_store


app = FastAPI(
    title="Variant PDP Backend",
    version="1.0.0",
    description="Three endpoints for the variant PDP take-home assessment.",
)

# Allow frontend on any origin (dev-friendly). In production we'd be specific.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Idempotency key cache
# ---------------------------------------------------------------------------

_MAX_IDEMPOTENCY_ENTRIES = 10_000
_IDEMPOTENCY_TTL_SECONDS = 3600

# OrderedDict for FIFO eviction. Each value: (timestamp, http_status, response_body)
_idempotency_cache: OrderedDict[str, tuple[float, int, dict]] = OrderedDict()


def _purge_expired() -> None:
    now = time.time()
    expired = [k for k, (ts, *_rest) in _idempotency_cache.items()
               if now - ts > _IDEMPOTENCY_TTL_SECONDS]
    for k in expired:
        del _idempotency_cache[k]


def _cache_put(key: str, status: int, body: dict) -> None:
    _purge_expired()
    if len(_idempotency_cache) >= _MAX_IDEMPOTENCY_ENTRIES:
        _idempotency_cache.popitem(last=False)
    _idempotency_cache[key] = (time.time(), status, body)


def _cache_get(key: str) -> Optional[tuple[int, dict]]:
    entry = _idempotency_cache.get(key)
    if entry is None:
        return None
    ts, status, body = entry
    if time.time() - ts > _IDEMPOTENCY_TTL_SECONDS:
        del _idempotency_cache[key]
        return None
    return (status, body)


# ---------------------------------------------------------------------------
# Request / response bodies
# ---------------------------------------------------------------------------

class AddToCartRequest(BaseModel):
    sku_id: str = Field(..., min_length=1, description="SKU identifier")
    quantity: int = Field(..., gt=0, description="Positive integer")
    cart_id: Optional[str] = Field(None, description="Optional cart id; server generates if omitted")


class AddToCartResponse(BaseModel):
    cart_id: str
    sku_id: str
    quantity_added: int
    stock_remaining: int
    message: str


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/products/{product_id}")
def get_product(product_id: str):
    store: Store = get_store()
    product = store.get_product(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")
    return product


@app.post("/api/cart/items", response_model=AddToCartResponse)
async def add_to_cart(
    body: AddToCartRequest,
    request: Request,
    x_idempotency_key: Optional[str] = Header(default=None),
):
    # Idempotency replay path — return cached response unchanged
    if x_idempotency_key:
        cached = _cache_get(x_idempotency_key)
        if cached is not None:
            status, resp = cached
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=status, content=resp)

    store: Store = get_store()

    # Generate a cart_id client-side if they didn't send one; server owns cart
    cart_id = body.cart_id or f"cart-{secrets.token_hex(8)}"

    ok, msg = await store.add_to_cart(cart_id, body.sku_id, body.quantity)
    sku = store.skus_by_id.get(body.sku_id)

    if not ok:
        if "not found" in msg.lower():
            status = 404
        elif "quantity must be positive" in msg.lower():
            status = 400
        else:
            status = 409  # insufficient stock

        body_out = {"cart_id": cart_id, "sku_id": body.sku_id,
                    "quantity_added": 0, "stock_remaining": sku.stock if sku else 0,
                    "message": msg}
        if x_idempotency_key:
            _cache_put(x_idempotency_key, status, body_out)
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=status, content=body_out)

    body_out = {"cart_id": cart_id, "sku_id": body.sku_id,
                "quantity_added": body.quantity,
                "stock_remaining": sku.stock if sku else 0,
                "message": msg}
    if x_idempotency_key:
        _cache_put(x_idempotency_key, 200, body_out)
    return body_out


@app.get("/api/cart")
def get_cart(cart_id: str = "default"):
    store: Store = get_store()
    return store.get_cart(cart_id)


# ---------------------------------------------------------------------------
# Startup hook — we just reset the singleton for fresh behaviour each boot
# ---------------------------------------------------------------------------

@app.on_event("startup")
def _on_startup():
    import models as _models
    _models._store = None  # force a fresh Store() on first get_store()
    _idempotency_cache.clear()

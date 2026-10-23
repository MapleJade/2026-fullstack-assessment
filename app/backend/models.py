"""In-memory domain store for the variant PDP backend.

Single module to keep the backend dependency-free beyond FastAPI + Pydantic.
Concurrency safety: SKU reservations use per-SKU asyncio locks so that two
concurrent add-to-cart requests racing for the last unit cannot both succeed.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OptionValue:
    value: str
    label: str


@dataclass(frozen=True)
class Option:
    name: str           # e.g. "color", "size"
    label: str          # e.g. "Colour", "Size"
    values: tuple[OptionValue, ...]


@dataclass
class SKU:
    sku_id: str
    option_values: tuple[tuple[str, str], ...]   # e.g. (("color","Red"),("size","S"))
    price: float
    image_url: str
    stock: int


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

def _build_seed():
    options = [
        Option(name="color", label="Colour", values=(
            OptionValue("red", "Red"),
            OptionValue("blue", "Blue"),
            OptionValue("green", "Green"),
        )),
        Option(name="size", label="Size", values=(
            OptionValue("s", "S"),
            OptionValue("m", "M"),
            OptionValue("l", "L"),
        )),
    ]

    skus = [
        SKU("sku-r-s", (("color", "red"), ("size", "s")),
            19.99, "https://example.com/img/red-s.jpg", stock=10),
        SKU("sku-r-m", (("color", "red"), ("size", "m")),
            19.99, "https://example.com/img/red-m.jpg", stock=5),
        SKU("sku-r-l", (("color", "red"), ("size", "l")),
            19.99, "https://example.com/img/red-l.jpg", stock=0),
        SKU("sku-b-s", (("color", "blue"), ("size", "s")),
            21.99, "https://example.com/img/blue-s.jpg", stock=8),
        SKU("sku-b-m", (("color", "blue"), ("size", "m")),
            21.99, "https://example.com/img/blue-m.jpg", stock=3),
        SKU("sku-b-l", (("color", "blue"), ("size", "l")),
            21.99, "https://example.com/img/blue-l.jpg", stock=6),
        # Note: "Green" is intentionally missing → colour "green" has no SKUs
        # → green + any size combination is an INVALID / unavailable variant.
    ]
    return options, skus


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class Store:
    def __init__(self) -> None:
        options, skus = _build_seed()
        self.product_id = "p-classic-tee"
        self.product_name = "Classic Crewneck Tee"
        self.product_description = (
            "A soft 100% cotton crewneck tee. Pre-shrunk, garment-dyed in "
            "small batches. Classic fit — size down if you prefer slim."
        )
        self.options: list[Option] = list(options)
        self.skus_by_id: dict[str, SKU] = {s.sku_id: s for s in skus}
        self._sku_locks: dict[str, asyncio.Lock] = {
            s.sku_id: asyncio.Lock() for s in skus
        }

        # Cart: cart_id -> {sku_id: qty}
        self.carts: dict[str, dict[str, int]] = {}

    # -- product lookup ---------------------------------------------------

    def get_product(self, product_id: str) -> Optional[dict]:
        if product_id != self.product_id:
            return None
        return {
            "id": self.product_id,
            "name": self.product_name,
            "description": self.product_description,
            "options": [
                {
                    "name": o.name,
                    "label": o.label,
                    "values": [
                        {"value": v.value, "label": v.label} for v in o.values
                    ],
                }
                for o in self.options
            ],
            "skus": [
                {
                    "sku_id": s.sku_id,
                    "options": dict(s.option_values),
                    "price": s.price,
                    "image_url": s.image_url,
                    "stock": s.stock,
                }
                for s in self.skus_by_id.values()
            ],
        }

    # -- cart -------------------------------------------------------------

    def _ensure_cart(self, cart_id: str) -> dict[str, int]:
        if cart_id not in self.carts:
            self.carts[cart_id] = {}
        return self.carts[cart_id]

    async def add_to_cart(
        self, cart_id: str, sku_id: str, qty: int
    ) -> tuple[bool, str]:
        """Reserve stock and add to cart. Returns (success, message).

        Thread-safe per SKU: the reservation + decrement is atomic for that SKU,
        preventing two concurrent requests from both "winning" the last unit.
        """
        if sku_id not in self.skus_by_id:
            return False, f"SKU {sku_id} not found"
        sku = self.skus_by_id[sku_id]

        if qty <= 0:
            return False, "quantity must be positive"

        async with self._sku_locks[sku_id]:
            if sku.stock < qty:
                return False, f"insufficient stock (have {sku.stock}, need {qty})"
            sku.stock -= qty
            cart = self._ensure_cart(cart_id)
            cart[sku_id] = cart.get(sku_id, 0) + qty

        return True, "added"

    def get_cart(self, cart_id: str) -> dict:
        cart = self.carts.get(cart_id, {})
        items = []
        total_count = 0
        for sid, qty in cart.items():
            sku = self.skus_by_id.get(sid)
            if sku is None:
                continue
            items.append({
                "sku_id": sid,
                "quantity": qty,
                "price_each": sku.price,
                "subtotal": round(sku.price * qty, 2),
            })
            total_count += qty
        items.sort(key=lambda x: x["sku_id"])
        return {"cart_id": cart_id, "items": items, "total_count": total_count}


# Singleton used by the FastAPI app. A new instance per-app is fine for tests.
_store: Optional[Store] = None


def get_store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store

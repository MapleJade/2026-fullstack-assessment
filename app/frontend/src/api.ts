import type { AddToCartResponse, ApiError, Cart, Product } from './types'

const API_BASE = '/api'

async function handleResp<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let detail: unknown
    try { detail = await resp.json() } catch { detail = resp.statusText }
    const err = (detail ?? {}) as ApiError
    throw new Error((err as any).message ?? err.error ?? JSON.stringify(detail))
  }
  return resp.json() as Promise<T>
}

export async function fetchProduct(productId: string): Promise<Product> {
  const resp = await fetch(`${API_BASE}/products/${productId}`)
  return handleResp<Product>(resp)
}

export async function addToCart(
  skuId: string,
  quantity: number,
  cartId: string | null,
  idempotencyKey: string,
): Promise<AddToCartResponse> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Idempotency-Key': idempotencyKey,
  }
  if (cartId) headers['X-Cart-Id'] = cartId

  const resp = await fetch(`${API_BASE}/cart/items`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ sku_id: skuId, quantity, cart_id: cartId ?? undefined }),
  })
  return handleResp<AddToCartResponse>(resp)
}

export async function fetchCart(cartId: string): Promise<Cart> {
  const resp = await fetch(`${API_BASE}/cart?cart_id=${encodeURIComponent(cartId)}`)
  return handleResp<Cart>(resp)
}

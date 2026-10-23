import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { fetchProduct, addToCart as apiAdd, fetchCart } from './api'
import type {
  Cart,
  Product,
  SKU,
  VariantSelection,
} from './types'
import { findSKUForSelection, isOptionAvailable } from './types'

const PRODUCT_ID = 'p-classic-tee'
const CART_ID_KEY = 'pdp.cart_id'

// ============== Helpers ==============

function getCartId(): string {
  let id = localStorage.getItem(CART_ID_KEY)
  if (!id) {
    id = 'cart-' + Math.random().toString(36).slice(2, 14)
    localStorage.setItem(CART_ID_KEY, id)
  }
  return id
}

function isNonZeroNumber(v: unknown): v is number {
  return typeof v === 'number' && v > 0
}

// ============== States ==============

type LoadState =
  | { kind: 'loading' }
  | { kind: 'ready'; product: Product }
  | { kind: 'error'; message: string }

type AddState =
  | { kind: 'idle' }
  | { kind: 'in_progress' }
  | { kind: 'success'; message: string }
  | { kind: 'validation_error'; message: string }
  | { kind: 'insufficient_stock'; message: string }
  | { kind: 'server_error'; message: string }

// ============== Component ==============

export default function PDP() {
  const [loadState, setLoadState] = useState<LoadState>({ kind: 'loading' })
  const [selection, setSelection] = useState<VariantSelection>({})
  const [qty, setQty] = useState<number>(1)
  const [addState, setAddState] = useState<AddState>({ kind: 'idle' })
  const [cart, setCart] = useState<Cart | null>(null)
  const cartIdRef = useRef<string>(getCartId())
  const lastSkuRef = useRef<string | null>(null)

  // 1. Load product + cart on mount
  const loadAll = useCallback(async () => {
    setLoadState({ kind: 'loading' })
    setAddState({ kind: 'idle' })
    try {
      const [product, cartData] = await Promise.all([
        fetchProduct(PRODUCT_ID),
        fetchCart(cartIdRef.current),
      ])
      setLoadState({ kind: 'ready', product })
      setCart(cartData)
    } catch (err) {
      setLoadState({
        kind: 'error',
        message: err instanceof Error ? err.message : 'Unknown error',
      })
    }
  }, [])

  useEffect(() => { loadAll() }, [loadAll])

  // 2. Derived: resolved SKU, validity flags, stock
  const { product, selectedSKU, hasAllOptions, availableQty } = useMemo(() => {
    if (loadState.kind !== 'ready') {
      return { product: null as Product | null, selectedSKU: undefined as SKU | undefined,
               hasAllOptions: false, availableQty: 0 }
    }
    const p = loadState.product
    const hasAll = Object.keys(selection).length === p.options.length
    const sku = hasAll ? findSKUForSelection(p, selection) : undefined
    // Qty must never exceed the *currently available* stock; 1 if out-of-stock
    // (disabled via the stock===0 check below).
    const max = sku ? Math.max(sku.stock, 1) : 1
    return { product: p, selectedSKU: sku, hasAllOptions: hasAll, availableQty: max }
  }, [loadState, selection])

  // 3. Keep qty bounded when selection changes
  useEffect(() => {
    if (!selectedSKU) return
    const max = Math.max(selectedSKU.stock, 1)
    if (qty > max) setQty(max)
    if (qty < 1) setQty(1)
  }, [selectedSKU, qty])

  // Reset add-to-cart feedback when SKU changes
  useEffect(() => {
    if (selectedSKU?.sku_id !== lastSkuRef.current) {
      lastSkuRef.current = selectedSKU?.sku_id ?? null
      setAddState({ kind: 'idle' })
    }
  }, [selectedSKU])

  // 4. Handlers
  const handleSelectOption = (optName: string, value: string) => {
    setSelection((prev) => ({ ...prev, [optName]: value }))
  }

  const handleAddToCart = async () => {
    if (!product || !selectedSKU) {
      setAddState({ kind: 'validation_error', message: 'Select a complete variant first.' })
      return
    }
    if (selectedSKU.stock <= 0) {
      setAddState({ kind: 'insufficient_stock', message: 'This variant is out of stock.' })
      return
    }
    if (qty < 1 || qty > selectedSKU.stock) {
      setAddState({ kind: 'validation_error', message: 'Please pick a valid quantity.' })
      return
    }
    setAddState({ kind: 'in_progress' })
    try {
      const resp = await apiAdd(
        selectedSKU.sku_id,
        qty,
        cartIdRef.current,
        `cart-${Date.now()}-${Math.random()}`,
      )
      // Keep server's cart_id if it generated one
      if (!localStorage.getItem(CART_ID_KEY) || cartIdRef.current !== resp.cart_id) {
        cartIdRef.current = resp.cart_id
        localStorage.setItem(CART_ID_KEY, resp.cart_id)
      }
      setAddState({
        kind: 'success',
        message: `Added ${qty} ${qty === 1 ? 'item' : 'items'} to cart.`,
      })
      // Refresh cart view
      const cartData = await fetchCart(cartIdRef.current)
      setCart(cartData)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      if (msg.toLowerCase().includes('insufficient')) {
        setAddState({ kind: 'insufficient_stock', message: msg })
      } else {
        setAddState({ kind: 'server_error', message: msg })
      }
    }
  }

  // ============== Render ==============

  if (loadState.kind === 'loading') return <LoadingUI />
  if (loadState.kind === 'error')
    return <ErrorUI message={loadState.message} onRetry={loadAll} />
  if (!product) return null

  return (
    <div className="pdp">
      <CartBadge count={cart?.total_count ?? 0} />
      <h1>{product.name}</h1>
      <p className="desc">{product.description}</p>

      {selectedSKU ? (
        <img
          src={selectedSKU.image_url}
          alt={`${product.name} ${selectedSKU.sku_id}`}
          className="sku-image"
        />
      ) : (
        <div className="sku-image placeholder" aria-hidden="true">Pick options to see image</div>
      )}

      {product.options.map((opt) => (
        <fieldset key={opt.name} className="option-group">
          <legend>{opt.label}</legend>
          <div className="option-buttons" role="radiogroup" aria-label={opt.label}>
            {opt.values.map((v) => {
              const available = isOptionAvailable(
                product, opt.name, v.value, selection,
              )
              const selected = selection[opt.name] === v.value
              return (
                <button
                  key={v.value}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  disabled={!available}
                  aria-disabled={!available}
                  onClick={() => handleSelectOption(opt.name, v.value)}
                  className={`option-btn ${selected ? 'selected' : ''} ${!available ? 'unavailable' : ''}`}
                  title={!available ? 'This combination is not available' : v.label}
                >
                  {v.label}
                </button>
              )
            })}
          </div>
        </fieldset>
      ))}

      <VariantStatus
        hasAll={hasAllOptions}
        sku={selectedSKU}
        addState={addState}
      />

      {selectedSKU && selectedSKU.stock > 0 && (
        <div className="qty-row">
          <label htmlFor="qty">Quantity</label>
          <input
            id="qty"
            type="number"
            min={1}
            max={selectedSKU.stock}
            value={qty}
            onChange={(e) => setQty(Math.min(selectedSKU.stock, Math.max(1, Number(e.target.value) || 1)))}
            aria-label="Quantity"
          />
          <span className="qty-hint">of {selectedSKU.stock} available</span>
        </div>
      )}

      <button
        type="button"
        disabled={
          addState.kind === 'in_progress'
          || !hasAllOptions
          || !selectedSKU
          || selectedSKU.stock <= 0
          || !isNonZeroNumber(qty)
        }
        onClick={handleAddToCart}
        className="add-btn"
        aria-busy={addState.kind === 'in_progress'}
      >
        {addState.kind === 'in_progress' ? 'Adding…' : 'Add to cart'}
      </button>

      <AddToCartFeedback addState={addState} />
    </div>
  )
}

// ============== Sub-components ==============

function CartBadge({ count }: { count: number }) {
  return (
    <span className="cart-badge" aria-label={`Cart has ${count} items`}>
      Cart: <strong>{count}</strong>
    </span>
  )
}

function VariantStatus({
  hasAll, sku, addState,
}: {
  hasAll: boolean
  sku: SKU | undefined
  addState: AddState
}) {
  if (!hasAll) {
    return <p className="status info">Pick all options to see price and stock.</p>
  }
  if (!sku) {
    return <p className="status invalid" role="alert">This combination is not available.</p>
  }
  if (sku.stock <= 0) {
    return (
      <p className="status out-of-stock" role="alert">
        <strong>${sku.price.toFixed(2)}</strong> — Out of stock.
      </p>
    )
  }
  return (
    <p className="status available">
      <strong>${sku.price.toFixed(2)}</strong> — In stock.
    </p>
  )
}

function AddToCartFeedback({ addState }: { addState: AddState }) {
  const cls = addState.kind
  if (cls === 'idle' || cls === 'in_progress') return null
  const role = cls === 'success' ? 'status' : 'alert'
  return (
    <p className={`feedback ${cls}`} role={role} aria-live="polite">
      {addState.message}
    </p>
  )
}

function LoadingUI() {
  return (
    <div className="pdp loading" role="status" aria-live="polite">
      Loading product…
    </div>
  )
}

function ErrorUI({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="pdp error" role="alert">
      <h2>Could not load product</h2>
      <p>{message}</p>
      <button type="button" className="retry-btn" onClick={onRetry}>Try again</button>
    </div>
  )
}

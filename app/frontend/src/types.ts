// ============== Domain types ==============

export interface OptionValue {
  value: string
  label: string
}

export interface ProductOption {
  name: string
  label: string
  values: OptionValue[]
}

export interface SKU {
  sku_id: string
  options: Record<string, string>
  price: number
  image_url: string
  stock: number
}

export interface Product {
  id: string
  name: string
  description: string
  options: ProductOption[]
  skus: SKU[]
}

// ============== Cart ==============

export interface CartItem {
  sku_id: string
  quantity: number
  price_each: number
  subtotal: number
}

export interface Cart {
  cart_id: string
  items: CartItem[]
  total_count: number
}

export interface AddToCartResponse {
  cart_id: string
  sku_id: string
  quantity_added: number
  stock_remaining: number
  message: string
}

export interface ApiError {
  error: string
  detail?: string
}

// ============== Variant resolution ==============

export type VariantSelection = Record<string, string>  // {color: "red", size: "m"}

export function findSKUForSelection(
  product: Product,
  selection: VariantSelection,
): SKU | undefined {
  if (Object.keys(selection).length !== product.options.length) return undefined
  return product.skus.find((sku) =>
    product.options.every((opt) => sku.options[opt.name] === selection[opt.name]),
  )
}

export function isOptionAvailable(
  product: Product,
  optionName: string,
  optionValue: string,
  currentSelection: VariantSelection,
): boolean {
  const trySelection = { ...currentSelection, [optionName]: optionValue }
  // An option value is available if there exists *at least one* SKU whose
  // already-chosen options match trySelection — regardless of whether other
  // option dimensions are still open. This way we only disable a button
  // when no path from current state can reach a valid SKU through it.
  return product.skus.some((sku) =>
    Object.entries(trySelection).every(
      ([name, value]) => sku.options[name] === value,
    ),
  )
}

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react'
import PDP from '../PDP'
import type { Product } from '../types'

// ============== Fixtures ==============

const SAMPLE_PRODUCT: Product = {
  id: 'p-classic-tee',
  name: 'Classic Crewneck Tee',
  description: 'Soft cotton tee.',
  options: [
    { name: 'color', label: 'Colour', values: [
      { value: 'red', label: 'Red' },
      { value: 'blue', label: 'Blue' },
      { value: 'green', label: 'Green' },
    ]},
    { name: 'size', label: 'Size', values: [
      { value: 's', label: 'S' },
      { value: 'm', label: 'M' },
      { value: 'l', label: 'L' },
    ]},
  ],
  skus: [
    { sku_id: 'sku-r-s', options: { color: 'red', size: 's' }, price: 19.99, image_url: '/img/red-s.jpg', stock: 10 },
    { sku_id: 'sku-r-m', options: { color: 'red', size: 'm' }, price: 19.99, image_url: '/img/red-m.jpg', stock: 5 },
    { sku_id: 'sku-r-l', options: { color: 'red', size: 'l' }, price: 19.99, image_url: '/img/red-l.jpg', stock: 0 },
    { sku_id: 'sku-b-s', options: { color: 'blue', size: 's' }, price: 21.99, image_url: '/img/blue-s.jpg', stock: 8 },
    { sku_id: 'sku-b-m', options: { color: 'blue', size: 'm' }, price: 21.99, image_url: '/img/blue-m.jpg', stock: 3 },
    { sku_id: 'sku-b-l', options: { color: 'blue', size: 'l' }, price: 21.99, image_url: '/img/blue-l.jpg', stock: 6 },
    { sku_id: 'sku-g-s', options: { color: 'green', size: 's' }, price: 22.99, image_url: '/img/green-s.jpg', stock: 4 },
  ],
}

function mockFetch(overrides?: { fail?: boolean; product?: Product }) {
  const product = overrides?.product ?? SAMPLE_PRODUCT
  const shouldFail = overrides?.fail ?? false

  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    if (shouldFail) {
      return Promise.resolve(new Response(JSON.stringify({ error: 'boom' }), { status: 500 }))
    }
    if (url.includes('/products/')) {
      return Promise.resolve(new Response(JSON.stringify(product)))
    }
    if (url.includes('/cart?')) {
      return Promise.resolve(new Response(JSON.stringify({ cart_id: 'cart-test', items: [], total_count: 0 })))
    }
    if (url.includes('/cart/items')) {
      const body = JSON.parse(init?.body ?? '{}')
      return Promise.resolve(new Response(JSON.stringify({
        cart_id: 'cart-test',
        sku_id: body.sku_id,
        quantity_added: body.quantity,
        stock_remaining: 0,
        message: 'added',
      })))
    }
    return Promise.resolve(new Response('{}'))
  }))
}

function clickOption(label: string) {
  fireEvent.click(screen.getByRole('radio', { name: label }))
}

// ============== Tests ==============

describe('PDP — variant resolution', () => {
  beforeEach(() => { vi.restoreAllMocks() })

  it('resolves the correct SKU after each option is selected', async () => {
    mockFetch()
    render(<PDP />)
    await waitFor(() => screen.getByText('Classic Crewneck Tee'))

    clickOption('Red')
    clickOption('M')
    await waitFor(() => expect(screen.getByText((_, el) => {
      return el?.classList?.contains('status') && el.textContent?.includes('19.99') && el.textContent?.includes('In stock')
    })).toBeInTheDocument())

    // Image reflects the chosen SKU
    const img = screen.getByAltText(/sku-r-m/)
    expect(img).toBeInTheDocument()

    // Switch to Blue + M — price changes
    clickOption('Blue')
    await waitFor(() => expect(screen.getByText((_, el) => {
      return el?.classList?.contains('status') && el.textContent?.includes('21.99')
    })).toBeInTheDocument())

    // Out-of-stock variant
    clickOption('M'); clickOption('Red'); clickOption('L')
    await waitFor(() => expect(screen.getByText(/Out of stock/)).toBeInTheDocument())
  })

  it('disables buttons for unavailable combinations and shows out-of-stock', async () => {
    mockFetch()
    render(<PDP />)
    await waitFor(() => screen.getByText('Classic Crewneck Tee'))

    // Pick Green — only size 's' exists for Green (green-s SKU only)
    clickOption('Green')
    await waitFor(() => {
      const sizeRadios = screen.getAllByRole('radio', { name: /^(S|M|L)$/ })
      expect(sizeRadios[0]).toBeEnabled()
      expect(sizeRadios[1]).toBeDisabled()
      expect(sizeRadios[2]).toBeDisabled()
    })

    // Green + S is valid
    clickOption('S')
    await waitFor(() => expect(screen.getByText((_, el) => {
      return el?.classList?.contains('status') && el.textContent?.includes('22.99') && el.textContent?.includes('In stock')
    })).toBeInTheDocument())

    // Switch to Red — now all sizes available again
    clickOption('Red')
    await waitFor(() => {
      const sizeRadios = screen.getAllByRole('radio', { name: /^(S|M|L)$/ })
      sizeRadios.forEach((btn) => expect(btn).toBeEnabled())
    })

    // Red + L exists but stock=0 → Out of stock
    clickOption('L')
    await waitFor(() => expect(screen.getByText(/Out of stock/)).toBeInTheDocument())
  })
})

describe('PDP — duplicate-click protection during pending request', () => {
  beforeEach(() => { vi.restoreAllMocks() })

  it('disables add-to-cart button during in-progress state and does not send duplicate requests', async () => {
    let resolveFetch: ((r: Response) => void) | null = null
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
      if (url.includes('/products/')) {
        return Promise.resolve(new Response(JSON.stringify(SAMPLE_PRODUCT)))
      }
      if (url.includes('/cart?')) {
        return Promise.resolve(new Response(JSON.stringify({ cart_id: 'x', items: [], total_count: 0 })))
      }
      if (url.includes('/cart/items')) {
        return new Promise<Response>((resolve) => { resolveFetch = resolve })
      }
      return Promise.resolve(new Response('{}'))
    }))

    render(<PDP />)
    await waitFor(() => screen.getByText('Classic Crewneck Tee'))

    clickOption('Red'); clickOption('M')
    await waitFor(() => expect(screen.getByText((_, el) => {
      return el?.classList?.contains('status') && el.textContent?.includes('19.99')
    })).toBeInTheDocument())

    const addBtn = screen.getByRole('button', { name: /Add to cart/ })
    fireEvent.click(addBtn)

    // Pending → disabled + aria-busy
    await waitFor(() => expect(addBtn).toBeDisabled())
    expect(addBtn).toHaveAttribute('aria-busy', 'true')
    expect(addBtn.textContent).toMatch(/Adding/)

    // Attempted second click must NOT have sent another request
    const fetchSpy = fetch as unknown as ReturnType<typeof vi.fn>
    const callsBeforeSecondClick = fetchSpy.mock.calls.filter(
      (c) => String(c[0]).includes('/cart/items'),
    ).length
    fireEvent.click(addBtn)
    await act(async () => { await Promise.resolve() })
    const callsAfter = fetchSpy.mock.calls.filter(
      (c) => String(c[0]).includes('/cart/items'),
    ).length
    expect(callsAfter).toBe(callsBeforeSecondClick)

    // Resolve the request
    await act(async () => {
      resolveFetch?.(new Response(JSON.stringify({
        cart_id: 'x', sku_id: 'sku-r-m', quantity_added: 1,
        stock_remaining: 4, message: 'added',
      })))
    })
    await waitFor(() => expect(addBtn).toBeEnabled())
  })
})

describe('PDP — resilient async UX', () => {
  beforeEach(() => { vi.restoreAllMocks() })

  it('shows load error and allows retry', async () => {
    mockFetch({ fail: true })
    render(<PDP />)

    await waitFor(() => screen.getByText(/Could not load product/))
    const retryBtn = screen.getByRole('button', { name: /Try again/ })
    expect(retryBtn).toBeInTheDocument()

    vi.restoreAllMocks()
    mockFetch()
    fireEvent.click(retryBtn)

    await waitFor(() => screen.getByText('Classic Crewneck Tee'))
  })

  it('shows server-side insufficient-stock message with alert role', async () => {
    let resolveFetch: ((r: Response) => void) | null = null
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
      if (url.includes('/products/')) {
        return Promise.resolve(new Response(JSON.stringify(SAMPLE_PRODUCT)))
      }
      if (url.includes('/cart?')) {
        return Promise.resolve(new Response(JSON.stringify({ cart_id: 'x', items: [], total_count: 0 })))
      }
      if (url.includes('/cart/items')) {
        return new Promise<Response>((resolve) => { resolveFetch = resolve })
      }
      return Promise.resolve(new Response('{}'))
    }))

    render(<PDP />)
    await waitFor(() => screen.getByText('Classic Crewneck Tee'))
    clickOption('Red'); clickOption('M')
    await waitFor(() => expect(screen.getByText((_, el) => {
      return el?.classList?.contains('status') && el.textContent?.includes('19.99')
    })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /Add to cart/ }))
    await act(async () => {
      resolveFetch?.(new Response(
        JSON.stringify({ message: 'insufficient stock' }),
        { status: 409 },
      ))
    })

    await waitFor(() => screen.getByText(/insufficient/))
    expect(screen.getByText(/insufficient/)).toHaveAttribute('role', 'alert')
  })
})

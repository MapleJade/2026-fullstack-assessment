# Full-Stack Developer Coding Assignment

## Structure

```
A/          Inventory Reservation Ledger (Python)
B/          Warehouse Allocation Optimiser (Python)
C/          Xero Integration Review (written answers)
app/        Full-Stack PDP Application
  backend/  FastAPI service (Python)
  frontend/ React + TypeScript SPA (Vite + Vitest)
```

## Task A — Inventory Reservation Ledger

A command-line ledger that processes RESERVE / RELEASE / SHIP / RESTOCK commands for a single SKU, with full **idempotency via event-ID dedup** and **O(N) linear-time replay**.

### Run

```bash
cd A
python -m pytest test_ledger.py -v
```

### Coverage

| Test | Description |
|------|-------------|
| `test_spec_example` | Spec walkthrough example |
| `test_idempotency_ok_replay` | Replay an accepted event → same result |
| `test_idempotency_rejected_replay` | Replay a rejected event → same error |
| `test_performance_200k` | 200 000 commands processed under 1 second |
| + 13 more | Edge cases: zero stock, over-release, over-ship, interleaved orders, malformed input… |

## Task B — Warehouse Allocation Optimiser

Dynamic-programming solver for a **3-tier optimisation**: minimise number of warehouses → minimise total cost → lexicographically smallest allocation vector.

### Run

```bash
cd B
python -m pytest test_optimiser.py -v
```

### Coverage

| Test | Description |
|------|-------------|
| `test_spec_example` | Spec walkthrough example |
| `test_impossible_insufficient_stock` | Total stock < qty → null |
| `test_two_warehouse_cost_tiebreak` | Equal cost → smallest indices win |
| `test_performance_worst_case` | W=30, Q=2000 completes under 5 seconds |
| + 9 more | Zero-unit cost, zero-fixed cost, large qty vs stock, lex tie-breaking… |

## Task C — Xero Integration Review

Six written answers covering connection verification, fault-tree analysis, incremental sync strategies, 429 handling, idempotent reconciliation, observability & security.

```
See C/answers.md
```

## Task App — Product Detail Page

### Backend (FastAPI + Pydantic)

Three endpoints — all in-memory, with **per-SKU asyncio locks** to prevent oversell under concurrency, and **Idempotency-Key header support** (1-hour TTL cache covering both success and rejection paths).

| Endpoint | Purpose |
|----------|---------|
| `GET  /api/products/{id}` | Product + SKUs + options |
| `POST /api/cart/items`     | Add SKU to cart (validates stock, idempotent) |
| `GET  /api/cart`           | View cart contents |

```bash
cd app/backend
python -m pytest test_api.py -v
```

**Tests (13):** happy path, validation errors, idempotency replay, stock depletion between requests, concurrent race for last unit.

### Frontend (React + TypeScript + Vite + Vitest + Testing Library)

Accessible PDP component with **ARIA radiogroups**, **blind variant resolution** (only disabling options whose paths no longer lead to any valid SKU), **double-click protection** on Add-to-Cart, and full **loading / error / out-of-stock / invalid-combination** state coverage.

```bash
cd app/frontend
npm install
npx vitest run
```

**Tests (5):** variant SKU resolution across option changes, button disabling for unavailable combinations, duplicate-click rejection, load error + retry, server-side insufficient-stock alert.

## Cross-Cutting Concerns

| Concern | Where addressed |
|---------|----------------|
| Idempotency | A (event-ID dedup hash-set), App backend (Idempotency-Key → response cache) |
| Concurrency safety | App backend (`asyncio.Lock` per SKU, acquired before stock decrement) |
| Accessibility | App frontend (`role="radiogroup"`, `aria-checked`, `aria-disabled`, `aria-live`, semantic `<fieldset>/<legend>`, `role="alert"` for errors) |
| Performance | A (O(N) scan), B (DP with memoised `(idx, remaining_qty, remaining_k)` state) |
| Testing | Every directory has a self-contained test suite runnable with `pytest` or `vitest run` |

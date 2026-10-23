# Task C — Xero Integration Review

> **Assumptions**
> - Xero Accounting API v3.0, OAuth 2.0 with `offline_access` scope for refresh tokens
> - A multi-tenant service stores `(tenant_id, access_token, refresh_token, expires_at, last_cursor)` per organisation
> - Python backend; HTTP client with built-in retry (e.g. `httpx` or `aiohttp`)

---

## C1 — Connection verification

Smallest sequence of calls to prove OAuth + tenant selection work **before** reading invoices:

| Step | Call | What it proves |
|------|------|----------------|
| 1 | `POST /oauth/token` with `refresh_token` (if expired) or `authorization_code` | Access token is valid OAuth 2.0; refresh_token rotation works |
| 2 | `GET /connections` with `Authorization: Bearer {token}` | Token is accepted by Xero; the response body lists each connected **tenant** (organisation) the user has granted access to. Each entry has `tenantId`, `tenantType`, `tenantName`. |
| 3 | `GET /3.0/Organisation` with `Xero-Tenant-Id: {tenantId}` header | Tenant header is correct; we have access to that specific organisation. Returns `OrganisationID`, `Name`, `LegalName`, `CountryCode`. |
| 4 | `GET /3.0/Invoices?page=1&modified-since=2000-01-01T00:00:00Z` | Read-scopes are present; invoices endpoint is reachable |

**Why this order:**
- Step 1-2 proves "can we authenticate + which tenants exist" without touching business data
- Step 3 proves the tenant header (a common source of 400s/403s)
- Step 4 is the actual business endpoint — at this point any failure is specific to the invoices scope

**References**
- Xero OAuth 2.0: https://developer.xero.com/documentation/guides/oauth2/auth-flow
- Connections endpoint: https://developer.xero.com/documentation/api/connections

---

## C2 — Failure diagnosis decision tree

```
GET /3.0/Invoices with valid-looking token + tenant header
│
├─ 401 Unauthorized
│   ├─ Check WWW-Authenticate header (Xero sets "error" param):
│   │   ├─ "invalid_token" → access token expired or revoked → refresh + retry ONCE
│   │   ├─ "invalid_client" → client_id/secret misconfigured → block, alert
│   │   └─ Unknown → log + escalate
│   └─ If refresh also 401 → refresh_token is dead → user must re-authorise
│
├─ 403 Forbidden
│   ├─ (A) Missing tenant header?
│   │     Xero returns 403 when no Xero-Tenant-Id sent. Verify header present.
│   ├─ (B) Wrong tenant_id for this token?
│   │     /connections returns the valid list; compare. Stale mapping in DB.
│   ├─ (C) Insufficient scopes?
│   │     Check Xero-App-Identifier + the "requires" error body; need
│   │     `accounting.invoices.read` (or `.write`) scope.
│   └─ (D) Organisation subscription status
│         Some error bodies hint at trial expiry or plan downgrade.
│
└─ 404 Not Found
    ├─ (A) Wrong base URL? (api.xero.com vs api-sandbox.xero.com)
    ├─ (B) Tenant is a demo company that was deleted
    │     (GET /connections → removed → 404 on data endpoints)
    ├─ (C) Organisation has no invoices table (very rare, data sync needed)
    └─ (D) Endpoint path typo (e.g. /Invoice vs /Invoices)
```

**Decision tree pseudocode:**

```python
async def diagnose_invoice_4xx(resp, org_record):
    if resp.status_code == 401:
        err = resp.headers.get("WWW-Authenticate", "")
        if "invalid_token" in err:
            if await try_refresh(org_record):
                return "RETRY_WITH_NEW_TOKEN"
            return "USER_MUST_REAUTH"
        return "BLOCK + ALERT"

    if resp.status_code == 403:
        if "Xero-Tenant-Id" not in sent_headers:
            return "MISSING_TENANT_HEADER"
        valid_tenants = await fetch_connections()
        if org_record.tenant_id not in valid_tenants:
            return "STALE_TENANT_MAPPING"
        if "requires" in resp.json().get("Errors", [{}])[0].get("Message", ""):
            return "SCOPE_MISSING"
        return "OTHER_403"

    if resp.status_code == 404:
        if org_record.tenant_id not in (await fetch_connections()):
            return "ORG_DELETED"
        return "CHECK_BASE_URL"
```

---

## C3 — Incremental synchronisation design

### Cursor model per organisation

```
{
  "org_id": "...",
  "cursor_timestamp": "2026-10-23T08:00:00Z",   # last successful modified-since
  "cursor_invoice_id": None,                     # resume-after pointer
  "sync_state": "running" | "paused" | "failed",
  "last_page_seen": None,
  "last_full_sync": "2026-09-01T00:00:00Z"       # periodic safety full-sync
}
```

### Algorithm (worker per org)

```
def sync_invoices(org):
    cursor = load_cursor(org)
    safe_window = 10 minutes                       # clock-skew guard
    since = (cursor.cursor_timestamp - safe_window).isoformat()

    page_no = 1
    local_ids_seen_this_run = set()                # dedupe within a run

    while True:
        resp = GET /3.0/Invoices
                 ?modified-since={since}
                 &page={page_no}
                 &IncludeArchived=false
                 &Xero-Tenant-Id={org.tenant_id}

        if resp.status_code == 429:  # → C4 rate-limit handler
        if resp.status_code in (401, 403):  # → C2 diagnosis

        invoices = resp.json()["Invoices"]
        if not invoices: break

        for inv in invoices:
            if inv["InvoiceID"] in local_ids_seen_this_run:
                continue                           # intra-page or cross-page dup
            local_ids_seen_this_run.add(inv["InvoiceID"])

            upsert_local(inv)                      # INSERT ON CONFLICT UPDATE
            cursor.cursor_timestamp = max(
                cursor.cursor_timestamp, inv["UpdatedDateUTC"]
            )                                        # advance per record
            checkpoint_cursor(org, cursor)           # durable save mid-run

        has_more = resp.json().get("HasMoreResults", False)
        if not has_more: break
        page_no += 1

    cursor.sync_state = "running"
    checkpoint_cursor(org, cursor)
```

### Key properties

| Concern | How we address it |
|---------|-------------------|
| **Pagination** | `HasMoreResults` + `page` param. Per-page checkpoint so we resume from correct page after crash. |
| **Change windows** | We always subtract a 5–10 min "safe window" from the cursor to catch late-arriving writes on Xero's side. Duplicates handled by `InvoiceID` uniqueness. |
| **Cursor persistence** | Stored in a durable DB row per organisation, updated **after each page**, never before. WAL / transactional write ensures crash safety. |
| **Duplicates** | `InvoiceID` (UUID) is the idempotency key at the DB level (`UNIQUE` constraint + `INSERT … ON CONFLICT UPDATE`). |
| **Partial failure** | If the worker dies mid-run, the restored cursor is still safely in the past (remember the safe window), so re-running from that point is correct. |
| **Safe replay** | Because the safe window guarantees overlap, replaying the same window yields no new inserts but does update any rows whose `UpdatedDateUTC` was stale. |
| **Long-term drift** | A nightly `FULL_SYNC` (modified-since far into the past → or no filter) reconciles any rows that slipped through incremental. |

---

## C4 — Handling HTTP 429 rate limits

Xero returns 429 with:
- `X-Rate-Limit-Reset`: Unix timestamp when the limit resets
- `Retry-After`: seconds to wait

### Response headers → concrete backoff

```python
def compute_backoff(resp, attempt):
    # 1. Prefer Xero's explicit reset time
    reset = resp.headers.get("X-Rate-Limit-Reset")
    if reset:
        wait = max(0, int(reset) - time.time())
    else:
        wait = int(resp.headers.get("Retry-After", 60))

    # 2. Add jitter to break thundering herd (±20%)
    jittered = wait * (0.8 + random.random() * 0.4)

    # 3. Also double as exponential backoff for repeated 429s
    expo = min(300, 2 ** attempt)  # cap at 5 minutes
    return min(jittered, expo)
```

### Per-org concurrency budget

```python
semaphores = defaultdict(lambda: asyncio.Semaphore(2))   # 2 in-flight per org

async def call_xero(org, request):
    async with semaphores[org.id]:
        for attempt in range(MAX_RETRIES):
            resp = await client.send(request)
            if resp.status_code == 429:
                sleep_for = compute_backoff(resp, attempt)
                logger.warning("429", org_id=org.id, sleep=sleep_for, attempt=attempt)
                await asyncio.sleep(sleep_for)
                continue
            return resp
        raise RateLimitExhausted()
```

### Retry budget

Global counter per org: `retries_last_hour`. If exceeded → pause sync, alert, let scheduler retry next hour with back-off delay.

**Do NOT retry these errors:**
| Code | Reason |
|------|--------|
| `400 Bad Request` | Malformed request (programmer error, no point retrying) |
| `401` without `invalid_token` | Client misconfig (no transient cause) |
| `403 Forbidden` scope errors | Permanent auth problem |
| `404` | Missing endpoint / deleted resource |
| `422 Unprocessable Entity` | Business validation failed |

### Job scheduling integration

When an org hits 429 repeatedly, emit a `rate_limited` metric → scheduler marks the org as `throttled_until={reset_time}` → won't dispatch for that org again until after reset.

---

## C5 — Preventing duplicate invoices on timeout

Xero uses **OAuth 2.0 + no idempotency-key header** for create-invoice calls. The canonical anti-duplicate pattern is an **application-level dedupe table**:

```sql
CREATE TABLE xero_invoice_dedupe (
    org_id         TEXT NOT NULL,
    local_order_id TEXT NOT NULL,
    xero_invoice_id TEXT,
    status         TEXT NOT NULL CHECK (status IN ('PENDING','ACKED','FAILED')),
    created_at     TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (org_id, local_order_id)
);
```

### Dedupe flow (creator side)

```python
def create_xero_invoice(org, local_order):
    with db_tx:
        row = db.execute(
            "INSERT INTO xero_invoice_dedupe (org_id, local_order_id, status)
             VALUES (%s, %s, 'PENDING')
             ON CONFLICT (org_id, local_order_id) DO UPDATE
               SET status = EXCLUDED.status
             RETURNING *",
            (org.id, local_order.id)
        ).one()

        if row.status == "ACKED":
            return row.xero_invoice_id   # already succeeded — idempotent short-circuit

        # Call Xero
        resp = POST /3.0/Invoices  body={...}

        if resp.status_code == 200:
            xero_id = resp.json()["Invoices"][0]["InvoiceID"]
            db.execute("UPDATE ... SET status='ACKED', xero_invoice_id=...")
            return xero_id

        if resp.status_code == 400 or resp.status_code == 409:
            # 409 Conflict: Xero may have actually created it; reconcile below
            db.execute("UPDATE ... SET status='FAILED'")
            return reconcile_xero_for_local_order(org, local_order.id)

        # Anything else → leave row as PENDING; will retry later
        raise XeroCreateFailed()
```

### Reconciliation (request succeeded but response lost)

When we get a timeout / 5xx and cannot know whether Xero created the invoice:

```python
def reconcile_xero_for_local_order(org, local_order_id):
    # Xero has no direct lookup by our local_id, so we scan recently created
    # invoices and match on an OUTLYING field we stamp:
    # POST body includes "Reference": "ORD-12345" (our local id)
    # After a timeout we do:
    # GET /3.0/Invoices?modified-since={ten_minutes_ago}&where=Reference=="ORD-12345"
    matches = resp.json()["Invoices"]
    if matches:
        xero_id = matches[0]["InvoiceID"]
        db.execute("UPDATE dedupe SET status='ACKED', xero_invoice_id=...")
        return xero_id
    # If no match → it truly failed; leave dedupe row as PENDING
    return None
```

### Outbox pattern for extra safety

An **outbox table** (`xero_outbox_messages`) with `(org_id, local_order_id, payload, status)` is written transactionally with local state. A separate relay worker picks up `PENDING` rows and performs the Xero POST → retries → marks `SENT` or `FAILED`. This decouples Xero availability from the main order flow.

---

## C6 — Observability & security

### Logs (structured JSON, always include trace_id + org_id)

| Event | Fields |
|-------|--------|
| `xero_api_call` | trace_id, org_id, tenant_id, method, path, status, latency_ms, retry_count, rate_limit_reset_ts |
| `xero_token_refresh` | trace_id, org_id, result (success/fail), latency_ms |
| `xero_sync_page` | trace_id, org_id, page_no, n_invoices, cursor_before, cursor_after, has_more |
| `xero_sync_completed` | trace_id, org_id, total_invoices, duration_ms, dedupe_hits, new_rows |
| `xero_dedupe_hit` | trace_id, org_id, local_order_id, xero_invoice_id (no invoice content!) |
| `xero_reconcile_miss` | trace_id, org_id, local_order_id — potential orphan |

**MUST NEVER log:**
- `access_token`, `refresh_token`, `client_secret`, full `Authorization` header
- Customer invoice content, contact details, line items (PII)
- The raw request/response bodies (strip or truncate to non-sensitive fields only)

### Metrics (Prometheus style)

| Metric | Type | Labels |
|--------|------|--------|
| `xero_api_requests_total` | Counter | org_id, path, status |
| `xero_api_request_latency_seconds` | Histogram | org_id, path |
| `xero_api_429_total` | Counter | org_id |
| `xero_sync_invoices_synced_total` | Counter | org_id |
| `xero_sync_duration_seconds` | Histogram | org_id |
| `xero_token_refresh_failures_total` | Counter | org_id |
| `xero_dedupe_conflicts_total` | Counter | org_id |

### Alerts

| Condition | Severity |
|-----------|----------|
| `xero_api_429_total` per org > 10 in 1h | P2 — investigate traffic pattern |
| `xero_token_refresh_failures_total` > 0 in 5 min | P1 — auth broken |
| Any org without a successful sync for > 30 min while others succeed | P2 — per-tenant problem |
| `xero_reconcile_miss` events > 0 | P2 — likely duplicates or orphaned orders |
| `xero_sync_duration_seconds` p99 > 10 min | P3 — large org may need horizontal scaling |

### Correlation identifiers

- Every internal request gets a `trace_id` (W3C Trace Context header)
- Xero API calls include `X-Correlation-Id: {trace_id}` — Xero logs it on their side too
- `org_id` + `tenant_id` + `trace_id` form a unique trio for cross-referencing between our logs and Xero support

### Secrets storage & rotation

```
# NEVER in repo; use a secrets manager
# AWS Secrets Manager / GCP Secret Manager / HashiCorp Vault / Azure Key Vault

per-org secrets stored:
  xero_client_id          (stable per app, shared)
  xero_client_secret      (per app, rotated every 90 days)
  xero_access_token       (short-lived — refreshed before each expiry)
  xero_refresh_token      (stored encrypted; rotated on each use!)
```

**Rotation policy:**
1. On every refresh, Xero issues a **new refresh_token** (one-time-use rotation). We persist the new one and discard the old.
2. If we ever get 401 on a refresh, the old refresh_token is revoked by Xero — user must re-authorise.
3. Client_secret rotation app-side: read from secret manager, gracefully periodical rotation without downtime.

**Encryption at rest:** Refresh tokens encrypted with AES-256-GCM using a key held in KMS — only the sync workers can decrypt them. DB backups are encrypted via the platform (RDS encryption, disk encryption).

---

## Reference links

- Xero Developer Portal: https://developer.xero.com/
- OAuth 2.0 Auth Flow: https://developer.xero.com/documentation/guides/oauth2/auth-flow
- Connections API: https://developer.xero.com/documentation/api/connections
- Invoices API: https://developer.xero.com/documentation/api/invoices
- Xero Rate Limits: https://developer.xero.com/documentation/getting-started/api-rate-limits
- Idempotency for Xero: https://developer.xero.com/documentation/guides/oauth2/idempotency

**Assumptions about SDK version**
All calls described are raw REST using Python `httpx`. We avoid heavy SDKs for visibility over headers/error shapes. If the team standardises on the official `xero-python` SDK (`pip install xero-python`), the patterns above still hold — the SDK is just a thin wrapper around the same REST contract.

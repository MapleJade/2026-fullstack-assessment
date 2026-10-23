"""Task A tests - Inventory Reservation Ledger."""

from __future__ import annotations

import io
import sys
import time

sys.path.insert(0, ".")
sys.path.insert(0, "..")

from ledger import (  # noqa: E402
    Ledger,
    OK,
    REJECTED,
    DUPLICATE,
    parse_line,
    run,
)


# ---------------------------------------------------------------------------
# 1. Spec example (golden test)
# ---------------------------------------------------------------------------

def test_spec_example():
    ledger = Ledger(10)
    assert ledger.handle("RESERVE", "e1", "o100", 4) == OK
    assert ledger.on_hand == 10 and ledger.reserved_total == 4

    assert ledger.handle("RESERVE", "e2", "o200", 7) == REJECTED
    assert ledger.on_hand == 10 and ledger.reserved_total == 4

    assert ledger.handle("SHIP", "e3", "o100", 2) == OK
    assert ledger.on_hand == 8 and ledger.reserved_total == 2

    assert ledger.handle("RELEASE", "e4", "o100", 2) == OK
    assert ledger.on_hand == 8 and ledger.reserved_total == 0

    assert ledger.handle("RESTOCK", "e5", None, 3) == OK
    assert ledger.on_hand == 11 and ledger.reserved_total == 0

    # replay previous event_id — originally REJECTED, still DUPLICATE
    assert ledger.handle("RESERVE", "e2", "o999", 1) == DUPLICATE
    assert ledger.on_hand == 11 and ledger.reserved_total == 0

    assert ledger.open_reservations() == []


# ---------------------------------------------------------------------------
# 2. Idempotency — OK path replay
# ---------------------------------------------------------------------------

def test_idempotency_ok_replay():
    ledger = Ledger(5)
    assert ledger.handle("RESERVE", "e1", "o1", 3) == OK
    assert ledger.handle("RESERVE", "e1", "o1", 3) == DUPLICATE
    assert ledger.handle("RESERVE", "e1", "o1", 999) == DUPLICATE  # diff args, same event_id
    assert ledger.on_hand == 5 and ledger.reserved_total == 3
    assert ledger.order_reserved["o1"] == 3


# ---------------------------------------------------------------------------
# 3. Idempotency — REJECTED path replay (critical!)
# ---------------------------------------------------------------------------

def test_idempotency_rejected_replay():
    ledger = Ledger(2)
    assert ledger.handle("RESERVE", "e1", "o1", 5) == REJECTED
    assert ledger.handle("RESERVE", "e1", "o1", 5) == DUPLICATE
    assert ledger.on_hand == 2 and ledger.reserved_total == 0

    # After restocking, that REJECTED event_id is still DUPLICATE
    assert ledger.handle("RESTOCK", "e2", None, 100) == OK
    assert ledger.handle("RESERVE", "e1", "o1", 5) == DUPLICATE
    assert ledger.on_hand == 102


# ---------------------------------------------------------------------------
# 4. Edge — initial stock 0
# ---------------------------------------------------------------------------

def test_initial_zero_stock():
    ledger = Ledger(0)
    assert ledger.handle("RESERVE", "e1", "o1", 1) == REJECTED
    assert ledger.handle("RESTOCK", "e2", None, 5) == OK
    assert ledger.handle("RESERVE", "e3", "o1", 5) == OK
    assert ledger.available == 0


# ---------------------------------------------------------------------------
# 5. Edge — qty exactly equals available
# ---------------------------------------------------------------------------

def test_exact_available():
    ledger = Ledger(10)
    assert ledger.handle("RESERVE", "e1", "o1", 10) == OK
    assert ledger.available == 0
    assert ledger.handle("RESERVE", "e2", "o2", 1) == REJECTED


# ---------------------------------------------------------------------------
# 6. RELEASE/SHIP cannot exceed order's reserved amount
# ---------------------------------------------------------------------------

def test_release_ship_exceed_reserved():
    ledger = Ledger(10)
    ledger.handle("RESERVE", "e1", "o1", 3)
    ledger.handle("RESERVE", "e2", "o2", 2)

    assert ledger.handle("RELEASE", "e3", "o1", 5) == REJECTED
    assert ledger.handle("SHIP", "e4", "o2", 10) == REJECTED
    assert ledger.reserved_total == 5

    # order_id never reserved anything
    assert ledger.handle("RELEASE", "e5", "nobody", 1) == REJECTED


# ---------------------------------------------------------------------------
# 7. SHIP reduces both on_hand and reserved
# ---------------------------------------------------------------------------

def test_ship_reduces_both():
    ledger = Ledger(10)
    ledger.handle("RESERVE", "e1", "o1", 6)
    result = ledger.handle("SHIP", "e2", "o1", 4)
    assert result == OK
    assert ledger.on_hand == 6
    assert ledger.reserved_total == 2
    assert ledger.order_reserved["o1"] == 2


# ---------------------------------------------------------------------------
# 8. RELEASE removes order from map when qty hits 0
# ---------------------------------------------------------------------------

def test_release_clears_order_entry():
    ledger = Ledger(5)
    ledger.handle("RESERVE", "e1", "o1", 3)
    ledger.handle("RELEASE", "e2", "o1", 3)
    assert "o1" not in ledger.order_reserved
    assert ledger.reserved_total == 0


# ---------------------------------------------------------------------------
# 9. RESTOCK non-positive qty rejected
# ---------------------------------------------------------------------------

def test_restock_non_positive():
    ledger = Ledger(5)
    # qty=0 and qty negative won't pass parse_line so we test via handle
    assert ledger.handle("RESTOCK", "e1", None, 0) == REJECTED
    assert ledger.handle("RESTOCK", "e2", None, -1) == REJECTED
    assert ledger.on_hand == 5


# ---------------------------------------------------------------------------
# 10. Unknown action
# ---------------------------------------------------------------------------

def test_unknown_action():
    ledger = Ledger(5)
    assert ledger.handle("INVENT", "e1", "o1", 1) == REJECTED


# ---------------------------------------------------------------------------
# 11. Large quantities (10^12)
# ---------------------------------------------------------------------------

def test_large_quantities():
    huge = 10**12
    ledger = Ledger(huge)
    assert ledger.handle("RESERVE", "e1", "o1", huge) == OK
    assert ledger.available == 0
    assert ledger.handle("RELEASE", "e2", "o1", huge) == OK
    assert ledger.on_hand == huge


# ---------------------------------------------------------------------------
# 12. open_reservations sorted by order_id
# ---------------------------------------------------------------------------

def test_open_reservations_sorted():
    ledger = Ledger(100)
    ledger.handle("RESERVE", "e1", "z", 1)
    ledger.handle("RESERVE", "e2", "a", 2)
    ledger.handle("RESERVE", "e3", "m", 3)
    assert ledger.open_reservations() == [("a", 2), ("m", 3), ("z", 1)]


# ---------------------------------------------------------------------------
# 13. Interleaved orders — correct per-order tracking
# ---------------------------------------------------------------------------

def test_interleaved_orders():
    ledger = Ledger(20)
    ledger.handle("RESERVE", "e1", "o1", 5)
    ledger.handle("RESERVE", "e2", "o2", 7)
    ledger.handle("RELEASE", "e3", "o1", 3)
    ledger.handle("SHIP", "e4", "o2", 2)
    # o1 reserved=2, o2 reserved=5
    assert ledger.reserved_total == 7
    assert ledger.on_hand == 18  # 20 - 2 (shipped)
    assert ledger.order_reserved == {"o1": 2, "o2": 5}


# ---------------------------------------------------------------------------
# 14. parse_line malformed
# ---------------------------------------------------------------------------

def test_parse_line_malformed():
    assert parse_line("") is None
    assert parse_line("RESERVE") is None
    assert parse_line("RESERVE e1 o1 -5") is None
    assert parse_line("RESERVE e1 o1 abc") is None
    assert parse_line("RESERVE e1") is None
    assert parse_line("RESTOCK") is None
    assert parse_line("RESTOCK e1 0") is None
    assert parse_line("RESTOCK e1 -1") is None
    assert parse_line("FOO e1 o1 1") is None
    # valid
    assert parse_line("RESERVE e1 o1 1") == ("RESERVE", "e1", "o1", 1)
    assert parse_line("restock e2 5") == ("RESTOCK", "e2", None, 5)


# ---------------------------------------------------------------------------
# 15. run() end-to-end (spec example via stdio)
# ---------------------------------------------------------------------------

def test_run_spec_example(capsys):
    stdin = io.StringIO(
        "10 6\n"
        "RESERVE e1 o100 4\n"
        "RESERVE e2 o200 7\n"
        "SHIP e3 o100 2\n"
        "RELEASE e4 o100 2\n"
        "RESTOCK e5 3\n"
        "RESERVE e2 o999 1\n"
    )
    stdout = io.StringIO()
    run(stdin=stdin, stdout=stdout)
    lines = stdout.getvalue().strip().split("\n")
    assert lines == [
        "OK 10 4",
        "REJECTED 10 4",
        "OK 8 2",
        "OK 8 0",
        "OK 11 0",
        "DUPLICATE 11 0",
        "OPEN 0",
    ]


# ---------------------------------------------------------------------------
# 16. run() — replay an entire log from the start (critical for idempotency)
# ---------------------------------------------------------------------------

def test_same_ledger_replay():
    """On a *single* Ledger, running the same log twice -> second pass all DUPLICATE."""
    ledger = Ledger(5)
    cmds = [
        ("RESERVE", "e1", "o1", 3),
        ("SHIP", "e2", "o1", 2),
        ("RELEASE", "e3", "o1", 1),
        ("RESTOCK", "e4", None, 10),
    ]

    first_results = [ledger.handle(*c) for c in cmds]
    assert first_results == [OK, OK, OK, OK]
    final_on_hand, final_reserved = ledger.on_hand, ledger.reserved_total

    second_results = [ledger.handle(*c) for c in cmds]
    assert second_results == [DUPLICATE] * 4
    # State must be byte-identical
    assert ledger.on_hand == final_on_hand
    assert ledger.reserved_total == final_reserved
    assert ledger.order_reserved == {}  # fully released/shipped entries are cleaned up
    assert ledger.open_reservations() == []


# ---------------------------------------------------------------------------
# 17. Performance — 200 000 commands must finish comfortably
# ---------------------------------------------------------------------------

def test_performance_200k():
    n = 200_000
    ledger = Ledger(n)

    # All successful RESERVE of 1 unit
    t0 = time.perf_counter()
    for i in range(n):
        assert ledger.handle("RESERVE", f"e{i}", f"o{i}", 1) == OK
    elapsed = time.perf_counter() - t0

    assert elapsed < 5.0, f"200k RESERVE took {elapsed:.2f}s — too slow"
    assert ledger.reserved_total == n
    assert ledger.on_hand == n

    # Idempotency pass — all DUPLICATE
    t0 = time.perf_counter()
    for i in range(n):
        assert ledger.handle("RESERVE", f"e{i}", f"o{i}", 1) == DUPLICATE
    elapsed2 = time.perf_counter() - t0
    assert elapsed2 < 5.0

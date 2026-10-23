"""Task B tests - Fulfilment Split Optimiser."""

from __future__ import annotations

import io
import sys
import time

sys.path.insert(0, ".")
sys.path.insert(0, "..")

from optimiser import Warehouse, solve, run  # noqa: E402


# ---------------------------------------------------------------------------
# 1. Spec example (golden test)
# ---------------------------------------------------------------------------

def test_spec_example():
    whs = [
        Warehouse("AU", 5, 8, 2),
        Warehouse("CN", 7, 20, 1),
        Warehouse("US", 4, 3, 4),
    ]
    k, cost, allocs = solve(whs, 7)
    assert k == 1
    assert cost == 27
    assert allocs == [("CN", 7)]


# ---------------------------------------------------------------------------
# 2. Impossible — sum of stock < Q
# ---------------------------------------------------------------------------

def test_impossible_insufficient_stock():
    whs = [
        Warehouse("A", 2, 0, 1),
        Warehouse("B", 3, 0, 1),
    ]
    assert solve(whs, 10) is None
    assert solve(whs, 6) is None  # 2+3=5 < 6


# ---------------------------------------------------------------------------
# 3. Zero-stock warehouses must be skipped
# ---------------------------------------------------------------------------

def test_zero_stock_warehouses():
    whs = [
        Warehouse("EMPTY", 0, 100, 1),
        Warehouse("FULL", 10, 5, 2),
    ]
    k, cost, allocs = solve(whs, 5)
    assert k == 1
    assert cost == 5 + 5 * 2  # 15
    assert allocs == [("FULL", 5)]


# ---------------------------------------------------------------------------
# 4. Tie-break — same k, same cost → lexicographically smallest
# ---------------------------------------------------------------------------

def test_tiebreak_lexicographic():
    # Two warehouses both give cost 10 for Q=5 with k=1
    # A: fixed 0, unit 2 → cost 10 (stock 5)
    # B: fixed 5, unit 1 → cost 5+5=10 (stock 5)
    # C: fixed 10, unit 0 → cost 10 (stock 5)
    # All cost same; lex smallest warehouse_id wins
    whs = [
        Warehouse("C", 5, 10, 0),
        Warehouse("B", 5, 5, 1),
        Warehouse("A", 5, 0, 2),
    ]
    k, cost, allocs = solve(whs, 5)
    assert k == 1
    assert cost == 10
    assert allocs == [("A", 5)]  # lexicographically smallest id among ties


# ---------------------------------------------------------------------------
# 5. k=1 impossible; k=2 is the minimum warehouse count
# ---------------------------------------------------------------------------

def test_two_warehouses_minimum_k():
    # No single warehouse has stock >= Q, so k=1 infeasible.
    # k=2: Y+Z supply exactly Q=10 with minimal cost.
    whs = [
        Warehouse("X", 3, 0, 100),  # too small for k=1
        Warehouse("Y", 5, 0, 1),
        Warehouse("Z", 5, 0, 1),
    ]
    k, cost, allocs = solve(whs, 10)
    assert k == 2
    assert cost == 10
    assert allocs == [("Y", 5), ("Z", 5)]


# ---------------------------------------------------------------------------
# 6. k=2 tie-break with same warehouse count but different costs
# ---------------------------------------------------------------------------

def test_two_warehouse_cost_tiebreak():
    # Three pairs of warehouses each capable of supplying Q=10 with k=2
    # Pairs and costs: (A,B)=20, (C,D)=15, (E,F)=25 → pick (C,D)
    whs = [
        Warehouse("A", 5, 5, 1),
        Warehouse("B", 5, 5, 1),  # pair AB: 5+5+5+5 = 20
        Warehouse("C", 5, 3, 1),
        Warehouse("D", 5, 3, 1),  # pair CD: 3+5+3+5 = 16? wait...
    ]
    # Let's recalculate to avoid mistakes
    # AB: (5 + 5*1) + (5 + 5*1) = 10 + 10 = 20
    # CD: (3 + 5*1) + (3 + 5*1) = 8 + 8 = 16
    whs = [
        Warehouse("A", 5, 5, 1),
        Warehouse("B", 5, 5, 1),
        Warehouse("C", 5, 3, 1),
        Warehouse("D", 5, 3, 1),
    ]
    k, cost, allocs = solve(whs, 10)
    assert k == 2
    assert cost == 16
    assert allocs == [("C", 5), ("D", 5)]


# ---------------------------------------------------------------------------
# 7. Lex tie-break within k=2 (both pairs same cost)
# ---------------------------------------------------------------------------

def test_two_warehouse_lex_tie():
    # All warehouse pairs cost the same (20 for Q=10 with k=2).
    # Lexicographically smallest pair wins after sorting by warehouse_id.
    whs = [
        Warehouse("B", 5, 5, 1),
        Warehouse("C", 5, 5, 1),
        Warehouse("A", 5, 5, 1),
        Warehouse("Z", 5, 5, 1),
    ]
    k, cost, allocs = solve(whs, 10)
    assert k == 2
    assert cost == 20
    # After sort: A, B, C, Z. Smallest pair is (A, B).
    assert allocs == [("A", 5), ("B", 5)]


# ---------------------------------------------------------------------------
# 8. Stock larger than Q
# ---------------------------------------------------------------------------

def test_large_stock_vs_q():
    whs = [
        Warehouse("A", 1000, 10, 5),  # can supply Q=10 alone: 10 + 10*5 = 60
    ]
    k, cost, allocs = solve(whs, 10)
    assert k == 1
    assert cost == 60
    assert allocs == [("A", 10)]


# ---------------------------------------------------------------------------
# 9. unit_cost=0 case — all qty free, pay only fixed
# ---------------------------------------------------------------------------

def test_zero_unit_cost():
    whs = [
        Warehouse("X", 10, 100, 0),  # fixed 100, free units
        Warehouse("Y", 10, 50, 0),   # fixed 50, free units
    ]
    k, cost, allocs = solve(whs, 5)
    assert k == 1
    assert cost == 50  # pick Y (lower fixed)
    assert allocs == [("Y", 5)]


# ---------------------------------------------------------------------------
# 10. fixed_cost=0 case — pay only per-unit
# ---------------------------------------------------------------------------

def test_zero_fixed_cost():
    whs = [
        Warehouse("X", 10, 0, 10),  # 10 per unit
        Warehouse("Y", 10, 0, 3),   # 3 per unit — much cheaper
    ]
    k, cost, allocs = solve(whs, 5)
    assert k == 1
    assert cost == 15
    assert allocs == [("Y", 5)]


# ---------------------------------------------------------------------------
# 11. Full input driver test
# ---------------------------------------------------------------------------

def test_run_driver(capsys):
    stdin = io.StringIO(
        "3 7\n"
        "AU 5 8 2\n"
        "CN 7 20 1\n"
        "US 4 3 4\n"
    )
    stdout = io.StringIO()
    run(stdin=stdin, stdout=stdout)
    assert stdout.getvalue() == "1 27\nCN 7\n"


def test_run_impossible():
    stdin = io.StringIO("2 10\nA 2 0 1\nB 3 0 1\n")
    stdout = io.StringIO()
    run(stdin=stdin, stdout=stdout)
    assert stdout.getvalue() == "-1\n"


# ---------------------------------------------------------------------------
# 12. Performance — W=30, Q=2000 worst case
# ---------------------------------------------------------------------------

def test_performance_worst_case():
    import random
    random.seed(42)

    whs = [
        Warehouse(
            f"W{i:03d}",
            stock=random.randint(500, 2000),
            fixed=random.randint(0, 100),
            unit=random.randint(0, 10),
        )
        for i in range(30)
    ]
    Q = 2000

    t0 = time.perf_counter()
    result = solve(whs, Q)
    elapsed = time.perf_counter() - t0

    assert elapsed < 5.0, f"Worst case took {elapsed:.2f}s — too slow"
    assert result is not None
    k, cost, allocs = result
    total = sum(q for _, q in allocs)
    assert total == Q
    assert k <= 30

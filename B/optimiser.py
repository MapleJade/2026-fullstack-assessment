"""Task B - Fulfilment Split Optimiser.

Given W warehouses, choose exactly Q units while:
  1. Minimising the number of warehouses used.
  2. Then minimising total cost (fixed + unit * qty per used warehouse).
  3. Then lexicographically smallest allocation list when sorted by warehouse_id.

Approach
--------
Warehouses are sorted by id up front. We enumerate warehouse count k
from 1..W (smallest first) and return the first feasible solution — that
gives tie-break #1 for free. Within a fixed k, a memoised DP over
  (index, remaining_qty, remaining_k)
returns (cost, selected_index_tuple, alloc_qty_tuple) and uses tuple
comparison on the allocations for tie-break #3.

Time / Space
------------
States: O(W * Q * W) = O(30 * 2000 * 30) = 1.8M; very comfortable.
Each state iterates min(stock, remaining_qty) ≥ 1, but remaining_k prunes
most branches early, so typical runtime is well under a second.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional


@dataclass(frozen=True)
class Warehouse:
    wid: str
    stock: int
    fixed: int
    unit: int


def solve(warehouses: list[Warehouse], q: int) -> Optional[tuple[int, int, list[tuple[str, int]]]]:
    """Return (k, total_cost, [(wid, qty), ...] sorted by wid) or None."""
    if q <= 0:
        return None

    whs = sorted(warehouses, key=lambda w: w.wid)
    W = len(whs)

    if sum(w.stock for w in whs) < q:
        return None

    suffix_stock = [0] * (W + 1)
    for i in range(W - 1, -1, -1):
        suffix_stock[i] = suffix_stock[i + 1] + whs[i].stock

    @lru_cache(maxsize=None)
    def rec(
        idx: int, remaining_q: int, need_k: int
    ) -> Optional[tuple[int, tuple[int, ...], tuple[int, ...]]]:
        if remaining_q == 0 and need_k == 0:
            return (0, (), ())
        if idx == W or remaining_q <= 0 or need_k <= 0:
            return None
        if remaining_q < need_k:
            return None
        if remaining_q > suffix_stock[idx]:
            return None
        if need_k > W - idx:
            return None

        best_cost = 10**18
        best_alloc: tuple[int, ...] = ()
        best_idx: tuple[int, ...] = ()

        skip = rec(idx + 1, remaining_q, need_k)
        if skip is not None:
            sc, si, sa = skip
            best_cost, best_idx, best_alloc = sc, si, sa

        wh = whs[idx]
        ss = suffix_stock[idx + 1]

        if need_k == 1:
            a = remaining_q
            if 1 <= a <= wh.stock:
                sub = rec(idx + 1, 0, 0)
                if sub is not None:
                    sub_cost, sub_idx, sub_alloc = sub
                    total_cost = sub_cost + wh.fixed + a * wh.unit
                    cand_alloc = (a,) + sub_alloc
                    cand_idx = (idx,) + sub_idx
                    if total_cost < best_cost or (
                        total_cost == best_cost and (cand_alloc, cand_idx) < (best_alloc, best_idx)
                    ):
                        best_cost = total_cost
                        best_alloc = cand_alloc
                        best_idx = cand_idx
        else:
            max_a = min(wh.stock, remaining_q)
            min_a = max(1, remaining_q - ss)
            for a in range(min_a, max_a + 1):
                sub = rec(idx + 1, remaining_q - a, need_k - 1)
                if sub is None:
                    continue
                sub_cost, sub_idx, sub_alloc = sub
                total_cost = sub_cost + wh.fixed + a * wh.unit
                cand_alloc = (a,) + sub_alloc
                cand_idx = (idx,) + sub_idx
                if total_cost < best_cost or (
                    total_cost == best_cost and (cand_alloc, cand_idx) < (best_alloc, best_idx)
                ):
                    best_cost = total_cost
                    best_alloc = cand_alloc
                    best_idx = cand_idx

        if best_cost == 10**18:
            return None
        return (best_cost, best_idx, best_alloc)

    for k in range(1, W + 1):
        res = rec(0, q, k)
        if res is not None:
            cost, sel_idx, alloc = res
            chosen: list[tuple[str, int]] = []
            for i, a in zip(sel_idx, alloc):
                chosen.append((whs[i].wid, a))
            return (k, cost, chosen)

    return None


# ---------------------------------------------------------------------------
# I/O driver
# ---------------------------------------------------------------------------

def parse_input(text: str) -> tuple[int, int, list[Warehouse]]:
    lines = text.splitlines()
    if not lines:
        raise ValueError("empty input")
    first = lines[0].split()
    if len(first) != 2:
        raise ValueError("first line must be 'W Q'")
    W, Q = int(first[0]), int(first[1])

    warehouses: list[Warehouse] = []
    for raw in lines[1 : 1 + W]:
        tok = raw.split()
        if len(tok) != 4:
            raise ValueError(f"warehouse line must have 4 tokens: {raw!r}")
        wid, stock, fixed, unit = tok[0], int(tok[1]), int(tok[2]), int(tok[3])
        warehouses.append(Warehouse(wid, stock, fixed, unit))
    return W, Q, warehouses


def run(stdin=sys.stdin, stdout=sys.stdout) -> None:
    text = stdin.read()
    _W, Q, warehouses = parse_input(text)
    result = solve(warehouses, Q)
    if result is None:
        stdout.write("-1\n")
        return
    k, cost, allocs = result
    stdout.write(f"{k} {cost}\n")
    for wid, qty in allocs:
        stdout.write(f"{wid} {qty}\n")


if __name__ == "__main__":
    run()

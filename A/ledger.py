"""Task A - Inventory Reservation Ledger.

A deterministic command processor for a single SKU. Tracks on_hand,
reserved totals, per-order reservation amounts, and processed event_ids
for idempotent replay.

Usage:
    python ledger.py < input.txt

Or programmatically:
    from ledger import Ledger, process_line
"""

from __future__ import annotations

import sys
from typing import Optional


# ---------------------------------------------------------------------------
# Result tuple / status codes
# ---------------------------------------------------------------------------

OK = "OK"
REJECTED = "REJECTED"
DUPLICATE = "DUPLICATE"


class Ledger:
    """Single-SKU reservation ledger with idempotent event processing."""

    __slots__ = (
        "on_hand",
        "reserved_total",
        "order_reserved",
        "processed",
    )

    def __init__(self, initial_stock: int = 0) -> None:
        if initial_stock < 0:
            raise ValueError("initial_stock must be non-negative")
        self.on_hand: int = initial_stock
        self.reserved_total: int = 0
        self.order_reserved: dict[str, int] = {}
        self.processed: dict[str, str] = {}  # event_id -> last-result (OK/REJECTED)

    # -- derived ----------------------------------------------------------

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved_total

    # -- command handler --------------------------------------------------

    def handle(
        self,
        action: str,
        event_id: str,
        order_id: Optional[str],
        qty: int,
    ) -> str:
        """Process one command. Returns one of OK / REJECTED / DUPLICATE.

        Idempotency rule: an event_id that has been seen before (regardless
        of whether its previous execution was OK or REJECTED) returns
        DUPLICATE and does not touch state.
        """
        if event_id in self.processed:
            return DUPLICATE

        action = action.upper()

        if action == "RESERVE":
            result = self._reserve(order_id, qty)
        elif action == "RELEASE":
            result = self._release(order_id, qty)
        elif action == "SHIP":
            result = self._ship(order_id, qty)
        elif action == "RESTOCK":
            result = self._restock(qty)
        else:
            result = REJECTED

        self.processed[event_id] = result
        return result

    # -- individual operations -------------------------------------------

    def _reserve(self, order_id: Optional[str], qty: int) -> str:
        if order_id is None or qty <= 0:
            return REJECTED
        if self.available < qty:
            return REJECTED
        self.reserved_total += qty
        self.order_reserved[order_id] = self.order_reserved.get(order_id, 0) + qty
        return OK

    def _release(self, order_id: Optional[str], qty: int) -> str:
        if order_id is None or qty <= 0:
            return REJECTED
        current = self.order_reserved.get(order_id, 0)
        if current < qty:
            return REJECTED
        self.order_reserved[order_id] = current - qty
        self.reserved_total -= qty
        if self.order_reserved[order_id] == 0:
            del self.order_reserved[order_id]
        return OK

    def _ship(self, order_id: Optional[str], qty: int) -> str:
        if order_id is None or qty <= 0:
            return REJECTED
        current = self.order_reserved.get(order_id, 0)
        if current < qty:
            return REJECTED
        self.order_reserved[order_id] = current - qty
        self.reserved_total -= qty
        self.on_hand -= qty
        if self.order_reserved[order_id] == 0:
            del self.order_reserved[order_id]
        return OK

    def _restock(self, qty: int) -> str:
        if qty <= 0:
            return REJECTED
        self.on_hand += qty
        return OK

    # -- output helpers ---------------------------------------------------

    def open_reservations(self) -> list[tuple[str, int]]:
        return sorted(self.order_reserved.items())


# ---------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------

def parse_line(line: str) -> tuple[str, str, Optional[str], int] | None:
    """Parse one command line.

    Returns (action, event_id, order_id_or_None, qty) or None on malformed.
    Validation here is purely syntactic; business checks happen in Ledger.
    """
    tokens = line.split()
    if not tokens:
        return None
    action = tokens[0].upper()

    if action == "RESTOCK":
        if len(tokens) != 3:
            return None
        event_id, qty_str = tokens[1], tokens[2]
        if not event_id or not qty_str.isdigit():
            return None
        qty = int(qty_str)
        if qty <= 0:
            return None
        return action, event_id, None, qty

    if action in ("RESERVE", "RELEASE", "SHIP"):
        if len(tokens) != 4:
            return None
        event_id, order_id, qty_str = tokens[1], tokens[2], tokens[3]
        if not event_id or not order_id or not qty_str.isdigit():
            return None
        qty = int(qty_str)
        if qty <= 0:
            return None
        return action, event_id, order_id, qty

    return None


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def run(stdin=sys.stdin, stdout=sys.stdout) -> None:
    first = stdin.readline()
    if not first:
        return
    parts = first.split()
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        return
    initial = int(parts[0])
    n = int(parts[1])

    ledger = Ledger(initial)
    lines = stdin.read().splitlines()

    for raw in lines[:n]:
        parsed = parse_line(raw)
        if parsed is None:
            # Malformed input is rejected but — per spec — we still need an
            # event_id to record idempotency. A truly malformed line has no
            # event_id, so we treat it as a silent REJECTED with no event
            # tracking (cannot happen in well-formed contest inputs, but we
            # handle it gracefully).
            stdout.write(f"{REJECTED} {ledger.on_hand} {ledger.reserved_total}\n")
            continue

        action, event_id, order_id, qty = parsed
        result = ledger.handle(action, event_id, order_id, qty)
        stdout.write(f"{result} {ledger.on_hand} {ledger.reserved_total}\n")

    # Final open reservations
    open_list = ledger.open_reservations()
    if open_list:
        out = " ".join(f"{oid} {q}" for oid, q in open_list)
        stdout.write(f"OPEN {out}\n")
    else:
        stdout.write("OPEN 0\n")


if __name__ == "__main__":
    run()

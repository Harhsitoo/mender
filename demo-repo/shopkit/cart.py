"""Shopping cart arithmetic.

All money is handled in integer cents. Floating point currency is a bug
waiting to happen, so the only float this module produces is a deliberate
average.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LineItem:
    """One SKU in a cart, at a quantity and a price."""

    sku: str
    quantity: int
    unit_price_cents: int

    def __post_init__(self) -> None:
        if self.quantity < 1:
            raise ValueError(f"quantity must be at least 1, got {self.quantity}")
        if self.unit_price_cents < 0:
            raise ValueError("unit_price_cents cannot be negative")

    @property
    def subtotal_cents(self) -> int:
        return self.quantity * self.unit_price_cents


class Cart:
    """A collection of line items with the usual totals."""

    def __init__(self, items: list[LineItem] | None = None) -> None:
        self._items: list[LineItem] = list(items or [])

    def add(self, item: LineItem) -> None:
        self._items.append(item)

    @property
    def items(self) -> tuple[LineItem, ...]:
        return tuple(self._items)

    @property
    def unit_count(self) -> int:
        """Total number of physical units, not distinct SKUs."""
        return sum(item.quantity for item in self._items)

    def total_cents(self) -> int:
        return sum(item.subtotal_cents for item in self._items)

    def average_unit_price_cents(self) -> float:
        """Mean price per unit across the cart.

        An empty cart averages to zero rather than raising — callers render
        this straight into a summary line and should not have to special-case
        the empty state.
        """
        if not self._items:
            return 0.0
        return self.total_cents() / self.unit_count

    def apply_discount_cents(self, percent: float) -> int:
        """Total after a percentage discount, rounded to the nearest cent."""
        if not 0 <= percent <= 100:
            raise ValueError(f"percent must be between 0 and 100, got {percent}")
        return round(self.total_cents() * (100 - percent) / 100)

"""Invoice timing.

Everything here is timezone-aware. Mixing naive and aware datetimes raises at
comparison time, so the boundary rule is: aware in, aware out, and `utcnow()`
is never used.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class Invoice:
    """A bill with a due date."""

    reference: str
    amount_cents: int
    due_at: datetime

    def __post_init__(self) -> None:
        if self.due_at.tzinfo is None:
            raise ValueError("due_at must be timezone-aware")


def now_utc() -> datetime:
    """Current time, always timezone-aware."""
    return datetime.now(timezone.utc)


def days_until_due(invoice: Invoice, now: datetime | None = None) -> int:
    """Whole days between now and the invoice due date.

    Negative once the invoice is overdue. `now` defaults to an aware UTC
    timestamp — passing a naive one is a caller error and raises.
    """
    reference = now if now is not None else now_utc()
    if reference.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return (invoice.due_at - reference).days


def is_overdue(invoice: Invoice, now: datetime | None = None) -> bool:
    reference = now if now is not None else now_utc()
    if reference.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return invoice.due_at < reference


def with_grace_period(invoice: Invoice, days: int) -> Invoice:
    """A copy of the invoice with its due date pushed back."""
    if days < 0:
        raise ValueError(f"grace period cannot be negative, got {days}")
    return Invoice(
        reference=invoice.reference,
        amount_cents=invoice.amount_cents,
        due_at=invoice.due_at + timedelta(days=days),
    )

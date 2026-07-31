from datetime import datetime, timedelta, timezone

import pytest

from shopkit.billing import Invoice, days_until_due, is_overdue, now_utc, with_grace_period

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


def invoice(due_at=None, reference="INV-1", amount_cents=5000):
    return Invoice(
        reference=reference,
        amount_cents=amount_cents,
        due_at=due_at if due_at is not None else NOW + timedelta(days=7),
    )


def test_days_until_due():
    assert days_until_due(invoice(NOW + timedelta(days=7)), now=NOW) == 7


def test_days_until_due_is_negative_when_overdue():
    assert days_until_due(invoice(NOW - timedelta(days=3)), now=NOW) == -3


def test_days_until_due_defaults_to_an_aware_now():
    """The default `now` must be timezone-aware or the subtraction raises."""
    assert isinstance(days_until_due(invoice(now_utc() + timedelta(days=5))), int)


def test_now_utc_is_timezone_aware():
    assert now_utc().tzinfo is not None


def test_is_overdue():
    assert is_overdue(invoice(NOW - timedelta(days=1)), now=NOW)
    assert not is_overdue(invoice(NOW + timedelta(days=1)), now=NOW)


def test_invoice_rejects_naive_due_date():
    with pytest.raises(ValueError):
        Invoice(reference="INV-2", amount_cents=100, due_at=datetime(2026, 7, 31, 12, 0))


def test_naive_now_is_rejected():
    with pytest.raises(ValueError):
        days_until_due(invoice(), now=datetime(2026, 7, 31, 12, 0))


def test_with_grace_period_extends_due_date():
    extended = with_grace_period(invoice(NOW + timedelta(days=2)), 5)
    assert days_until_due(extended, now=NOW) == 7


def test_with_grace_period_rejects_negative():
    with pytest.raises(ValueError):
        with_grace_period(invoice(), -1)

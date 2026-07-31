"""shopkit — a small storefront toolkit.

This package exists to be broken. It is the repository Mender watches during
demos: small enough to read in one sitting, real enough that the bugs seeded
into it look like bugs a person would actually write.
"""

from shopkit.billing import Invoice, days_until_due, is_overdue, with_grace_period
from shopkit.cart import Cart, LineItem
from shopkit.pagination import Page, page_count, paginate
from shopkit.users import User, full_name, initials, sort_key

__all__ = [
    "Cart",
    "Invoice",
    "LineItem",
    "Page",
    "User",
    "days_until_due",
    "full_name",
    "initials",
    "is_overdue",
    "page_count",
    "paginate",
    "sort_key",
    "with_grace_period",
]

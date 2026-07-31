"""Pagination helpers.

Pages are 1-indexed throughout, because these numbers end up in URLs and in
front of users. Page 1 is the first page.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class Page:
    """One slice of a larger collection, plus where it sits."""

    items: tuple
    number: int
    per_page: int
    total_items: int

    @property
    def total_pages(self) -> int:
        return page_count(self.total_items, self.per_page)

    @property
    def has_next(self) -> bool:
        return self.number < self.total_pages

    @property
    def has_previous(self) -> bool:
        return self.number > 1


def page_count(total_items: int, per_page: int) -> int:
    """How many pages `total_items` needs. Zero items is still one page."""
    if per_page < 1:
        raise ValueError(f"per_page must be at least 1, got {per_page}")
    if total_items <= 0:
        return 1
    return math.ceil(total_items / per_page)


def paginate(items: Sequence[T], number: int = 1, per_page: int = 10) -> Page:
    """Return the `number`-th page of `items`, 1-indexed.

    Page 1 starts at index 0. Getting this wrong silently hides the first
    page of every list in the product, which is why it has its own test.
    """
    if number < 1:
        raise ValueError(f"page number must be at least 1, got {number}")
    if per_page < 1:
        raise ValueError(f"per_page must be at least 1, got {per_page}")

    start = (number - 1) * per_page
    return Page(
        items=tuple(items[start : start + per_page]),
        number=number,
        per_page=per_page,
        total_items=len(items),
    )

import pytest

from shopkit.pagination import page_count, paginate

LETTERS = list("abcdefghij")


def test_first_page_starts_at_the_beginning():
    """Page 1 is the first page. Off-by-one here hides real data."""
    assert paginate(LETTERS, number=1, per_page=3).items == ("a", "b", "c")


def test_second_page():
    assert paginate(LETTERS, number=2, per_page=3).items == ("d", "e", "f")


def test_last_page_may_be_short():
    assert paginate(LETTERS, number=4, per_page=3).items == ("j",)


def test_page_beyond_the_end_is_empty():
    assert paginate(LETTERS, number=99, per_page=3).items == ()


def test_page_records_its_position():
    page = paginate(LETTERS, number=2, per_page=3)
    assert page.number == 2
    assert page.total_items == 10
    assert page.total_pages == 4


def test_has_next_and_previous():
    page = paginate(LETTERS, number=2, per_page=3)
    assert page.has_next
    assert page.has_previous


def test_first_page_has_no_previous():
    assert not paginate(LETTERS, number=1, per_page=3).has_previous


def test_last_page_has_no_next():
    assert not paginate(LETTERS, number=4, per_page=3).has_next


def test_page_count_rounds_up():
    assert page_count(10, 3) == 4


def test_page_count_of_empty_collection_is_one():
    assert page_count(0, 10) == 1


def test_rejects_page_zero():
    with pytest.raises(ValueError):
        paginate(LETTERS, number=0, per_page=3)


def test_rejects_zero_per_page():
    with pytest.raises(ValueError):
        paginate(LETTERS, number=1, per_page=0)

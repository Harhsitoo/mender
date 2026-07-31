import pytest

from shopkit.users import User, full_name, initials, sort_key


def test_full_name_with_both_parts():
    assert full_name(User(first_name="Ada", last_name="Lovelace")) == "Ada Lovelace"


def test_full_name_without_last_name():
    """Single-name users are real. Rendering them must not crash or pad."""
    assert full_name(User(first_name="Prince")) == "Prince"


def test_full_name_has_no_trailing_space_without_last_name():
    assert not full_name(User(first_name="Cher")).endswith(" ")


def test_initials_with_both_parts():
    assert initials(User(first_name="Ada", last_name="Lovelace")) == "AL"


def test_initials_without_last_name():
    assert initials(User(first_name="Prince")) == "P"


def test_user_requires_first_name():
    with pytest.raises(ValueError):
        User(first_name="")


def test_user_rejects_whitespace_first_name():
    with pytest.raises(ValueError):
        User(first_name="   ")


def test_sort_key_orders_by_surname():
    users = [
        User(first_name="Ada", last_name="Lovelace"),
        User(first_name="Grace", last_name="Hopper"),
    ]
    assert [u.first_name for u in sorted(users, key=sort_key)] == ["Grace", "Ada"]


def test_users_without_surname_sort_last():
    users = [
        User(first_name="Prince"),
        User(first_name="Grace", last_name="Hopper"),
    ]
    assert [u.first_name for u in sorted(users, key=sort_key)] == ["Grace", "Prince"]

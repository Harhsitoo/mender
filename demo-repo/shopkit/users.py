"""User records and how we render them in the UI."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class User:
    """A customer.

    Only `first_name` is required. Plenty of real people have one legal name,
    and plenty of sign-up forms let the surname field go empty, so `last_name`
    is genuinely optional and every renderer has to cope with that.
    """

    first_name: str
    last_name: str | None = None
    email: str | None = None

    def __post_init__(self) -> None:
        if not self.first_name or not self.first_name.strip():
            raise ValueError("first_name is required")


def full_name(user: User) -> str:
    """Display name for a user.

    Users without a last name render as just their first name — with no
    trailing space, which is the whole reason this is not an f-string.
    """
    if user.last_name is None:
        return user.first_name
    return f"{user.first_name} {user.last_name}"


def initials(user: User) -> str:
    """Uppercase initials, one character per available name part."""
    parts = [user.first_name]
    if user.last_name is not None:
        parts.append(user.last_name)
    return "".join(part[0].upper() for part in parts if part)


def sort_key(user: User) -> tuple[str, str]:
    """Sort by surname then forename, with missing surnames sorting last."""
    surname = user.last_name.lower() if user.last_name else "￿"
    return (surname, user.first_name.lower())

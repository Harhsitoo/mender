import pytest

from shopkit.cart import Cart, LineItem


def test_line_item_subtotal():
    item = LineItem(sku="MUG", quantity=3, unit_price_cents=450)
    assert item.subtotal_cents == 1350


def test_line_item_rejects_zero_quantity():
    with pytest.raises(ValueError):
        LineItem(sku="MUG", quantity=0, unit_price_cents=450)


def test_line_item_rejects_negative_price():
    with pytest.raises(ValueError):
        LineItem(sku="MUG", quantity=1, unit_price_cents=-1)


def test_cart_total():
    cart = Cart([
        LineItem(sku="MUG", quantity=2, unit_price_cents=450),
        LineItem(sku="TEE", quantity=1, unit_price_cents=1800),
    ])
    assert cart.total_cents() == 2700


def test_cart_unit_count_counts_units_not_skus():
    cart = Cart([
        LineItem(sku="MUG", quantity=2, unit_price_cents=450),
        LineItem(sku="TEE", quantity=3, unit_price_cents=1800),
    ])
    assert cart.unit_count == 5


def test_cart_average_unit_price():
    cart = Cart([
        LineItem(sku="MUG", quantity=2, unit_price_cents=450),
        LineItem(sku="TEE", quantity=2, unit_price_cents=1550),
    ])
    assert cart.average_unit_price_cents() == 1000


def test_empty_cart_averages_to_zero():
    """An empty cart renders a summary line like any other cart."""
    assert Cart().average_unit_price_cents() == 0.0


def test_empty_cart_total_is_zero():
    assert Cart().total_cents() == 0


def test_apply_discount():
    cart = Cart([LineItem(sku="TEE", quantity=1, unit_price_cents=2000)])
    assert cart.apply_discount_cents(25) == 1500


def test_apply_discount_rejects_out_of_range():
    cart = Cart([LineItem(sku="TEE", quantity=1, unit_price_cents=2000)])
    with pytest.raises(ValueError):
        cart.apply_discount_cents(140)


def test_add_appends_item():
    cart = Cart()
    cart.add(LineItem(sku="MUG", quantity=1, unit_price_cents=450))
    assert len(cart.items) == 1

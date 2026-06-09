import pytest

from inventory_management.modules.vendor.payment_dialog import _VendorMoneyDialog


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12", 12.0),
        ("12.5", 12.5),
        ("0.50", 0.5),
        (".5", 0.5),
        ("+12", 12.0),
        ("-12.5", -12.5),
        (" 12.50 ", 12.5),
    ],
)
def test_to_float_safe_accepts_plain_decimal_amounts(text, expected):
    assert _VendorMoneyDialog._to_float_safe(None, text) == pytest.approx(expected)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        None,
        "1abc2",
        "Rs 12",
        "$12.00",
        "1,234.56",
        "12 34",
        "1.2.3",
        "--12",
        "12-",
        "+",
        "-",
        ".",
        "+.",
        "1e3",
    ],
)
def test_to_float_safe_rejects_non_plain_decimal_amounts(text):
    assert _VendorMoneyDialog._to_float_safe(None, text) is None

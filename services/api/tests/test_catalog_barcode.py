import pytest

from elblasy_api.catalog_barcode import (
    ean13_check_digit,
    internal_barcode,
    is_scale_barcode,
    is_valid_ean13,
    scale_barcode,
)


def test_known_ean13_check_digits():
    assert is_valid_ean13("4006381333931")  # real-world EAN-13
    assert ean13_check_digit("400638133393") == 1
    assert not is_valid_ean13("4006381333932")
    assert not is_valid_ean13("12345")


def test_scale_barcode_matches_odoo_weight_rule_shape():
    b = scale_barcode(123)
    assert len(b) == 13 and b.startswith("21") and b[2:7] == "00123" and b[7:12] == "00000"
    assert is_valid_ean13(b) and is_scale_barcode(b)
    assert not is_scale_barcode("4006381333931")


def test_odoo_scan_flow_resolves_to_same_product():
    """A scale prints weight in digits 8-12; Odoo zeroes them and recomputes the check digit."""
    stored = scale_barcode(4242)
    printed_base = stored[:7] + "01250"  # 1.250 kg
    printed = printed_base + str(ean13_check_digit(printed_base))
    assert is_valid_ean13(printed)
    zeroed = printed[:7] + "00000"
    assert zeroed + str(ean13_check_digit(zeroed)) == stored


def test_internal_barcodes_avoid_odoo_special_rules():
    b = internal_barcode(1)
    assert b.startswith("20") and is_valid_ean13(b)
    assert not b.startswith(("21", "22", "23"))
    assert internal_barcode(1) != internal_barcode(2)


def test_ranges_enforced():
    with pytest.raises(ValueError):
        scale_barcode(0)
    with pytest.raises(ValueError):
        scale_barcode(100_000)
    with pytest.raises(ValueError):
        internal_barcode(0)

"""EAN-13 helpers and platform-generated barcodes.

Odoo's default nomenclature (verified on CE 18/19) has weight rule `21.....{NNDDD}`: a scale prints
`21` + 5-digit product code + 5-digit weight (grams) + check digit; the POS zeroes the weight digits
and looks up the product by `21` + code + `00000` + recomputed check digit. So a weighed product's
barcode in Odoo must be exactly that zero-weight form.
In-store (non-weighed) codes use the GS1 "in-store" prefix `20`, which Odoo's price/weight/discount
rules (21/22/23) never match."""

SCALE_PREFIX = "21"
INTERNAL_PREFIX = "20"
SCALE_MAX = 99_999
INTERNAL_MAX = 9_999_999_999


def ean13_check_digit(first12: str) -> int:
    if len(first12) != 12 or not first12.isdigit():
        raise ValueError("need 12 digits")
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(first12))
    return (10 - total % 10) % 10


def is_valid_ean13(code: str) -> bool:
    return len(code) == 13 and code.isdigit() and ean13_check_digit(code[:12]) == int(code[12])


def scale_barcode(code: int) -> str:
    if not 1 <= code <= SCALE_MAX:
        raise ValueError("scale code out of range")
    base = f"{SCALE_PREFIX}{code:05d}00000"
    return base + str(ean13_check_digit(base))


def internal_barcode(n: int) -> str:
    if not 1 <= n <= INTERNAL_MAX:
        raise ValueError("internal code out of range")
    base = f"{INTERNAL_PREFIX}{n:010d}"
    return base + str(ean13_check_digit(base))


def is_scale_barcode(code: str) -> bool:
    return is_valid_ean13(code) and code.startswith(SCALE_PREFIX) and code[7:12] == "00000"

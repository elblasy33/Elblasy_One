"""Versioned setup templates. A template declares *what the business needs*; the planner
compares that with what the Odoo actually has. Nothing here assumes taxes, accounts,
payment providers or valuation policy: those are reported for review, never imposed."""

from dataclasses import dataclass, field

from elblasy_api.setup.profile import BusinessProfile

TEMPLATE_SCHEMA_VERSION = 1

BASE_MODULES = ("account", "sale_management", "purchase", "stock", "stock_account", "point_of_sale")

# feature -> modules it needs (installed only through an approved plan)
FEATURE_MODULES: dict[str, tuple[str, ...]] = {
    "manufacturing": ("mrp",),
    "expiry": ("product_expiry",),
    "weighing": ("barcodes",),
}


@dataclass(frozen=True)
class Template:
    id: str
    version: str
    vertical: str
    name: dict[str, str]
    summary: dict[str, str]
    default_features: frozenset[str] = frozenset()
    required_modules: tuple[str, ...] = BASE_MODULES
    required_capabilities: tuple[str, ...] = ("accounting", "sales", "inventory", "pos", "purchase")
    optional_capabilities: tuple[str, ...] = ("manufacturing", "expiry")
    # Checks the post-configuration verifier must pass before setup is marked complete.
    verification_checks: tuple[str, ...] = (
        "modules_installed", "pos_config_exists", "payment_methods_attached",
        "warehouse_exists", "features_enabled",
    )  # fmt: skip
    notes: dict[str, str] = field(default_factory=dict)


TEMPLATES: dict[str, Template] = {
    t.id: t
    for t in (
        Template(
            "grocery_starter",
            "1.0.0",
            "grocery",
            {"ar": "بقالة / ميني ماركت", "en": "Grocery / mini-market"},
            {
                "ar": "بيع بالقطعة والوزن، موردون، مخزون، ومنتجات مصنّعة اختيارية",
                "en": "Piece and weight sales, suppliers, stock, optional own-made products",
            },
        ),
        Template(
            "bookstore_starter",
            "1.0.0",
            "bookstore",
            {"ar": "مكتبة", "en": "Bookstore / stationery"},
            {
                "ar": "كتب وأدوات مكتبية بباركود ISBN/EAN ومرتجعات للموردين",
                "en": "Books and stationery with ISBN/EAN barcodes and supplier returns",
            },
        ),
        Template(
            "shoes_starter",
            "1.0.0",
            "shoes",
            {"ar": "محل أحذية", "en": "Shoe store"},
            {"ar": "مقاسات وألوان لكل موديل", "en": "Sizes and colours per model"},
            default_features=frozenset({"variants"}),
        ),
        Template(
            "clothing_starter",
            "1.0.0",
            "clothing",
            {"ar": "محل ملابس", "en": "Clothing store"},
            {"ar": "مقاسات وألوان وموسمية", "en": "Sizes, colours, seasonal stock"},
            default_features=frozenset({"variants"}),
        ),
        Template(
            "electronics_starter",
            "1.0.0",
            "electronics",
            {"ar": "إلكترونيات وموبايلات", "en": "Electronics / mobile phones"},
            {
                "ar": "رقم تسلسلي لكل قطعة (سيريال/IMEI)، ألوان وسعات، وضمان",
                "en": "A serial/IMEI per item, colours and capacities",
            },
            default_features=frozenset({"serials", "lots", "variants"}),
        ),
        Template(
            "general_trading_starter",
            "1.0.0",
            "general",
            {"ar": "تجارة عامة", "en": "General trading"},
            {"ar": "نشاط تجاري عام", "en": "General retail/trading"},
        ),
    )
}


def template_for(profile: BusinessProfile) -> Template:
    return next(t for t in TEMPLATES.values() if t.vertical == profile.vertical)


def resolve_features(t: Template, p: BusinessProfile) -> set[str]:
    f = set(t.default_features)
    if p.tracks_serials is True:
        f |= {"serials", "lots"}
    if p.tracks_serials is False:
        f -= {"serials"}
        if not p.tracks_expiry:
            f.discard("lots")
    if p.needs_variants is True:
        f.add("variants")
    if p.needs_variants is False:
        f.discard("variants")
    if p.makes_own_products:
        f.add("manufacturing")
    if p.uses_weighing_scale:
        f.add("weighing")
    if p.tracks_expiry:
        f |= {"expiry", "lots"}
    if p.multiple_uom:
        f.add("uom")
    if p.sells_on_credit:
        f.add("credit_sales")
    if p.buys_on_credit:
        f.add("supplier_credit")
    return f


def unsupported_combinations(p: BusinessProfile, features: set[str]) -> list[dict[str, str]]:
    """Reasons a profile cannot be set up safely by this version. Reported, never worked around."""
    out = []
    if p.branches > 1:
        out.append({"code": "multi_branch", "reason":
                    "Multi-branch operation is not supported yet; set up a single branch first."})  # fmt: skip
    if "weighing" in features and "variants" in features:
        out.append({"code": "weighing_with_variants", "reason":
                    "Weighed items with size/colour variants are not supported."})  # fmt: skip
    return out

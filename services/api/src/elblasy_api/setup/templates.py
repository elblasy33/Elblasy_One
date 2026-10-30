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


# What each capability means for the shop, in its own words (shown live while answering).
FEATURE_EFFECTS: dict[str, dict[str, str]] = {
    "weighing": {"ar": "بيع بالوزن: الكاشير يكتب الوزن أو يقراه من ملصق الميزان", "en": "Sell by weight: typed at the till or read from the scale label"},
    "scale_labels": {"ar": "قراءة ملصقات الميزان بالباركود والوزن جواه", "en": "Read scale labels with the weight inside the barcode"},
    "variants": {"ar": "مقاسات وألوان: كل مقاس له رصيد وباركود", "en": "Sizes and colours: stock and barcode per size"},
    "expiry": {"ar": "تواريخ الصلاحية: البيع من الأقرب انتهاءً ومنع بيع المنتهي", "en": "Expiry dates: sell the earliest first, never the expired"},
    "lots": {"ar": "تتبع الدفعات في المخزن", "en": "Batch (lot) tracking in stock"},
    "serials": {"ar": "رقم مسلسل لكل قطعة عند الاستلام والبيع والمرتجع", "en": "A serial number per item at receiving, sale and return"},
    "uom": {"ar": "وحدات متعددة: كرتونة وعلبة وقطعة", "en": "Several units: carton, box, piece"},
    "manufacturing": {"ar": "وصفات وتصنيع: المكونات تتخصم والمنتج يتضاف", "en": "Recipes and production: ingredients out, product in"},
    "credit_sales": {"ar": "البيع بالآجل وكشف حساب لكل زبون", "en": "Sales on credit and a statement per customer"},
    "credit_limits": {"ar": "حد أقصى لمديونية كل زبون", "en": "A maximum debt per customer"},
    "supplier_credit": {"ar": "فواتير موردين بالآجل ومتابعة المستحق", "en": "Supplier bills on credit and what you owe"},
    "pricelists": {"ar": "أسعار قطاعي وجملة لنفس الصنف", "en": "Retail and wholesale prices for the same item"},
    "services": {"ar": "بيع خدمات من غير مخزون", "en": "Sell services without stock"},
    "sales_orders": {"ar": "أوامر بيع للتجار بأسعارها وفواتيرها", "en": "Sales orders for traders, with their prices and invoices"},
    "fast_till": {"ar": "كاشير سريع للزحمة: أزرار سريعة ومسح ودفع من الكيبورد", "en": "A fast till for busy times: quick keys, scan-and-pay from the keyboard"},
    "reorder": {"ar": "تنبيه لما الصنف يقرب يخلص واقتراح كمية الطلب", "en": "Low-stock warnings and suggested reorder quantities"},
    "internal_barcodes": {"ar": "باركود داخلي للمنتجات اللي ملهاش باركود، واختيار بالصور", "en": "Internal barcodes for unlabelled products, and picking by picture"},
    "tax_included_prices": {"ar": "السعر المكتوب على الرف هو اللي الزبون يدفعه (شامل الضريبة)", "en": "The shelf price is what the customer pays (tax included)"},
    "no_sales_tax": {"ar": "منتجات من غير ضريبة مبيعات", "en": "Products without sales tax"},
}  # fmt: skip

# Answer-built profiles (no business type) all use this one template: what gets set up comes from the
# answers alone, through `resolve_features`.
PROFILE_TEMPLATE = Template(
    "business_profile",
    "2.0.0",
    "custom",
    {"ar": "نشاطك كما وصفته", "en": "Your business, as you described it"},
    {
        "ar": "إعداد مبني على إجاباتك عن طريقة شغلك",
        "en": "A setup built from your answers about how you work",
    },
)


def template_for(profile: BusinessProfile) -> Template:
    if profile.vertical is None:
        return PROFILE_TEMPLATE
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
    if p.buys_on_credit and p.buys_from_suppliers:
        f.add("supplier_credit")
    if p.vertical is None:  # capabilities only the answer-built questionnaire asks about
        if p.scale_labels and p.uses_weighing_scale:
            f.add("scale_labels")
        if p.wholesale_prices:
            f.add("pricelists")
        if "services" in p.sells:
            f.add("services")
        if set(p.channels) & {"orders", "delivery"}:
            f.add("sales_orders")
        if p.daily_volume == "high" or p.registers > 1:
            f.add("fast_till")
        if p.sells_on_credit and p.credit_limits:
            f.add("credit_limits")
        if p.track_stock and p.reorder_alerts:
            f.add("reorder")
        if p.barcodes != "all":
            f.add("internal_barcodes")
        if p.vat == "included":
            f.add("tax_included_prices")
        if p.vat == "not_registered":
            f.add("no_sales_tax")
    return f


def limitations(p: BusinessProfile) -> list[dict[str, str]]:
    """What the answers ask for that this version does not do yet. Reported honestly; never blocking:
    the rest of the setup still applies and the shop can start working."""
    out = []
    if p.dine_in:
        out.append({"code": "dine_in", "ar": "الترابيزات والمطبخ مش مدعومين لسه؛ البيع هيبقى على الكاشير (تيك أواي).",
                    "en": "Tables and kitchen tickets are not supported yet; sell at the counter (takeaway)."})  # fmt: skip
    if p.registers > 1:
        out.append({"code": "registers", "ar": f"هنجهّز نقطة بيع واحدة الأول؛ تشغيل {p.registers} كاشير في نفس الوقت على نقاط منفصلة لسه مش مدعوم.",
                    "en": f"One point of sale is set up first; {p.registers} separate tills at once are not supported yet."})  # fmt: skip
    if "delivery" in p.channels:
        out.append({"code": "delivery", "ar": "التوصيل بيتسجّل كأمر بيع وتسليم؛ تتبع المندوب والشحن مش مدعوم لسه.",
                    "en": "Delivery is recorded as a sales order and delivery; courier tracking is not supported yet."})  # fmt: skip
    if "services" in p.sells:
        out.append({"code": "services", "ar": "الخدمات بتتباع كأصناف من غير مخزون؛ المواعيد والحجوزات مش مدعومة لسه.",
                    "en": "Services are sold as items without stock; appointments and bookings are not supported yet."})  # fmt: skip
    return out


def unsupported_combinations(p: BusinessProfile, features: set[str]) -> list[dict[str, str]]:
    """Reasons a profile cannot be set up safely by this version. Reported, never worked around."""
    out = []
    if p.branches > 1:
        out.append({"code": "multi_branch", "reason":
                    "Multi-branch operation is not supported yet; set up a single branch first."})  # fmt: skip
    if p.vertical is not None and "weighing" in features and "variants" in features:
        out.append({"code": "weighing_with_variants", "reason":
                    "Weighed items with size/colour variants are not supported."})  # fmt: skip
    return out

"""Business profile + conditional questionnaire (bilingual, data-driven).

The business is described by *how it works*, never by picking a business type from a list: what it
sells, how customers buy and pay, what its goods are like, how it buys, and who works there. Every
answer switches on concrete capabilities, so any small business (a bakery that also repairs phones, a
pharmacy, a wholesaler with a counter) composes its own setup. Questions are grouped in stages, shown
only when relevant (`when`), and every answer can be changed later: a changed profile produces a new,
additive plan.

The earlier questionnaire started with a business type (`vertical`). Answers that still carry it are
read with the legacy questions so old plans and integrations keep working.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

Vertical = Literal["grocery", "bookstore", "shoes", "clothing", "electronics", "general"]
PayMethod = Literal["cash", "card", "wallet", "bank_transfer"]
Sells = Literal["goods", "services", "made"]
Channel = Literal["counter", "orders", "delivery"]
Volume = Literal["low", "medium", "high"]
Barcodes = Literal["all", "some", "none"]
CustomersKind = Literal["walk_in", "some_known", "all_known"]
Vat = Literal["not_registered", "included", "excluded"]
Staff = Literal["alone", "small", "team"]
Device = Literal["scanner", "receipt_printer", "cash_drawer"]


class BusinessProfile(BaseModel):
    # legacy: the business type the old questionnaire asked first (None for answer-built profiles)
    vertical: Vertical | None = None
    # --- how you sell
    sells: list[Sells] = Field(default=["goods"])
    channels: list[Channel] = Field(default=["counter"])
    daily_volume: Volume = "low"
    registers: int = Field(default=1, ge=1, le=10)
    dine_in: bool = False
    branches: int = Field(default=1, ge=1, le=100)
    # --- what your goods are like
    makes_own_products: bool = False
    uses_weighing_scale: bool = False
    scale_labels: bool = False
    needs_variants: bool | None = None  # None -> legacy template default
    tracks_expiry: bool = False
    tracks_serials: bool | None = None  # None -> legacy template default
    multiple_uom: bool = False
    barcodes: Barcodes = "all"
    track_stock: bool = True
    # --- customers and money
    payment_methods: list[PayMethod] = Field(default=["cash"])
    customers: CustomersKind = "walk_in"
    sells_on_credit: bool = False
    credit_limits: bool = False
    wholesale_prices: bool = False
    vat: Vat | None = None
    # --- buying and stock
    buys_from_suppliers: bool = True
    buys_on_credit: bool = True
    reorder_alerts: bool = True
    # --- people and devices
    staff: Staff = "alone"
    devices: list[Device] = Field(default_factory=list)


@dataclass(frozen=True)
class Option:
    value: str
    text: dict[str, str]
    hint: dict[str, str] | None = None


@dataclass(frozen=True)
class Question:
    id: str
    kind: str  # choice | bool | number | multi
    text: dict[str, str]
    options: tuple[
        Any, ...
    ] = ()  # Option for answer-built questions; plain strings for legacy ones
    when: dict[str, Any] = field(default_factory=dict)
    default: Any = None
    stage: str = "business"
    hint: dict[str, str] | None = None
    minimum: int | None = None
    maximum: int | None = None


def _t(ar: str, en: str) -> dict[str, str]:
    return {"ar": ar, "en": en}


def _o(
    value: str, ar: str, en: str, hint_ar: str | None = None, hint_en: str | None = None
) -> Option:
    return Option(value, _t(ar, en), _t(hint_ar, hint_en or hint_ar) if hint_ar else None)


STAGES: tuple[dict[str, Any], ...] = (
    {"id": "selling", "title": _t("طريقة البيع", "How you sell"),
     "intro": _t("نبدأ بطريقة شغلك اليومية، مش باسم النشاط.", "We start from how you work every day, not from a business type.")},
    {"id": "goods", "title": _t("البضاعة", "Your goods"),
     "intro": _t("طبيعة اللي بتبيعه بتحدد شكل الكاشير والمخزن.", "What your goods are like shapes the till and the stock.")},
    {"id": "money", "title": _t("الزبون والفلوس", "Customers and money"),
     "intro": _t("إزاي الزبون بيدفع، وهل في حسابات وأسعار مختلفة.", "How customers pay, and whether there are accounts and price levels.")},
    {"id": "buying", "title": _t("الشراء والمخزن", "Buying and stock"),
     "intro": _t("منين بتجيب بضاعتك وإزاي تتابعها.", "Where your goods come from and how you follow them.")},
    {"id": "people", "title": _t("الفريق والأجهزة", "People and devices"),
     "intro": _t("مين بيشتغل معاك وإيه الأجهزة الموجودة.", "Who works with you and which devices you have.")},
)  # fmt: skip

GOODS = {"sells": {"has_any": ["goods", "made"]}}

QUESTIONS: tuple[Question, ...] = (
    # ---------------- how you sell ----------------
    Question("sells", "multi", _t("إيه اللي بتبيعه؟ (اختار كل اللي ينطبق)", "What do you sell? (pick all that apply)"), (
        _o("goods", "بضاعة جاهزة بتشتريها وتبيعها", "Ready goods you buy and resell", "زي البقالة، الملابس، الأدوات، الموبايلات", "groceries, clothes, tools, phones"),
        _o("made", "حاجات بتعملها أو بتجهزها بنفسك", "Things you make or prepare yourself", "زي المخبوزات، الأكل، العطور، الهدايا المجمّعة", "bakery, food, perfume blends, gift boxes"),
        _o("services", "خدمات أو شغل يد", "Services or work", "زي الصيانة، الحلاقة، التوصيل، التركيب", "repairs, haircuts, delivery, installation"),
    ), stage="selling", default=["goods"]),
    Question("channels", "multi", _t("إزاي الزبون بيشتري منك؟", "How do customers buy from you?"), (
        _o("counter", "بييجي المحل ويدفع على الكاشير", "Comes to the shop and pays at the till"),
        _o("orders", "طلبات لتجار أو شركات بأسعار وفواتير", "Orders for traders or companies, with prices and invoices", "بيع جملة أو توريد", "wholesale or supply"),
        _o("delivery", "توصيل للبيوت", "Home delivery"),
    ), stage="selling", default=["counter"]),
    Question("daily_volume", "choice", _t("في يوم الذروة، تقريبًا كام عملية بيع؟", "On a busy day, roughly how many sales?"), (
        _o("low", "أقل من 30", "Under 30"),
        _o("medium", "من 30 لـ 150", "30 to 150"),
        _o("high", "أكتر من 150، وساعات بيبقى في طابور", "Over 150, sometimes with a queue"),
    ), when={"channels": {"has": "counter"}}, stage="selling", default="low"),
    Question("registers", "number", _t("كام كاشير بيشتغلوا في نفس الوقت؟", "How many tills work at the same time?"),
             when={"channels": {"has": "counter"}}, stage="selling", default=1, minimum=1, maximum=10),
    Question("dine_in", "bool", _t("الزبون بيقعد ياكل أو يشرب عندك (ترابيزات)؟", "Do customers sit and eat or drink at tables?"),
             when={"sells": {"has": "made"}, "channels": {"has": "counter"}}, stage="selling", default=False),
    Question("branches", "number", _t("كام فرع عندك؟", "How many branches do you have?"), stage="selling", default=1, minimum=1, maximum=100),
    # ---------------- your goods ----------------
    Question("uses_weighing_scale", "bool", _t("بتبيع حاجات بالوزن؟", "Do you sell things by weight?"),
             when=GOODS, stage="goods", default=False, hint=_t("خضار، لحوم، جبن، مكسرات، عطارة", "vegetables, meat, cheese, nuts, spices")),
    Question("scale_labels", "bool", _t("عندك ميزان بيطبع ملصق عليه باركود؟", "Does your scale print a barcode label?"),
             when={"uses_weighing_scale": True}, stage="goods", default=False,
             hint=_t("لو لأ، الكاشير هيكتب الوزن بإيده", "If not, the cashier types the weight")),
    Question("needs_variants", "bool", _t("نفس المنتج له مقاسات أو ألوان أو أحجام؟", "Does one product come in sizes, colours or capacities?"),
             when=GOODS, stage="goods", default=False, hint=_t("هدوم، جزم، موبايلات بسعات مختلفة", "clothes, shoes, phones with different storage")),
    Question("tracks_expiry", "bool", _t("بضاعتك ليها تاريخ صلاحية لازم تتابعه؟", "Do your goods have expiry dates you must follow?"),
             when=GOODS, stage="goods", default=False, hint=_t("أدوية، ألبان، معلبات، مستحضرات", "medicines, dairy, canned food, cosmetics")),
    Question("tracks_serials", "bool", _t("كل قطعة ليها رقم مسلسل لازم يتسجل؟", "Does each item have a serial number you must record?"),
             when=GOODS, stage="goods", default=False, hint=_t("موبايلات (IMEI)، أجهزة عليها ضمان", "phones (IMEI), appliances with warranty")),
    Question("multiple_uom", "bool", _t("بتشتري بوحدة وتبيع بوحدة تانية؟", "Do you buy in one unit and sell in another?"),
             when=GOODS, stage="goods", default=False, hint=_t("تشتري كرتونة وتبيع بالعلبة أو بالقطعة", "buy by the carton, sell by the box or piece")),
    Question("barcodes", "choice", _t("منتجاتك عليها باركود؟", "Do your products carry barcodes?"), (
        _o("all", "أغلبها عليه باركود", "Most of them"),
        _o("some", "بعضها", "Some"),
        _o("none", "لأ، تقريبًا مفيش", "Hardly any", "هنطبع لك باركود داخلي، والكاشير يختار من صور المنتجات", "we print internal codes; the till shows product pictures"),
    ), when=GOODS, stage="goods", default="all"),
    Question("makes_own_products", "bool", _t("الحاجات اللي بتعملها ليها وصفة/مكونات بتخصمها من المخزن؟", "Do the things you make use ingredients you take out of stock?"),
             when={"sells": {"has": "made"}}, stage="goods", default=True, hint=_t("زي الدقيق والسكر في المخبوزات", "like flour and sugar for baked goods")),
    # ---------------- customers and money ----------------
    Question("payment_methods", "multi", _t("الزبون بيدفع إزاي؟", "How do customers pay?"), (
        _o("cash", "كاش", "Cash"), _o("card", "فيزا / بطاقة", "Card"),
        _o("wallet", "محفظة إلكترونية", "Mobile wallet", "فودافون كاش، إنستاباي", "Vodafone Cash, InstaPay"),
        _o("bank_transfer", "تحويل بنكي", "Bank transfer"),
    ), stage="money", default=["cash"]),
    Question("customers", "choice", _t("تعرف زباينك؟", "Do you know your customers?"), (
        _o("walk_in", "أغلبهم زباين عابرين", "Mostly walk-in customers"),
        _o("some_known", "في زباين دايمين بحسابات", "Some regulars with accounts"),
        _o("all_known", "كل زبون ليه حساب عندي", "Every customer has an account"),
    ), stage="money", default="walk_in"),
    Question("sells_on_credit", "bool", _t("بتبيع بالآجل (على الحساب)؟", "Do you sell on credit (on account)?"),
             stage="money", default=False),
    Question("credit_limits", "bool", _t("عايز حد أقصى للمديونية لكل زبون؟", "Do you want a maximum debt per customer?"),
             when={"sells_on_credit": True}, stage="money", default=True),
    Question("wholesale_prices", "bool", _t("في أسعار مختلفة لنفس الصنف (قطاعي وجملة)؟", "Different prices for the same item (retail and wholesale)?"),
             stage="money", default=False),
    Question("vat", "choice", _t("وضعك مع ضريبة القيمة المضافة؟", "Your VAT situation?"), (
        _o("not_registered", "مش مسجّل، أسعاري من غير ضريبة", "Not registered; my prices carry no tax"),
        _o("included", "مسجّل، والسعر المكتوب على الرف شامل الضريبة", "Registered; shelf prices include the tax"),
        _o("excluded", "مسجّل، والضريبة بتتضاف على السعر", "Registered; tax is added on top of the price"),
    ), stage="money", default=None, hint=_t("لو مش متأكد، اسأل محاسبك", "If unsure, ask your accountant")),
    # ---------------- buying and stock ----------------
    Question("track_stock", "bool", _t("عايز تعرف رصيد كل صنف وتتنبه لما يقرب يخلص؟", "Do you want to know each item's stock and be warned when it runs low?"),
             when=GOODS, stage="buying", default=True),
    Question("buys_from_suppliers", "bool", _t("بتشتري بضاعتك من موردين؟", "Do you buy your goods from suppliers?"),
             when=GOODS, stage="buying", default=True),
    Question("buys_on_credit", "bool", _t("بتشتري من الموردين بالآجل؟", "Do you buy from suppliers on credit?"),
             when={"buys_from_suppliers": True, **GOODS}, stage="buying", default=True),
    Question("reorder_alerts", "bool", _t("عايز النظام يقترح عليك تطلب إيه وإمتى؟", "Should the system suggest what to reorder and when?"),
             when={"track_stock": True, **GOODS}, stage="buying", default=True),
    # ---------------- people and devices ----------------
    Question("staff", "choice", _t("مين بيشتغل في المحل؟", "Who works in the shop?"), (
        _o("alone", "أنا لوحدي", "Just me"),
        _o("small", "أنا ومعايا من 1 لـ 4", "Me and 1 to 4 people"),
        _o("team", "فريق أكبر بمسؤوليات مختلفة", "A larger team with different roles"),
    ), stage="people", default="alone"),
    Question("devices", "multi", _t("إيه الأجهزة اللي عندك؟", "Which devices do you have?"), (
        _o("scanner", "قارئ باركود", "Barcode scanner"),
        _o("receipt_printer", "طابعة إيصالات", "Receipt printer"),
        _o("cash_drawer", "درج نقدية", "Cash drawer"),
    ), stage="people", default=[]),
)  # fmt: skip

# The first questionnaire (business type first). Kept so answers that carry `vertical` still work.
LEGACY_QUESTIONS: tuple[Question, ...] = (
    Question("vertical", "choice", _t("ما نوع نشاطك؟", "What kind of business do you run?"),
             ("grocery", "bookstore", "shoes", "clothing", "electronics", "general")),
    Question("makes_own_products", "bool", _t("هل تصنّع بعض منتجاتك بنفسك؟", "Do you make some of your own products?"),
             when={"vertical": ["grocery", "general"]}, default=False),
    Question("uses_weighing_scale", "bool", _t("هل تبيع بالوزن بميزان بباركود؟", "Do you sell by weight with a barcode scale?"),
             when={"vertical": ["grocery", "general"]}, default=False),
    Question("tracks_expiry", "bool", _t("هل تتابع تواريخ الصلاحية؟", "Do you track expiry dates?"),
             when={"vertical": ["grocery", "general", "bookstore"]}, default=False),
    Question("needs_variants", "bool", _t("هل للمنتج الواحد مقاسات أو ألوان؟", "Do products come in sizes or colours?"),
             when={"vertical": ["general", "bookstore", "grocery"]}, default=False),
    Question("tracks_serials", "bool", _t("هل تتابع كل قطعة برقم تسلسلي (سيريال/IMEI)؟", "Do you track each item by serial number (serial/IMEI)?"),
             when={"vertical": ["electronics", "general"]}, default=False),
    Question("multiple_uom", "bool", _t("هل تبيع نفس المنتج بأكثر من وحدة (قطعة/كرتونة/كيلو)؟", "Do you sell the same product in several units (piece/carton/kg)?"),
             when={"vertical": ["grocery", "general"]}, default=False),
    Question("sells_on_credit", "bool", _t("هل تبيع بالآجل لبعض العملاء؟", "Do you sell on credit to some customers?"), default=False),
    Question("buys_on_credit", "bool", _t("هل تشتري من الموردين بالآجل؟", "Do you buy from suppliers on credit?"), default=True),
    Question("payment_methods", "multi", _t("ما وسائل الدفع التي تقبلها؟", "Which payment methods do you accept?"),
             ("cash", "card", "wallet", "bank_transfer"), default=["cash"]),
    Question("branches", "number", _t("كم عدد فروعك؟", "How many branches do you have?"), default=1),
)  # fmt: skip


def _matches(cond: dict[str, Any], answers: dict[str, Any], defaults: dict[str, Any]) -> bool:
    for qid, want in cond.items():
        got = answers.get(qid, defaults.get(qid))
        if isinstance(want, dict):  # conditions on a multiple-choice answer
            items = got if isinstance(got, list) else []
            if "has" in want and want["has"] not in items:
                return False
            if "has_any" in want and not set(want["has_any"]) & set(items):
                return False
        elif isinstance(want, list):
            if got not in want:
                return False
        elif got != want:
            return False
    return True


def is_legacy(answers: dict[str, Any]) -> bool:
    return "vertical" in answers and answers.get("vertical") is not None


def visible_questions(answers: dict[str, Any]) -> list[Question]:
    qs = LEGACY_QUESTIONS if is_legacy(answers) else QUESTIONS
    defaults = {q.id: q.default for q in qs}
    return [q for q in qs if _matches(q.when, answers, defaults)]


def build_profile(answers: dict[str, Any]) -> BusinessProfile:
    """Only answers to *visible* questions count; hidden ones fall back to safe defaults."""
    visible = visible_questions(answers)
    ids = {q.id for q in visible}
    clean = {k: v for k, v in answers.items() if k in ids}
    if not is_legacy(answers):
        for q in visible:  # an unanswered visible question takes its stated default
            if q.id not in clean and q.default is not None:
                clean[q.id] = q.default
        sells = clean.get("sells") or ["goods"]
        if "made" not in sells:
            clean["makes_own_products"] = False
    return BusinessProfile(**clean)

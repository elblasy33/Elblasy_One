"""Business profile + conditional questionnaire (bilingual, data-driven).

Questions are business-language only. `visible_questions` hides questions whose `when`
condition is not met, so the wizard never asks irrelevant things.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

Vertical = Literal["grocery", "bookstore", "shoes", "clothing", "electronics", "general"]
PayMethod = Literal["cash", "card", "wallet", "bank_transfer"]


class BusinessProfile(BaseModel):
    vertical: Vertical
    makes_own_products: bool = False
    uses_weighing_scale: bool = False
    needs_variants: bool | None = None  # None -> template default (shoes/clothing: yes)
    tracks_expiry: bool = False
    sells_on_credit: bool = False
    buys_on_credit: bool = True
    multiple_uom: bool = False
    tracks_serials: bool | None = None  # None -> template default (electronics: yes)
    payment_methods: list[PayMethod] = Field(default=["cash"])
    branches: int = Field(default=1, ge=1, le=100)


@dataclass(frozen=True)
class Question:
    id: str
    kind: str  # choice | bool | number | multi
    text: dict[str, str]
    options: tuple[str, ...] = ()
    when: dict[str, Any] = field(default_factory=dict)  # {question_id: required_value | [values]}
    default: Any = None


QUESTIONS: tuple[Question, ...] = (
    Question(
        "vertical",
        "choice",
        {"ar": "ما نوع نشاطك؟", "en": "What kind of business do you run?"},
        ("grocery", "bookstore", "shoes", "clothing", "electronics", "general"),
    ),
    Question(
        "makes_own_products",
        "bool",
        {"ar": "هل تصنّع بعض منتجاتك بنفسك؟", "en": "Do you make some of your own products?"},
        when={"vertical": ["grocery", "general"]},
        default=False,
    ),
    Question(
        "uses_weighing_scale",
        "bool",
        {
            "ar": "هل تبيع بالوزن بميزان بباركود؟",
            "en": "Do you sell by weight with a barcode scale?",
        },
        when={"vertical": ["grocery", "general"]},
        default=False,
    ),
    Question(
        "tracks_expiry",
        "bool",
        {"ar": "هل تتابع تواريخ الصلاحية؟", "en": "Do you track expiry dates?"},
        when={"vertical": ["grocery", "general", "bookstore"]},
        default=False,
    ),
    Question(
        "needs_variants",
        "bool",
        {"ar": "هل للمنتج الواحد مقاسات أو ألوان؟", "en": "Do products come in sizes or colours?"},
        when={"vertical": ["general", "bookstore", "grocery"]},
        default=False,
    ),
    Question(
        "tracks_serials",
        "bool",
        {
            "ar": "هل تتابع كل قطعة برقم تسلسلي (سيريال/IMEI)؟",
            "en": "Do you track each item by serial number (serial/IMEI)?",
        },
        when={"vertical": ["electronics", "general"]},
        default=False,
    ),
    Question(
        "multiple_uom",
        "bool",
        {
            "ar": "هل تبيع نفس المنتج بأكثر من وحدة (قطعة/كرتونة/كيلو)؟",
            "en": "Do you sell the same product in several units (piece/carton/kg)?",
        },
        when={"vertical": ["grocery", "general"]},
        default=False,
    ),
    Question(
        "sells_on_credit",
        "bool",
        {"ar": "هل تبيع بالآجل لبعض العملاء؟", "en": "Do you sell on credit to some customers?"},
        default=False,
    ),
    Question(
        "buys_on_credit",
        "bool",
        {"ar": "هل تشتري من الموردين بالآجل؟", "en": "Do you buy from suppliers on credit?"},
        default=True,
    ),
    Question(
        "payment_methods",
        "multi",
        {"ar": "ما وسائل الدفع التي تقبلها؟", "en": "Which payment methods do you accept?"},
        ("cash", "card", "wallet", "bank_transfer"),
        default=["cash"],
    ),
    Question(
        "branches",
        "number",
        {"ar": "كم عدد فروعك؟", "en": "How many branches do you have?"},
        default=1,
    ),
)


def _matches(cond: dict[str, Any], answers: dict[str, Any]) -> bool:
    for qid, want in cond.items():
        got = answers.get(qid)
        if isinstance(want, list):
            if got not in want:
                return False
        elif got != want:
            return False
    return True


def visible_questions(answers: dict[str, Any]) -> list[Question]:
    return [q for q in QUESTIONS if _matches(q.when, answers)]


def build_profile(answers: dict[str, Any]) -> BusinessProfile:
    """Only answers to *visible* questions count; hidden ones fall back to safe defaults."""
    visible = {q.id for q in visible_questions(answers)}
    clean = {k: v for k, v in answers.items() if k in visible}
    return BusinessProfile(**clean)

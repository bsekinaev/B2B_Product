"""Регрессионные проверки повторной генерации и коммерческого блока."""

import json

from app.generator import generate_card
from app.schemas import GenerationStatus, ProductInput


def product() -> ProductInput:
    return ProductInput(
        name="Манометр DM 02",
        manufacturer="Манотомь",
        specs={
            "диапазон": "0–1,6 МПа",
            "класс точности": "1,5",
            "присоединение": "G1/2",
            "диаметр корпуса": "100 мм",
        },
        description="Предназначен для измерения избыточного давления.",
    )


GOOD_DESCRIPTION = (
    "Манометр DM 02 производителя «Манотомь» предназначен для измерения "
    "избыточного давления. Во входных данных указан диапазон 0–1,6 МПа; "
    "его следует сопоставить с требуемой областью измерений при подборе. "
    "Класс точности 1,5 также приводится по исходным характеристикам, "
    "поэтому его можно использовать для предварительного сравнения вариантов. "
    "Присоединение G1/2 необходимо сверить с монтажными требованиями; "
    "само обозначение не подтверждает совместимость с конкретным оборудованием. "
    "Диаметр корпуса 100 мм следует учитывать при проверке габаритов и "
    "доступного пространства в месте установки. Каждый перечисленный параметр "
    "желательно сопоставить с проектной документацией до оформления заявки. "
    "Из приведённых данных нельзя сделать вывод о комплектации, условиях "
    "поставки или возможности применения в особых условиях эксплуатации. "
    "Перед выбором прибора стоит получить актуальный паспорт, уточнить "
    "отсутствующие параметры и проверить соответствие требуемой задаче."
)


def answer(description: str, note: str = "") -> str:
    return json.dumps(
        {
            "seo_title": "Манометр DM 02 — характеристики",
            "seo_description": description,
            "search_queries": [
                "манометр DM 02",
                "манометр Манотомь",
                "манометр характеристики",
            ],
            "commercial_note": note,
        },
        ensure_ascii=False,
    )


class Provider:
    def __init__(self, *answers: str):
        self.answers = list(answers)
        self.calls = 0

    def generate_text(self, **_kwargs: object) -> str:
        self.calls += 1
        return self.answers.pop(0)


def test_description_fixture_has_required_length() -> None:
    assert 800 <= len(GOOD_DESCRIPTION) <= 1200


def test_empty_commercial_triggers_second_request() -> None:
    provider = Provider(
        answer(GOOD_DESCRIPTION),
        answer(GOOD_DESCRIPTION, "Для сравнения характеристик при закупке."),
    )
    result = generate_card(product(), provider)  # type: ignore[arg-type]
    assert provider.calls == 2
    assert result.status == GenerationStatus.READY_FOR_REVIEW
    assert result.card.commercial_note


def test_two_empty_commercial_replies_use_safe_fallback() -> None:
    provider = Provider(
        answer(GOOD_DESCRIPTION),
        answer(GOOD_DESCRIPTION),
    )
    result = generate_card(product(), provider)  # type: ignore[arg-type]
    assert provider.calls == 2
    assert result.status == GenerationStatus.READY_FOR_REVIEW
    assert "специалистов по закупке" in (result.card.commercial_note or "")
    assert result.card.specifications == product().specs


def test_short_seo_is_not_disguised_as_complete() -> None:
    provider = Provider(
        answer("Короткое описание."),
        answer("Короткое описание."),
    )
    result = generate_card(product(), provider)  # type: ignore[arg-type]
    assert provider.calls == 2
    assert result.status == GenerationStatus.REQUIRES_REVISION
    assert result.card.commercial_note
    assert any("SEO-описание" in w for w in result.warnings)


def test_insufficient_facts_do_not_trigger_fallback() -> None:
    limited = product().model_copy(update={"specs": {"диапазон": "0–1,6 МПа"}})
    provider = Provider(answer("Короткое описание."))
    result = generate_card(limited, provider)  # type: ignore[arg-type]
    assert provider.calls == 1
    assert result.status == GenerationStatus.REQUIRES_REVISION
    assert not result.card.commercial_note


def test_warranty_from_second_reply_is_rejected() -> None:
    provider = Provider(
        answer(GOOD_DESCRIPTION),
        answer(GOOD_DESCRIPTION, "Гарантия 20 лет."),
    )
    result = generate_card(product(), provider)  # type: ignore[arg-type]
    assert provider.calls == 2
    assert result.card.commercial_note
    assert "гарант" not in result.card.commercial_note.casefold()
    assert result.card.specifications == product().specs


def test_complete_first_reply_is_not_retried() -> None:
    provider = Provider(answer(GOOD_DESCRIPTION, "Для сравнения характеристик при закупке."))
    result = generate_card(product(), provider)  # type: ignore[arg-type]
    assert provider.calls == 1
    assert result.status == GenerationStatus.READY_FOR_REVIEW


def test_checking_fit_is_not_claiming_certification() -> None:
    provider = Provider(
        answer(
            GOOD_DESCRIPTION,
            "Перед заказом проверить соответствие параметров требованиям заявки.",
        )
    )
    result = generate_card(product(), provider)  # type: ignore[arg-type]
    assert provider.calls == 1
    assert result.status == GenerationStatus.READY_FOR_REVIEW
    assert not any("стандарты" in warning for warning in result.warnings)


def test_explicit_unverified_compliance_still_requires_revision() -> None:
    provider = Provider(
        answer(
            GOOD_DESCRIPTION,
            "Прибор соответствует нормативным требованиям.",
        )
    )
    result = generate_card(product(), provider)  # type: ignore[arg-type]
    assert result.status == GenerationStatus.REQUIRES_REVISION
    assert any("стандарты" in warning for warning in result.warnings)


def test_unverified_operational_speed_is_detected() -> None:
    provider = Provider(
        answer(
            GOOD_DESCRIPTION + " Прибор позволяет оперативно отслеживать показатели.",
            "Для сравнения характеристик при закупке.",
        )
    )
    result = generate_card(product(), provider)  # type: ignore[arg-type]
    assert result.status == GenerationStatus.REQUIRES_REVISION
    assert any("преимущества" in warning for warning in result.warnings)


def test_prompt_rejects_generic_card_marketing() -> None:
    from app.llm.prompts import SYSTEM_PROMPT

    assert "коммерческий блок должен говорить о товаре" in SYSTEM_PROMPT
    assert "длину чувствительного элемента" in SYSTEM_PROMPT


def test_live_unverified_high_accuracy() -> None:
    provider = Provider(answer(GOOD_DESCRIPTION, "Высокая точность и надежность измерений."))
    result = generate_card(product(), provider)  # type: ignore[arg-type]
    assert result.status == GenerationStatus.REQUIRES_REVISION
    assert any("преимущества" in warning for warning in result.warnings)


def test_overlong_title_uses_source_name() -> None:
    draft = json.loads(answer(GOOD_DESCRIPTION, "Для сравнения характеристик при закупке."))
    draft["seo_title"] = "Манометр " + "очень длинный заголовок " * 5
    provider = Provider(json.dumps(draft, ensure_ascii=False))

    result = generate_card(product(), provider)  # type: ignore[arg-type]

    assert result.card.seo_title == "Манометр DM 02 — характеристики"
    assert result.status == GenerationStatus.READY_FOR_REVIEW


def test_ip54_cannot_be_attributed_to_sleeve() -> None:
    item = product().model_copy(
        update={
            "specs": {
                **product().specs,
                "степень защиты корпуса": "IP54",
                "материал защитной гильзы": "латунь",
            }
        }
    )
    draft = json.loads(answer(GOOD_DESCRIPTION, "Для сравнения характеристик при закупке."))
    draft["seo_description"] += " Латунная гильза IP54 указана в описании."
    provider = Provider(json.dumps(draft, ensure_ascii=False))

    result = generate_card(item, provider)  # type: ignore[arg-type]

    assert result.status == GenerationStatus.REQUIRES_REVISION
    assert any("приписана гильзе" in w for w in result.warnings)


def test_correct_body_ip54_is_allowed() -> None:
    item = product().model_copy(
        update={
            "specs": {
                **product().specs,
                "степень защиты корпуса": "IP54",
            }
        }
    )
    provider = Provider(
        answer(
            GOOD_DESCRIPTION,
            "Для подбора важно учитывать степень защиты корпуса IP54.",
        )
    )

    result = generate_card(item, provider)  # type: ignore[arg-type]

    assert result.status == GenerationStatus.READY_FOR_REVIEW


def test_refinement_prompt_requests_substantive_paragraphs() -> None:
    from app.llm.prompts import SYSTEM_PROMPT, build_refinement_prompt

    assert "защиты корпуса защитной гильзе" in SYSTEM_PROMPT
    prompt = build_refinement_prompt(product(), 575)
    assert "четыре смысловых абзаца" in prompt
    assert "900–1100" in prompt

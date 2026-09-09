from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Final, Union

if TYPE_CHECKING:
    from typing import TypeAlias   # 3.10+ — 런타임 임포트 금지(아래 주석 참고)

# 3.9 임포트 안전판: 여기서 `str | int` 런타임 유니온이나 `from typing import TypeAlias` 를 쓰면
# Python 3.9 이하에서 이 모듈 임포트가 죽는다 → main.py 가 이 모듈을 최상단에서 import 하므로
# `--doctor` 가 "파이썬 3.10+ 필요" 를 친절히 알리기도 전에 트레이스백으로 죽는 자기모순이 된다.
# Union[...] / builtin 제네릭(dict[str, …])은 3.9 에서도 평가된다. 변수 어노테이션(: TypeAlias)은
# `from __future__ import annotations` 덕에 런타임 평가되지 않아 안전하다.
JsonValue: TypeAlias = Union[str, int, float, bool, None, Sequence["JsonValue"], Mapping[str, "JsonValue"]]
JsonMap: TypeAlias = Mapping[str, JsonValue]
JsonRecord: TypeAlias = dict[str, JsonValue]

MVP_WARNING_CODES: Final[tuple[str, ...]] = (
    "HEADER_MISSING",
    "COUNT_DIVERGENCE",
    "ABSORBED_QUESTION",
    "LOW_OPTION_COUNT",
    "EXPLANATION_BLEED",
    "COLUMN_ORDER_UNCERTAIN",
    "SEGMENTATION_INVALID",
    "SEGMENTATION_LEAK",
    "COLUMN_ORDER_SUSPECT",
)

_SEVERITY_ORDER: Final[dict[str, int]] = {"blocker": 0, "warning": 1, "info": 2}
_CODE_ORDER: Final[dict[str, int]] = {code: pos for pos, code in enumerate(MVP_WARNING_CODES)}
_EXPLANATION_BLEED_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:해설|정답)\s*[:：]?|(?<![가-힣])답\s*[:：]"
)

WARNING_DEFINITIONS: Final[dict[str, dict[str, str]]] = {
    "HEADER_MISSING": {
        "severity": "blocker",
        "message_ko": "범위/헤더를 찾지 못했습니다.",
        "detail_ko": "PDF의 범위 표시 형식이 다르거나 텍스트 레이어가 제대로 읽히지 않았을 수 있습니다.",
        "recommended_action": "--header-regex 를 조정하거나 OCR/텍스트 레이어를 확인한 뒤 다시 추출하세요.",
    },
    "COUNT_DIVERGENCE": {
        "severity": "warning",
        "message_ko": "답마커 기준 문항 수와 문제번호 기준 문항 수가 다릅니다.",
        "detail_ko": "답이 빠진 문항이나 잘못 잡힌 정답 마커 때문에 실제 문항 수와 다를 수 있습니다.",
        "recommended_action": "원본 PDF와 all_questions.json의 문항 수를 비교하세요. 필요하면 --auto-format 재추출을 고려하세요.",
    },
    "ABSORBED_QUESTION": {
        "severity": "warning",
        "message_ko": "한 문항에 여러 문제번호가 합쳐진 것 같습니다.",
        "detail_ko": "답이 없는 문제가 다음 답 있는 문제와 붙으면서 누락처럼 보일 수 있습니다.",
        "recommended_action": "표시된 idx 근처를 원본 PDF와 대조하세요. 실제 누락이면 --auto-format 재추출을 고려하세요.",
    },
    "LOW_OPTION_COUNT": {
        "severity": "warning",
        "message_ko": "선지 수가 너무 적게 잡혔습니다.",
        "detail_ko": "객관식 선지 분리가 실패했거나 일부 선지가 본문에 붙어 있을 수 있습니다.",
        "recommended_action": "표시된 idx의 원본 문항과 선지 패턴을 확인하세요.",
    },
    "EXPLANATION_BLEED": {
        "severity": "warning",
        "message_ko": "문제 본문에 정답/해설 문구가 섞인 것 같습니다.",
        "detail_ko": "인라인 정답/해설이 다음 문제 본문으로 침범했을 수 있습니다.",
        "recommended_action": "--auto-format 으로 다시 추출해 보고, 그래도 남으면 원본 PDF와 해당 idx를 대조하세요.",
    },
    "COLUMN_ORDER_UNCERTAIN": {
        "severity": "info",
        "message_ko": "2단 편집 읽기 순서를 확인해야 합니다.",
        "detail_ko": "컬럼 인지 추출이 사용되어 왼쪽/오른쪽 문제 순서가 원본과 맞는지 확인이 필요합니다.",
        "recommended_action": "2단 편집 원본과 all_questions.json 순서를 대조하고, 필요하면 --auto-format 결과를 확인하세요.",
    },
    "SEGMENTATION_INVALID": {
        "severity": "blocker",
        "message_ko": "포맷추론 분절 결과가 구조 검증을 통과하지 못했습니다.",
        "detail_ko": "라인 배정에 범위 밖·중복·미할당 본문이 있어 문항이 누락/중복됐을 수 있습니다.",
        "recommended_action": "segmentation.json 의 라인 배정을 다시 만들거나, 사람이 원본과 대조해 수동 보정하세요.",
    },
    "SEGMENTATION_LEAK": {
        "severity": "blocker",
        "message_ko": "포맷추론 분절에서 정답/해설이 문제 본문(블라인드)으로 샌 것 같습니다.",
        "detail_ko": "해설/정답 라인이 stem 으로 잘못 분류되어 블라인드 풀이가 오염될 수 있습니다.",
        "recommended_action": "표시된 idx 의 라인 역할(해설/정답)을 다시 분류해 segmentation.json 을 재생성하세요.",
    },
    "COLUMN_ORDER_SUSPECT": {
        "severity": "warning",
        "message_ko": "2단 편집 읽기 순서가 잘못됐을 가능성이 높습니다.",
        "detail_ko": (
            "컬럼 인지 추출 후 확인된 문항 수가 문제번호 기준 수의 절반 미만으로 줄어 "
            "읽기 순서 오류가 의심됩니다."
        ),
        "recommended_action": (
            "2단 편집 원본과 all_questions.json 의 문항 순서를 직접 대조하고, "
            "필요하면 --auto-format 으로 재추출하세요."
        ),
    },
}


def qcount_diverges(primary: int, secondary: int) -> bool:
    if not primary or not secondary:
        return False
    hi, lo = max(primary, secondary), min(primary, secondary)
    return (hi - lo) > max(2, 0.15 * hi)


def _count_value(counts: JsonMap, preferred_key: str, fallback_key: str) -> int:
    value = counts.get(preferred_key, counts.get(fallback_key, 0))
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0


def _question_idx(question: JsonMap, fallback_idx: int) -> int:
    value = question.get("idx", fallback_idx)
    if isinstance(value, bool):
        return fallback_idx
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return fallback_idx


def _warning_indices(warning: JsonMap) -> list[int]:
    raw_indices = warning.get("question_indices")
    if not isinstance(raw_indices, list):
        return []
    return [idx for idx in raw_indices if isinstance(idx, int) and not isinstance(idx, bool)]


def _warning_text(warning: JsonMap, key: str, default: str) -> str:
    value = warning.get(key)
    return value if isinstance(value, str) else default


def _make_warning(code: str, question_indices: Sequence[int] | None = None) -> JsonRecord:
    definition = WARNING_DEFINITIONS[code]
    return {
        "code": code,
        "severity": definition["severity"],
        "message_ko": definition["message_ko"],
        "detail_ko": definition["detail_ko"],
        "question_indices": sorted(set(question_indices or [])),
        "recommended_action": definition["recommended_action"],
    }


def make_warning(code: str, question_indices: Sequence[int] | None = None) -> JsonRecord:
    """단일 진실 정의로부터 경고 레코드를 만든다(검증 게이트 등 외부 주입용 공개 래퍼)."""
    return _make_warning(code, question_indices)


def _sort_key(warning: JsonMap) -> tuple[int, int, int]:
    indices = _warning_indices(warning)
    first_idx = min(indices) if indices else -1
    return (
        _SEVERITY_ORDER.get(_warning_text(warning, "severity", ""), 99),
        _CODE_ORDER.get(_warning_text(warning, "code", ""), 999),
        first_idx,
    )


def sort_parse_warnings(warnings: Sequence[JsonMap]) -> list[JsonRecord]:
    return sorted([dict(warning) for warning in warnings], key=_sort_key)


def build_parse_warnings(counts: JsonMap, blind_questions: Sequence[JsonMap]) -> list[JsonRecord]:
    warnings: list[JsonRecord] = []
    headers = _count_value(counts, "headers", "n_headers")
    questions = _count_value(counts, "questions", "n_questions")
    by_number = _count_value(counts, "questions_by_number", "n_questions_by_number")

    if headers == 0:
        warnings.append(_make_warning("HEADER_MISSING"))
    if qcount_diverges(questions, by_number):
        warnings.append(_make_warning("COUNT_DIVERGENCE"))

    absorbed: list[int] = []
    low_options: list[int] = []
    explanation_bleed: list[int] = []
    for fallback_idx, question in enumerate(blind_questions):
        idx = _question_idx(question, fallback_idx)
        if question.get("absorbed_qnums"):
            absorbed.append(idx)
        options = question.get("options")
        if isinstance(options, list) and len(options) < 3:
            low_options.append(idx)
        stem = str(question.get("stem") or question.get("stem_raw") or "")
        if _EXPLANATION_BLEED_RE.search(stem):
            explanation_bleed.append(idx)

    if absorbed:
        warnings.append(_make_warning("ABSORBED_QUESTION", absorbed))
    if explanation_bleed:
        warnings.append(_make_warning("EXPLANATION_BLEED", explanation_bleed))
    if low_options:
        warnings.append(_make_warning("LOW_OPTION_COUNT", low_options))
    if bool(counts.get("column_aware")):
        warnings.append(_make_warning("COLUMN_ORDER_UNCERTAIN"))

    return sort_parse_warnings(warnings)


def enrich_question_warnings(
    blind_questions: Sequence[JsonMap],
    warnings: Sequence[JsonMap],
) -> list[JsonRecord]:
    question_warnings: dict[int, list[JsonRecord]] = {}
    for warning in sort_parse_warnings(warnings):
        for idx in _warning_indices(warning):
            question_warnings.setdefault(idx, []).append(warning)

    enriched: list[JsonRecord] = []
    for fallback_idx, question in enumerate(blind_questions):
        rec = dict(question)
        idx = _question_idx(rec, fallback_idx)
        attached = question_warnings.get(idx, [])
        if attached:
            rec["warnings"] = [_warning_text(warning, "code", "") for warning in attached]
            rec["warning_messages"] = [_warning_text(warning, "message_ko", "") for warning in attached]
        enriched.append(rec)
    return enriched

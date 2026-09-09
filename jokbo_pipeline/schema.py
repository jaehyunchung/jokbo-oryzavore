# -*- coding: utf-8 -*-
"""
questions_data.py 스키마 단일 정의 (과목 무관, 파이프라인 공용).

이 모듈 하나가 build.py(DOCX) · ../kd_library/build_viewer.py(HTML 뷰어) · validate.py 의
**공유 진실(single source of truth)** 이다. 필드 목록·범위 헤더 파싱·교수명 정규화·왕족 태그·
정답 개수 판정을 여기서만 정의하고, 각 빌더는 import 해서 쓴다(복붙 금지).

뷰어(JS) 쪽에도 동일 로직(clean_scope / getProf / isRoyal / correctSet)이 viewer_template.html 에
있다 — 언어가 달라 공유 불가하나 **동작은 이 파일과 일치해야 한다**(변경 시 양쪽 같이 수정).
"""
import importlib.util
import re

# ─── 범위 헤더 꼬리 '· [<연도> 담당교수: …]' 파싱 ─────────────────────────────
# 연도는 하드코딩하지 않는다(연도 고정 시 다음 해부터 매칭 실패). 4자리 연도(19xx/20xx)면 매칭.
SCOPE_TAIL_RE = re.compile(r"\s*·\s*\[(?:19|20)\d{2}[^\]]*\]\s*$")
PROF_RE = re.compile(r"\[(?:19|20)\d{2}[^\]]*?담당교수\s*[:：]\s*([^\]]+)\]")
SCOPE_YEAR_RE = re.compile(r"\[((?:19|20)\d{2})[^\]]*?담당교수")
SCOPE_WEIGHT = {"same": 1.0, "unknown": 1.0, "changed": 0.7, "new": 0.7, "closed": 0.3}

# ─── 경고 문구 단일 진실(single source of truth) ─────────────────────────────
# DOCX(build.py) 와 HTML 뷰어(../kd_library/build_viewer.py) 두 출력물 모두 이 문자열을
# 그대로(verbatim) 삽입한다. main.py · INSTRUCTIONS.md 의 문구와 글자 단위로 동일해야 한다.
CANONICAL_WARNING = (
    "이 산출물은 AI가 검증·생성한 정보로 정확하지 않을 수 있으며, "
    "항상 강의록/원본과 본인이 직접 재확인하세요."
)

# ─── 왕족(빈출) 태그: new_expl 선두에 붙으면 별도 배지로 분리하고 본문에선 제거 ──
ROYAL_TAGS = ["【왕족】", "【킹왕족】"]
ROYAL_TAG = ROYAL_TAGS[0]

# ─── 교수명 '이름만' 정규화: '…과/교실 이름' → 이름 ───────────────────────────
DEPT_RE = re.compile(r'^(\S{2,}(?:과|교실))\s+(.+)$')

# ─── 뷰어/렌더가 그대로 전달하는 필드(있는 것만). image·images·image_missing 은 빌더가 별도 처리. ──
# image(단일)·images(다중, v2 #4) 는 빌더가 base64/경로로 별도 변환하므로 KEEP 에 넣지 않는다.
# image_caption(단일)·image_captions(다중) 은 순수 텍스트라 그대로 전달한다.
KEEP = [
    "meta", "years", "stem", "options", "verified", "answers", "source",
    "new_expl", "orig_ans", "orig_expl", "flags",
    "image_caption", "image_captions", "recon", "scope_note",
    # optional 리치 블록(있으면 렌더, 없으면 자동 숨김)
    "clinical_summary", "imp", "wrong_option_explanations", "tip", "related_theory",
]

# ─── 스키마 검사 기준(validate.py 가 사용) ────────────────────────────────────
# options 는 주관식이면 [](빈 배열) 일 수 있어 '키 존재'가 아니라 빌더가 별도 처리 → 필수에서 제외.
REQUIRED = ["meta", "stem", "verified", "new_expl"]
RECOMMENDED = ["years"]   # 없으면 build.py --strict-years 시 '(연도 미확인)'. 최종본은 채울 것.

FLAG_TAXONOMY = [
    "ANSWER_MATCH", "ANSWER_CORRECTED", "ANSWER_DISPUTED", "TEXT_RECONSTRUCTED",
    "STEM_IMAGE_A_PRESENT", "IMAGE_MISSING", "SCOPE_RECLASSIFIED_OR_INFERRED",
    # merge_rtype 가 부여하는 보조 플래그
    "MERGED_RTYPE", "ORIG_RTYPE", "ORIG_SINGLE",
]


def load_scopes(data_path):
    """questions_data.py 를 실행해 SCOPES(=[(header, [q...])]) 를 반환."""
    spec = importlib.util.spec_from_file_location("questions_data", data_path)
    qd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(qd)
    if not hasattr(qd, "SCOPES"):
        raise SystemExit(f"{data_path} 에 SCOPES 가 없습니다.")
    return qd.SCOPES


def clean_scope(h):
    """범위 헤더에서 '· [<연도> 담당교수: …]' 꼬리를 제거한 표시용 라벨."""
    return SCOPE_TAIL_RE.sub("", h or "").strip()


def scope_prof(h):
    """범위 헤더 꼬리의 '<연도> 담당교수' 이름(없으면 '')."""
    m = PROF_RE.search(h or "")
    return m.group(1).strip() if m else ""


def scope_year(h):
    """범위 헤더 꼬리에 적힌 담당교수 연도(예 '2026'; 없으면 '')."""
    m = SCOPE_YEAR_RE.search(h or "")
    return m.group(1) if m else ""


def scope_tokens(header: str | None) -> list[str]:
    """범위 헤더 교수란을 가운데점으로 나눈 원본 토큰 배열."""
    m = PROF_RE.search(header or "")
    return [token.strip() for token in m.group(1).split("·")] if m else []


def scope_token_status(raw_token: str, prof_names: set[str]) -> str:
    """담당교수 토큰 하나의 2026 상태를 판정."""
    if "미개설" in raw_token:
        return "closed"
    if "신설" in raw_token:
        return "new"
    name = re.sub(r"\([^)]*\)", "", raw_token).strip()
    if not name or name == "미정":
        return "unknown"
    return "same" if name in prof_names else "changed"


def scope_status(
    header: str | None, prof_names: set[str] | None
) -> dict[str, str | float | list[str]]:
    """범위 헤더의 2026 담당교수 상태와 학습 가중치를 반환."""
    prof2026 = scope_prof(header)
    if not prof2026:
        return {"status": "unknown", "weight": 1.0, "prof2026": "", "tokens": []}

    tokens = scope_tokens(header)
    statuses = [scope_token_status(token, prof_names or set()) for token in tokens]
    weight = max(SCOPE_WEIGHT[status] for status in statuses)
    status = next(
        candidate
        for candidate in ("same", "unknown", "changed", "new", "closed")
        if candidate in statuses and SCOPE_WEIGHT[candidate] == weight
    )
    return {"status": status, "weight": weight, "prof2026": prof2026, "tokens": tokens}


def split_prof(meta):
    """meta → (연도/머리부, 과·교실 or '', 교수이름). 교수 segment = 마지막 '·' 뒤."""
    s = meta or ''
    i = s.rfind('·')
    head, seg = (s[:i].strip(), s[i + 1:].strip()) if i >= 0 else ('', s.strip())
    m = DEPT_RE.match(seg)
    return (head, m.group(1), m.group(2).strip()) if m else (head, '', seg)


def meta_nameonly(meta):
    """meta 표시용: 과/교실명을 떼고 '연도 · 이름' (또는 이름만)."""
    head, _dept, name = split_prof(meta)
    return (head + ' · ' + name) if head else name


def is_royal(q):
    """new_expl 에 왕족 태그가 들어 있으면 True."""
    ne = q.get('new_expl')
    s = " ".join(str(x) for x in ne) if isinstance(ne, list) else (ne or "")
    return any(tag in s for tag in ROYAL_TAGS)


def strip_royal(s):
    """본문에서 왕족 태그 제거."""
    text = str(s)
    for tag in ROYAL_TAGS:
        text = text.replace(tag + " ", "").replace(tag, "")
    return text.strip()


def n_correct(q):
    """정답 개수. answers(복수정답) 있으면 그 길이, 없으면 1(단일·기존 호환).
    R형/복수정답 가능성을 반영 — verified 1개 가정에 묶이지 않음."""
    a = q.get('answers')
    return len(a) if isinstance(a, list) and a else 1


def as_text(x):
    """문자열 또는 리스트를 한 문자열로(불릿 합치기)."""
    return " ".join(str(i) for i in x) if isinstance(x, list) else (str(x) if x else "")

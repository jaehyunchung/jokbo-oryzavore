# -*- coding: utf-8 -*-
"""
test_extract.py — extract.count_extraction_markers() 회귀 테스트.

Sub-AC 8a: count_extraction_markers(text) 가 {header_count, answer_marker_count} 를
올바르게 반환하는지 합성 텍스트로 검증한다.

테스트 케이스:
  1. 정상 케이스 — 헤더 2개, 답 마커 3개
  2. 헤더 0개 케이스 (답 마커만 있음)
  3. 답 마커 0개 케이스 (헤더만 있음)
  4. 둘 다 0 케이스 — 빈 문자열
  5. 둘 다 0 케이스 — 무관한 일반 텍스트
  6. 다양한 답 마커 형식 (답/정답/딥, 콜론 유무, 전각콜론)
  7. 경계: 5자리 연도는 헤더로 매칭되지 않아야 함
  8. 커스텀 header_regex 파라미터 동작 확인

실행: python3 tests/test_extract.py   (pytest 불필요, plain assert)
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent                       # jokbo_pipeline/
sys.path.insert(0, str(PIPE))

from extract import count_extraction_markers, DEFAULT_HEADER_REGEX, split_blind_key  # noqa: E402

PASS = [0]
FAIL = [0]


def ok(cond, msg):
    if cond:
        PASS[0] += 1
    else:
        FAIL[0] += 1
        print("  ✗", msg)


def eq(a, b, msg):
    ok(a == b, f"{msg}  (got {a!r}, want {b!r})")


# ── 케이스 1: 정상 케이스 — 헤더 2, 답 마커 3 ──────────────────────────────────
_NORMAL = (
    "[2023 예시과 교수A] 1차범위\n"
    "문항 내용 첫 번째.\n"
    "답: 2\n"
    "문항 내용 두 번째.\n"
    "답: 1\n"
    "[2022 예시과 교수B] 2차범위\n"
    "문항 내용 세 번째.\n"
    "답: 3\n"
)
_r1 = count_extraction_markers(_NORMAL)
eq(_r1["header_count"], 2, "정상 케이스: header_count == 2")
eq(_r1["answer_marker_count"], 3, "정상 케이스: answer_marker_count == 3")

# ── 케이스 2: 헤더 0개 (답 마커만 있음) ─────────────────────────────────────────
_NO_HEADERS = (
    "이 텍스트에는 범위 헤더가 없습니다.\n"
    "문항 내용.\n"
    "답: 1\n"
    "또 다른 문항.\n"
    "정답: 4\n"
)
_r2 = count_extraction_markers(_NO_HEADERS)
eq(_r2["header_count"], 0, "헤더 0: header_count == 0")
eq(_r2["answer_marker_count"], 2, "헤더 0: answer_marker_count == 2")

# ── 케이스 3: 답 마커 0개 (헤더만 있음) ─────────────────────────────────────────
_NO_ANSWERS = (
    "[2023 내과 교수C] 범위A\n"
    "문항 내용만 있고 답 마커가 없습니다.\n"
    "[2021 외과 교수D] 범위B\n"
    "또 다른 문항.\n"
)
_r3 = count_extraction_markers(_NO_ANSWERS)
eq(_r3["header_count"], 2, "답마커 0: header_count == 2")
eq(_r3["answer_marker_count"], 0, "답마커 0: answer_marker_count == 0")

# ── 케이스 4: 둘 다 0 — 빈 문자열 ─────────────────────────────────────────────
_r4 = count_extraction_markers("")
eq(_r4["header_count"], 0, "빈 문자열: header_count == 0")
eq(_r4["answer_marker_count"], 0, "빈 문자열: answer_marker_count == 0")

# ── 케이스 5: 둘 다 0 — 무관한 일반 텍스트 ────────────────────────────────────
_IRRELEVANT = "This is plain English text with no Korean markers or bracket headers.\n"
_r5 = count_extraction_markers(_IRRELEVANT)
eq(_r5["header_count"], 0, "무관 텍스트: header_count == 0")
eq(_r5["answer_marker_count"], 0, "무관 텍스트: answer_marker_count == 0")

# ── 케이스 6: 다양한 답 마커 형식 ───────────────────────────────────────────────
# 답/정답/딥, 콜론 유무, 전각콜론(：), 두 자리 숫자, 물음표(미확인)
_VARIED_MARKERS = (
    "[2020 교수E] 범위X\n"
    "문항1.\n"
    "답: 1\n"           # 기본 형식
    "문항2.\n"
    "정답: 12\n"        # 정답 + 두 자리 숫자
    "문항3.\n"
    "딥: 5\n"           # 딥 형식
    "문항4.\n"
    "답：3\n"           # 전각 콜론
    "문항5.\n"
    "답 2\n"            # 공백만(콜론 없음)
    "문항6.\n"
    "답: ??\n"          # 미확인 답
    "문항7.\n"
    "답: ?\n"           # 단일 물음표
)
_r6 = count_extraction_markers(_VARIED_MARKERS)
eq(_r6["header_count"], 1, "다양한 마커: header_count == 1")
eq(_r6["answer_marker_count"], 7, "다양한 마커: answer_marker_count == 7 (7가지 형식 모두)")

# ── 케이스 7: 경계 — 5자리 연도는 헤더로 매칭되지 않아야 함 ────────────────────
_BAD_YEAR = (
    "[20230 예시과 교수F] 이건 5자리라 헤더 아님\n"
    "[2023 예시과 교수F] 이건 맞는 4자리 헤더\n"
    "답: 1\n"
)
_r7 = count_extraction_markers(_BAD_YEAR)
eq(_r7["header_count"], 1, "경계 케이스: 5자리 연도 제외, 4자리 헤더만 1개 매칭")
eq(_r7["answer_marker_count"], 1, "경계 케이스: answer_marker_count == 1")

# ── 케이스 8: 커스텀 header_regex — 다른 패턴으로 교체 ─────────────────────────
# 간단한 "Q:" 패턴을 헤더로 인식하는 커스텀 정규식
_CUSTOM_TEXT = (
    "Q: 첫 번째 문항\n"
    "답: 2\n"
    "Q: 두 번째 문항\n"
    "답: 3\n"
    "[2023 교수G] 기본 헤더 — 이건 커스텀 regex 에서 안 잡힘\n"
)
_r8 = count_extraction_markers(_CUSTOM_TEXT, header_regex=r'Q:\s+\S')
eq(_r8["header_count"], 2, "커스텀 regex: Q: 헤더 2개 인식")
eq(_r8["answer_marker_count"], 2, "커스텀 regex: answer_marker_count == 2 (ANS_RE 변경 없음)")

# ── 케이스 9: 반환 dict 키 정확성 확인 ──────────────────────────────────────────
_r9 = count_extraction_markers(_NORMAL)
ok("header_count" in _r9, "반환 dict에 'header_count' 키 존재")
ok("answer_marker_count" in _r9, "반환 dict에 'answer_marker_count' 키 존재")
ok(isinstance(_r9["header_count"], int), "header_count 값은 int 타입")
ok(isinstance(_r9["answer_marker_count"], int), "answer_marker_count 값은 int 타입")

# ── 케이스 10: DEFAULT_HEADER_REGEX 상수 공개 확인 ───────────────────────────────
ok(isinstance(DEFAULT_HEADER_REGEX, str), "DEFAULT_HEADER_REGEX 가 모듈 레벨 문자열 상수로 공개됨")
ok(len(DEFAULT_HEADER_REGEX) > 0, "DEFAULT_HEADER_REGEX 가 비어 있지 않음")
# 기본 regex는 4자리 연도 [ 패턴을 포함해야 함
ok(r'\d{4}' in DEFAULT_HEADER_REGEX, "DEFAULT_HEADER_REGEX 가 4자리 연도 패턴(\\d{4})을 포함")

# ── 케이스 11: split_blind_key 블라인드 불변식 (재검증 기본 경로의 핵심) ─────────
# all_questions.json(블라인드)에는 원본 답·해설이 절대 없어야 하고, answer_key.json(봉인)에만 있어야 한다.
_BK_TEXT = (
    "[2023 예시과 교수A] 범위1\n"
    "첫 번째 문항 본문입니다.\n"
    "답: 2\n"
    "두 번째 문항 본문입니다.\n"
    "정답: 4\n"
)
_hf = lambda idx: ("2023", "예시과 교수A", "범위1")   # noqa: E731
_pf = lambda idx: 1                                      # noqa: E731
_blind, _key = split_blind_key(_BK_TEXT, _hf, _pf)

eq(len(_blind), 2, "split_blind_key: blind 2문항")
eq(len(_key), 2, "split_blind_key: key 2개")
ok(all(('answer' not in q) and ('expl_raw' not in q) for q in _blind),
   "★블라인드 불변식: blind 에 'answer'·'expl_raw' 키가 전혀 없음(원본 정답 미노출)")
ok(all('stem_raw' in q and q['stem_raw'] for q in _blind),
   "blind 각 문항에 stem_raw 존재(풀이 가능)")
ok(all(('answer' in q) and ('expl_raw' in q) for q in _key),
   "answer_key: 각 항목에 원본 answer·expl_raw 존재")
eq([q['answer'] for q in _key], ['2', '4'], "answer_key: 원본 답 값 정확(2, 4)")
eq([q['idx'] for q in _blind], [q['idx'] for q in _key],
   "blind·key idx 1:1 정렬 일치(병합 가능)")
ok(all(('답:' not in q['stem_raw']) and ('정답:' not in q['stem_raw']) for q in _blind),
   "blind stem 에 답 마커 텍스트가 남지 않음")
# 빈 입력 방어
eq(split_blind_key("", _hf, _pf), ([], []), "split_blind_key: 빈 텍스트 → ([], [])")

print(f"\n[test_extract] {PASS[0]} passed, {FAIL[0]} failed")
sys.exit(1 if FAIL[0] else 0)

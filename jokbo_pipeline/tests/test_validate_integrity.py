# -*- coding: utf-8 -*-
"""
test_validate_integrity.py — validate.integrity_check() 구조 무결성 회귀 테스트(감사 Tier2).

검사: 정답 인덱스 범위·중복, verified↔answers 일치, flag 그룹 상호배타,
      images↔image_captions 길이, years 형식, 정정/논쟁 source 필수, 동일 stem 중복(경고),
      이미지 플래그↔실제 데이터 정합성, 선지 마커 연속성, 해설의 마크다운 잔존.

실행: python3 jokbo_pipeline/tests/test_validate_integrity.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent
sys.path.insert(0, str(PIPE))

from validate import integrity_check, _marker_index  # noqa: E402

PASS = [0]
FAIL = [0]


def ok(cond, msg):
    if cond:
        PASS[0] += 1
    else:
        FAIL[0] += 1
        print("  ✗", msg)


def _errs(q):
    e, _w = integrity_check([("범위", [q])])
    return " ".join(e)


def _warns(q):
    _e, w = integrity_check([("범위", [q])])
    return " ".join(w)


_BASE = {"meta": "2023 · 홍길동", "stem": "문항?", "verified": "②",
         "options": ["①", "②", "③", "④", "⑤"], "new_expl": "해설"}


def good(**kw):
    q = dict(_BASE); q.update(kw); return q


# _marker_index
ok(_marker_index("②") == 2, "마커 '②' → 2")
ok(_marker_index("3번") == 3, "마커 '3번' → 3")
ok(_marker_index("") is None, "빈 마커 → None")

# 정상 문항은 에러 0
ok(_errs(good()) == "", "정상 문항 에러 0")

# 정답 인덱스 범위 초과(선지 2개인데 ⑤)
ok("초과" in _errs(good(options=["①", "②"], verified="⑤")),
   "선지 2개인데 verified ⑤ → 범위 초과 에러")
ok("초과" in _errs(good(answers=["⑨"], verified="⑨")),
   "answers ⑨ 인데 선지 5개 → 범위 초과 에러")

# answers 중복
ok("중복 정답" in _errs(good(answers=["②", "②"], verified="②")),
   "answers 중복 정답 에러")

# verified ↔ answers 불일치
ok("불일치" in _errs(good(answers=["③", "④"], verified="②")),
   "verified ②가 answers[③,④]에 없음 → 불일치 에러")

# flag 그룹 상호배타
ok("answer_group" in _errs(good(flags=["ANSWER_MATCH", "ANSWER_CORRECTED"], source="교과서")),
   "ANSWER_MATCH+ANSWER_CORRECTED 동시 → 에러")
ok("image_group" in _errs(good(flags=["STEM_IMAGE_A_PRESENT", "IMAGE_MISSING"])),
   "STEM_IMAGE_A_PRESENT+IMAGE_MISSING 동시 → 에러")

# 정정/논쟁 source 필수
ok("source" in _errs(good(flags=["ANSWER_CORRECTED"])),
   "ANSWER_CORRECTED 인데 source 없음 → 에러")
ok(_errs(good(flags=["ANSWER_CORRECTED"], source="2026 강의록 p34")) == "",
   "ANSWER_CORRECTED + source 있으면 통과")
ok(_errs(good(flags=["ANSWER_MATCH"])) == "",
   "ANSWER_MATCH 는 source 없어도 통과(매치는 근거 약식 가능)")

# images ↔ image_captions 길이
ok("길이 불일치" in _errs(good(images=["a.jpg"], image_captions=["c1", "c2", "c3"])),
   "image_captions(3) > images(1) → 길이 불일치 에러")
ok(_errs(good(image="x.jpg", images=["a.jpg"], image_captions=["c1", "c2"])) == "",
   "단일 image + images[1] = 2장이면 captions 2개 OK")

# years 형식
ok("비연도" in _errs(good(years=["2021", "스물한"])),
   "years 에 비연도 문자열 → 에러")
ok(_errs(good(years=["2021", "2019"])) == "", "정상 연도는 통과")

# 동일 stem 중복 → 경고(에러 아님)
dup_scope = [("범위", [good(stem="완전히 같은 문항 본문입니다"),
                       good(stem="완전히 같은 문항 본문입니다", meta="2022 · 김철수")])]
e, w = integrity_check(dup_scope)
ok(e == [], "동일 stem 중복은 빌드 차단(에러) 아님")
ok(any("중복" in x for x in w), "동일 stem 중복은 경고로 보고")

# ── 이미지 플래그 ↔ 실제 데이터 정합성 ──────────────────────────────────────
ok("STEM_IMAGE_A_PRESENT 인데" in _errs(good(flags=["STEM_IMAGE_A_PRESENT"])),
   "STEM_IMAGE_A_PRESENT 인데 사진이 없으면 에러")
ok(_errs(good(flags=["STEM_IMAGE_A_PRESENT"], image="p1.jpg")) == "",
   "사진이 붙어 있으면 통과")
ok(_errs(good(flags=["STEM_IMAGE_A_PRESENT"], images=["a.jpg", "b.jpg"])) == "",
   "다중 이미지도 통과")
ok("image_group flag 없음" in _warns(good(image="p1.jpg")),
   "이미지가 있는데 플래그가 없으면 경고")

ok("image_missing 설명 없음" in _warns(good(flags=["IMAGE_MISSING"])),
   "IMAGE_MISSING 인데 설명이 없으면 경고")
ok("image_missing 설명 없음" not in _warns(good(flags=["IMAGE_MISSING"], image_missing="흉부 X선")),
   "설명이 있으면 통과")
ok("IMAGE_MISSING flag 없음" in _warns(good(image_missing="흉부 X선")),
   "설명만 있고 플래그가 없으면 경고")

# ── 선지 마커 연속성 ────────────────────────────────────────────────────────
ok("마커 불연속" in _warns(good(options=["① 가", "② 나", "③ 다", "⑤ 마"])),
   "선지 마커를 건너뛰면 경고")
ok("마커 불연속" not in _warns(good(options=["① 가", "② 나", "③ 다"])),
   "연속 마커는 통과")
ok("마커 불연속" not in _warns(good(options=["가", "나", "다"])),
   "마커 없는 선지는 검사 대상 아님")

# ── 마크다운 잔존 ──────────────────────────────────────────────────────────
ok("마크다운" in _warns(good(new_expl=["이것은 **중요**하다"])),
   "**강조** 는 경고")
ok("마크다운" in _warns(good(tip="*Klebsiella* 감염")),
   "학명 이탤릭도 경고")
ok("마크다운" in _warns(good(clinical_summary={"소견": "**양성**"})),
   "리치블록 dict 값도 검사")
ok("마크다운" not in _warns(good(new_expl=["치식 6* 와 ** 는 내용이다"])),
   "치식 표기의 단독 별표는 오탐 아님")
ok("마크다운" not in _warns(good(new_expl=["곱셈 2 * 3 * 4"])),
   "공백 낀 별표는 오탐 아님")

print(f"\n[test_validate_integrity] {PASS[0]} passed, {FAIL[0]} failed")
sys.exit(1 if FAIL[0] else 0)

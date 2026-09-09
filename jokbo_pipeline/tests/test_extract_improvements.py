# -*- coding: utf-8 -*-
"""
test_extract_improvements.py — jokbo-oryzavore v2 파싱 6대 개선 회귀 테스트.

외부 파싱 개선 보고서의 6개 항목을 extract.py 의 순수함수로 검증한다.
  #1 split_stem_options    — 지문/선지 분리(①·1.·1))
  #2 clean_stem            — 이전 문항 해설 침범 제거
  #3 parse_categories      — [2025년]·<소화기>·교수 동시 추적 → bucket
  #5 split_stem_options    — 2~3개 선지·마침표/괄호도 인식(선지 유실 완화)
  #6 unmerge_glued         — 'N장영실 교수님' 들러붙은 문항 강제 분리
  #4 assign_candidate_images — y좌표 기반 후보 이미지(없으면 graceful fallback)

실행: python3 jokbo_pipeline/tests/test_extract_improvements.py   (pytest 불필요)
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent                       # jokbo_pipeline/
sys.path.insert(0, str(PIPE))

import re  # noqa: E402
from extract import (  # noqa: E402
    unmerge_glued, clean_stem, split_stem_options, parse_categories,
    compose_bucket, assign_candidate_images, split_blind_key, ANS_RE,
    strip_leading_header, DEFAULT_HEADER_REGEX,
)

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


# ── #6 Unmerging ──────────────────────────────────────────────────────────────
_glued = "정답입니다.2장영실 교수님 다음 환자 3장영실 교수님 또"
_un = unmerge_glued(_glued)
ok("\n2장영실" in _un, "#6 들러붙은 'N장영실 교수' 앞에 개행 삽입")
ok(_un.count("\n") >= 1, "#6 최소 1건 분리")
# 일반 숫자(제2형 등)는 건드리지 않는다
eq(unmerge_glued("제2형 당뇨병 환자"), "제2형 당뇨병 환자", "#6 '교수' 없는 일반 숫자는 미변경")
# 공백 있는(안 들러붙은) 번호는 미변경
eq(unmerge_glued("문항 3장영실 교수").count("\n"), 0,
   "#6 앞이 공백이면(안 들러붙음) 분리하지 않음")

# ── #1 / #5 지문·선지 분리 ────────────────────────────────────────────────────
s, o = split_stem_options("다음 중 옳은 것은? ① 가 ② 나 ③ 다 ④ 라 ⑤ 마")
eq(s, "다음 중 옳은 것은?", "#1 원문자 stem 분리")
eq(len(o), 5, "#1 원문자 선지 5개")
s, o = split_stem_options("가장 적절한 처치는? 1. 수술 2. 항생제 3. 경과관찰")
eq(len(o), 3, "#5 '1.' 마침표형 선지 3개 인식")
ok(o[0].startswith("1."), "#5 선지에 마커 보존")
s, o = split_stem_options("맞는 것은? 1) 가 2) 나")
eq(len(o), 2, "#5 2개 선지(괄호형)도 인식")
s, o = split_stem_options("주관식: 진단명을 쓰시오")
eq(o, [], "#5 마커 없으면 선지 빈 배열(단답 보호)")
# 본문 속 일반 숫자는 선지로 오인하지 않는다(연속 1,2 시퀀스 아님)
s, o = split_stem_options("2형 당뇨 환자에서 5년 뒤 합병증은?")
eq(o, [], "#5 본문 숫자(2형·5년)는 선지로 오탐하지 않음")
# run-on(줄바꿈·공백 없이 마침표로 붙은) 숫자 선지도 분리(실족보 형식)
s, o = split_stem_options("옳은 것은? 1. 가이다.2. 나이다.3. 다이다")
eq(len(o), 3, "#5 run-on '…이다.2.' 마침표-글루 선지 3개 분리")
# 소수점은 선지로 오인하지 않는다
s, o = split_stem_options("용량 2.5 mg 와 1.0 g 중 옳은 것은?")
eq(o, [], "#5 소수(2.5·1.0)는 선지 마커로 오탐하지 않음")

# ── #2 해설 침범 제거 ─────────────────────────────────────────────────────────
c = clean_stem("해설: 앞 문항 정답은 ②이다. 부연.\n3. 다음 환자에서 처치는?")
eq(c, "3. 다음 환자에서 처치는?", "#2 '해설:' 뒤 새 문제번호부터를 stem 으로")
c2 = clean_stem("   ))) 다음 중 옳은 것은?")
eq(c2, "다음 중 옳은 것은?", "#2 선두 공백·특수문자 정제")
# 해설 마커 없으면 선지 번호를 오절단하지 않는다
c3 = clean_stem("다음 중? 1. 가 2. 나")
ok(c3.startswith("다음 중?"), "#2 해설 마커 없으면 선지번호 오절단 안 함")

# ── #3 연도·분류·교수 ─────────────────────────────────────────────────────────
# 교수명은 경칭형('…교수님') 또는 라벨형('담당교수:')만 인정(감사 P0-4)
tf = parse_categories("[2025년] 머리말 <소화기> 본문 김철수 교수님 문제 여기서부터")
y, cat, prof = tf(40)
eq(y, "2025", "#3 [2025년] 연도 추적")
eq(cat, "소화기", "#3 <소화기> 분류 추적")
eq(prof, "김철수", "#3 교수명 추적(경칭형)")
# 라벨형 '담당교수:' 는 '담당'이 아니라 콜론 뒤 이름을 잡는다(P0-4 회귀)
_pl = parse_categories("[2024] <예시범위> 담당교수: 박영희 본문")(30)
eq(_pl[2], "박영희", "#3 '담당교수: 박영희' → prof '박영희'(‘담당’ 오인 안 함)")
# 자유본문의 'OOO 교수에게/교수가'는 메타데이터로 쓰지 않는다(오염 차단)
eq(parse_categories("환자를 이순신 교수에게 의뢰하였다 다음")(20)[2], "",
   "#3 본문 'OOO 교수에게'는 교수로 잡지 않음(오염 차단)")
eq(compose_bucket("2025", "소화기", "김철수"), "[2025] <소화기> 담당교수:김철수", "#3 bucket 합성")
# 구조 마커(<정답 및 해설>)·비이름 토큰(즉시·문제)은 분류·교수에서 제외(실족보 노이즈 컷)
tf_noise = parse_categories("<정답 및 해설> 즉시 교수 본문 여기")
_y, _c, _p = tf_noise(20)
eq(_c, "", "#3 <정답 및 해설> 같은 구조 마커는 분류로 잡지 않음")
eq(_p, "", "#3 '즉시 교수' 같은 비이름 토큰은 교수로 잡지 않음")
eq(compose_bucket("", "소화기", ""), "<소화기>", "#3 빈 부분은 생략")
eq(compose_bucket("", "", ""), "", "#3 전부 비면 빈 문자열")

# split_blind_key 에 tags_for 주면 bucket/category/prof 채워짐(+ stem/options)
_txt = "[2025년] <소화기> 김철수 교수\n1. 첫 문항 본문? 1) 가 2) 나\n답: 1\n"
_hf = lambda i: ("2025", "소화기 김철수", "범위")   # noqa: E731
_pf = lambda i: 1                                    # noqa: E731
blind, key = split_blind_key(_txt, _hf, _pf, tags_for=tf)
ok(blind and "bucket" in blind[0], "#3 split_blind_key(tags_for) → bucket 부여")
ok("options" in blind[0] and "stem" in blind[0], "#1 split_blind_key → stem·options 부여")
ok("answer" not in blind[0] and "expl_raw" not in blind[0],
   "블라인드 불변식 유지(answer·expl_raw 없음)")

# ── #4 이미지 BBox 매핑 ───────────────────────────────────────────────────────
# 페이지1에 문항 2개(y=100,400), 이미지 2개(y=150,420) → y구간으로 각 1장 배정
geo = {1: {"images": [(150, 200), (420, 470)],
           "words": [(100, "첫째문항"), (400, "둘째문항")]}}
page_images = {1: ["p01_001_a.jpg", "p01_002_b.jpg"]}
b = [{"idx": 0, "page": 1, "stem": "첫째문항 본문"},
     {"idx": 1, "page": 1, "stem": "둘째문항 본문"}]
assign_candidate_images(geo, page_images, b)
eq(b[0].get("candidate_images"), ["p01_001_a.jpg"], "#4 위 문항 → 위 이미지")
eq(b[1].get("candidate_images"), ["p01_002_b.jpg"], "#4 아래 문항 → 아래 이미지")
# pdfplumber 부재(None) → 후보 키 자체가 없어야 함(graceful fallback)
b2 = [{"idx": 0, "page": 1, "stem": "x"}]
assign_candidate_images(None, page_images, b2)
ok("candidate_images" not in b2[0], "#4 geometry=None → candidate_images 생략(fallback)")
# y추정 실패 → 페이지 전체 후보(안전)
b3 = [{"idx": 0, "page": 1, "stem": "없는단어"}, {"idx": 1, "page": 1, "stem": "또없음"}]
assign_candidate_images({1: {"images": [(1, 2), (3, 4)], "words": [(9, "전혀다름")]}},
                        page_images, b3)
eq(b3[0].get("candidate_images"), ["p01_001_a.jpg", "p01_002_b.jpg"],
   "#4 y추정 실패 → 페이지 전체 후보(폴백)")

# ── 감사 P0-1: ANS_RE 오탐 가드 + 원문자/복수/영문 답 ─────────────────────────
def _ans(t):
    return [m.group(0) for m in ANS_RE.finditer(t)]
eq(_ans("응답 2명 중 1명이"), [], "P0-1 '응답 2명'을 정답마커로 오인하지 않음(한글꼬리 가드)")
eq(_ans("화답 3가지"), [], "P0-1 '화답 3'도 오인하지 않음")
ok(_ans("정답: ③") == ["정답: ③"], "P0-1 원문자 답 '정답: ③' 인식")
ok(_ans("답: A") == ["답: A"], "P0-1 영문 답 '답: A' 인식")
m = ANS_RE.search("정답: 1, 3")
ok(m and m.group(1).replace(" ", "") == "1,3", "P0-1 복수 답 '1, 3' 통째 캡처")
m2 = ANS_RE.search("정답: ②, ④")
ok(m2 and "②" in m2.group(1) and "④" in m2.group(1), "P0-1 복수 원문자 '②, ④' 캡처")
ok(_ans("답: 2") == ["답: 2"], "P0-1 기존 '답: 2' 정상 유지")

# ── 감사 P0-2: answer_key 해설이 '다음 문제'를 머금지 않음 ────────────────────
_bleed = ("첫 문항 본문?\n답: 2\n첫 해설이다 핵심.\n2. 둘째 문제 본문? 1) 다 2) 라\n답: 3\n")
_hf2 = lambda i: (None, None, None)   # noqa: E731
_pf2 = lambda i: 1                    # noqa: E731
bl, ky = split_blind_key(_bleed, _hf2, _pf2)
ok(len(ky) == 2, "P0-2 답마커 2개")
ok("둘째 문제" not in ky[0]["expl_raw"],
   "P0-2 첫 문항 expl_raw 가 둘째 문제 지문을 머금지 않음(다음 문제에서 절단)")
ok("첫 해설" in ky[0]["expl_raw"], "P0-2 자기 해설은 보존")

# ── 감사 P0-5: 주관식은 오답선지 해설을 강제하지 않는다 ────────────────────────
from build import detail_gaps  # noqa: E402
_ne = ("타이피컬 앙기나는 흉골 뒤 통증·운동 유발·휴식/NTG 완화 세 가지가 특징이며 이를 충실히 서술한다.")
_subj = {"stem": "특징 3가지를 쓰시오", "options": [], "verified": "정의", "imp": "핵심", "new_expl": _ne}
ok("오답선지" not in " ".join(detail_gaps(_subj)),
   "P0-5 주관식(options=[])은 '오답선지' 게이트에 걸리지 않음")
eq(detail_gaps(_subj), [], "P0-5 충실한 주관식은 strict-detail 통과")
_obj = {"stem": "옳은 것은?", "options": ["①", "②", "③", "④", "⑤"],
        "verified": "②", "imp": "핵심", "new_expl": _ne}
ok(any("오답선지" in g for g in detail_gaps(_obj)),
   "P0-5 객관식은 여전히 오답선지 해설을 요구(기능 보존)")

# ── 감사 P2: 문제번호('Q1.'/'1.')가 선지 1로 흡수되지 않는다 ───────────────────
# 혼합 구분자: 'Q1.'(.) + 선지 '1) 2) … 5)'()) → '1.' 은 선지 아님, 선지는 ')' 5개.
s, o = split_stem_options(
    "Q1. Which best describes mechanism X?\n1) alpha 2) beta 3) gamma 4) delta 5) epsilon")
eq(s, "Q1. Which best describes mechanism X?", "P2 'Q1.' 은 stem 에 남음(선지 흡수 안 함)")
eq(len(o), 5, "P2 실제 선지 5개(')' 구분자) 인식")
ok(o[0].startswith("1)"), "P2 첫 선지는 '1) alpha'(질문번호 '1.' 이 아님)")
# 동일번호 중복: 문제번호 '1.' + 선지 '1) 2)' → 문제번호는 stem, 선지 2개
s, o = split_stem_options("1. 첫 문항 본문? 1) 가 2) 나")
eq(s, "1. 첫 문항 본문?", "P2 선두 문제번호 '1.' 은 stem(혼합 구분자)")
eq(len(o), 2, "P2 괄호형 선지 2개만")
# 같은 구분자 중복: '1. 다음? 1. 가 2. 나 3. 다' → 늦은 run(선지)을 택해 문제번호 보존
s, o = split_stem_options("1. 다음 처치는? 1. 가 2. 나 3. 다")
eq(s, "1. 다음 처치는?", "P2 동일 구분자 중복도 문제번호를 stem 에 남김(늦은 run 선택)")
eq(len(o), 3, "P2 마침표형 선지 3개")
ok(o[0].startswith("1. 가"), "P2 첫 선지는 '1. 가'(문제번호 '1.' 아님)")

# ── 감사 P2: 첫 문항 stem 에 배너·헤더 블록이 섞이지 않는다 ────────────────────
_hdr_re = re.compile(DEFAULT_HEADER_REGEX)
_seg_banner = ("=== DRY RUN SAMPLE ===\n=== NOT A REAL EXAM ===\n"
               "[2024 SampleDept ProfA] Scope A\nQ1. Which mechanism?")
_stripped = strip_leading_header(_seg_banner, _hdr_re)
ok("DRY RUN SAMPLE" not in _stripped, "P2 헤더 앞 배너 제거")
ok("[2024 SampleDept" not in _stripped, "P2 헤더 라벨 제거(메타로 이미 파싱됨)")
ok(_stripped.strip().startswith("Q1."), "P2 stem 은 질문 본문부터 시작")
# 헤더 없는 블록 2번째 문항 seg 는 손대지 않는다
_seg_nohdr = "\n\nQ2. A patient presents? 1) a 2) b"
eq(strip_leading_header(_seg_nohdr, _hdr_re), _seg_nohdr,
   "P2 헤더 없으면 seg 미변경(블록 내 2번째 이후 문항 보호)")
# split_blind_key 통합: 배너+헤더로 시작하는 첫 문항 stem 이 'Q1.' 부터 시작
_full_p2 = ("=== BANNER ===\n[2024 SampleDept ProfA] Scope A\n"
            "Q1. Which mechanism X?\n1) alpha 2) beta 3) gamma\n답: 2\n")
_bl, _ky = split_blind_key(_full_p2, lambda i: ("2024", "SampleDept ProfA", "Scope A"),
                           lambda i: 1, header_re=_hdr_re)
ok(_bl[0]["stem"].startswith("Q1."), "P2 split_blind_key: 첫 문항 stem 이 'Q1.' 부터(배너·헤더 제거)")
eq(len(_bl[0]["options"]), 3, "P2 split_blind_key: 선지 3개 정상 분리")

print(f"\n[test_extract_improvements] {PASS[0]} passed, {FAIL[0]} failed")
sys.exit(1 if FAIL[0] else 0)

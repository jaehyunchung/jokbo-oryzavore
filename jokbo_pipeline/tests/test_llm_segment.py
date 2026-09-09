# -*- coding: utf-8 -*-
"""
test_llm_segment.py — Phase2 포맷추론 에스컬레이션의 코드 절단/검증(llm_segment) 회귀.

규칙적 답·해설 구분자가 없는 freeform 합본 기출(학생 인라인 코멘트형 — Phase1 format_probe 가
폴백하는 케이스)을 라인 인덱싱한 뒤, LLM Segmenter 가 냈다고 가정한 '포인터맵(라인ID→역할)'으로
코드가 절단했을 때:
  1) apply_segmentation 이 blind/key 를 split_blind_key 동일 계약으로 만들고
     블라인드 불변식(blind 에 answer/expl_raw 키 0)·정답키 idx 정렬을 지키는가.
  2) run-on 선지 분리·정답값 추출이 되는가.
  3) verify_segmentation 이 LLM 출력을 신뢰하지 않고 결함을 잡는가 —
     파티션 중복(overlap)·범위밖(range)·미할당 본문(coverage)·블라인드 불변식 위반,
     그리고 누출(해설 마커 stem 침범 / 봉인 해설 핵심어가 blind 로 대량 겹침).
  4) normalize_segmentation_map 이 문자열 정수 강제·누락 키를 관대하게 정규화하는가.
  5) 결정성(같은 입력 → 같은 출력).

합성 데이터는 과목 무관(행정/경제) placeholder — 어떤 과목/이름/제목/문구도 코드에 없다.
실행: python3 jokbo_pipeline/tests/test_llm_segment.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent
sys.path.insert(0, str(PIPE))

import llm_segment as S                                       # noqa: E402

PASS = [0]; FAIL = [0]


def ok(cond, msg):
    if cond:
        PASS[0] += 1
    else:
        FAIL[0] += 1
        print("  ✗", msg)


def eq(a, b, msg):
    ok(a == b, f"{msg}  (got {a!r}, want {b!r})")


# ── 합성 freeform 합본(규칙적 구분자 없음, 인라인 학생 코멘트형) ────────────────
LINES = [
    "과목 후기 — 다들 화이팅",                       # 0  표지/잡음(ignore)
    "1. 행정의 정의로 옳은 것은?",                    # 1  stem
    "1) 공익 2) 이윤 3) 권력 4) 비용 5) 여론",        # 2  options(run-on)
    "답 1번 (작년 기출이랑 선지순서까지 똑같이 나옴)", # 3  answer(freeform)
    "해설 나머지는 사익이나 권력 개념이라 행정과 무관", # 4  explanation(누출원)
    "2. 기회비용의 정의로 옳은 것은?",                # 5  stem
    "1) 매몰비용 2) 차선의가치 3) 총비용 4) 고정비용 5) 한계수입",  # 6  options
    "답: 2번",                                       # 7  answer
    "3. 핵심 가치 세 가지를 서술하시오.",             # 8  stem(주관식)
    "정답 공익 능률 민주성",                          # 9  answer(주관식, 숫자 아님)
    "",                                              # 10 blank(미할당 허용)
]

CLEAN_MAP = {
    "questions": [
        {"qid": 1, "stem_lines": [1], "option_lines": [2],
         "answer_lines": [3], "explanation_lines": [4]},
        {"qid": 2, "stem_lines": [5], "option_lines": [6],
         "answer_lines": [7], "explanation_lines": []},
        {"qid": 3, "stem_lines": [8], "option_lines": [],
         "answer_lines": [9], "explanation_lines": []},
    ],
    "ignore_lines": [0],
}


def hf(_off):
    return ("", "행정학 총론", "행정학 총론")


def pf(_off):
    return 1


def tf(_off):
    return ("", "", "")


def run():
    # ── 1) apply: 블라인드 불변식 + 계약 ────────────────────────────────────
    blind, key, prof = S.apply_segmentation(LINES, hf, pf, CLEAN_MAP, tags_for=tf)
    eq(len(blind), 3, "blind 문항수")
    eq(len(key), 3, "key 문항수")
    eq([b["idx"] for b in blind], [0, 1, 2], "blind idx 0..2")
    eq([k["idx"] for k in key], [0, 1, 2], "key idx 0..2")
    ok(all(("answer" not in b and "expl_raw" not in b) for b in blind),
       "블라인드 불변식: blind 에 answer/expl_raw 키 0")
    eq(prof["provenance"], "llm-segment", "provenance")

    # ── 2) stem/options 분리 + 정답값 추출 ──────────────────────────────────
    eq(blind[0]["stem"], "1. 행정의 정의로 옳은 것은?", "q1 stem")
    eq(len(blind[0]["options"]), 5, "q1 run-on 선지 5개 분리")
    eq(len(blind[1]["options"]), 5, "q2 선지 5개")
    eq(blind[2]["options"], [], "q3 주관식 선지 0")
    eq(key[0]["answer"], "1", "q1 정답값(ANS_RE)")
    eq(key[1]["answer"], "2", "q2 정답값")
    ok("능률" in (key[2]["answer"] or ""), "q3 주관식 정답 텍스트 보존")
    ok("사익" in key[0]["expl_raw"], "q1 해설 봉인")
    eq(blind[0].get("bucket"), "", "tags_for bucket: 태그 전부 빈값이면 빈 문자열")

    # 정답/해설이 blind 어디에도 verbatim 없어야(누출 0)
    hay0 = blind[0]["stem"] + " ".join(blind[0]["options"])
    ok("사익" not in hay0, "q1 해설어가 blind 로 새지 않음")

    # ── 3) verify: 클린 맵 통과 ─────────────────────────────────────────────
    prob, leaks = S.verify_segmentation(LINES, CLEAN_MAP, blind, key)
    eq(prob, [], "클린 맵 구조결함 0")
    eq(leaks, [], "클린 맵 누출 0")

    # ── 3a) overlap(파티션 위반): 라인 4(해설)를 stem 에도 배정 ──────────────
    ov = {"questions": [dict(CLEAN_MAP["questions"][0], stem_lines=[1, 4])]
          + CLEAN_MAP["questions"][1:], "ignore_lines": [0]}
    b2, k2, _ = S.apply_segmentation(LINES, hf, pf, ov, tags_for=tf)
    p2, l2 = S.verify_segmentation(LINES, ov, b2, k2)
    ok(any(x["kind"] == "overlap" for x in p2), "overlap 검출(라인 중복할당)")
    ok(0 in l2, "overlap 이 누출(idx0)로도 잡힘")

    # ── 3b) bleed 누출(중복 없이): 해설 라인을 stem 에만 넣고 explanation 비움 ─
    bl = {"questions": [{"qid": 1, "stem_lines": [1, 4], "option_lines": [2],
                         "answer_lines": [3], "explanation_lines": []}],
          "ignore_lines": [0, 5, 6, 7, 8, 9, 10]}
    b3, k3, _ = S.apply_segmentation(LINES, hf, pf, bl, tags_for=tf)
    p3, l3 = S.verify_segmentation(LINES, bl, b3, k3)
    ok(0 in l3, "해설 마커 stem 침범 누출 검출")

    # ── 3c) range(범위밖) + coverage(미할당 본문) ───────────────────────────
    rc = {"questions": [{"qid": 1, "stem_lines": [1], "option_lines": [2],
                         "answer_lines": [99], "explanation_lines": []}],
          "ignore_lines": [0]}
    b4, k4, _ = S.apply_segmentation(LINES, hf, pf, rc, tags_for=tf)
    p4, _ = S.verify_segmentation(LINES, rc, b4, k4)
    kinds = {x["kind"] for x in p4}
    ok("range" in kinds, "range(라인ID 범위밖) 검출")
    ok("coverage" in kinds, "coverage(미할당 비어있지않은 라인) 검출")

    # 빈 라인(10)은 미할당이어도 coverage 위반 아님
    full_assign = {"questions": [{"qid": 1, "stem_lines": [1, 5, 8],
                                  "option_lines": [2, 6], "answer_lines": [3, 7, 9],
                                  "explanation_lines": [4]}],
                   "ignore_lines": [0]}
    bb, kk, _ = S.apply_segmentation(LINES, hf, pf, full_assign)
    pp, _ = S.verify_segmentation(LINES, full_assign, bb, kk)
    ok(not any(x["kind"] == "coverage" for x in pp),
       "빈 라인 미할당은 coverage 위반 아님")

    # ── 4) normalize: 문자열 정수 강제 + 누락 키 → [] ───────────────────────
    norm = S.normalize_segmentation_map(
        {"questions": [{"qid": "1", "stem_lines": ["1", 2], "option_lines": None}],
         "ignore_lines": ["0", "x", 3]})
    eq(norm["questions"][0]["stem_lines"], [1, 2], "문자열 정수 강제")
    eq(norm["questions"][0]["option_lines"], [], "누락/None 키 → []")
    eq(norm["questions"][0]["answer_lines"], [], "answer_lines 기본 []")
    eq(norm["ignore_lines"], [0, 3], "ignore_lines 비정수 'x' 제외")

    # ── 5) 결정성 ───────────────────────────────────────────────────────────
    b_a, k_a, _ = S.apply_segmentation(LINES, hf, pf, CLEAN_MAP, tags_for=tf)
    b_b, k_b, _ = S.apply_segmentation(LINES, hf, pf, CLEAN_MAP, tags_for=tf)
    eq(b_a, b_b, "apply 결정성(blind)")
    eq(k_a, k_b, "apply 결정성(key)")


if __name__ == "__main__":
    run()
    total = PASS[0] + FAIL[0]
    print(f"test_llm_segment: {PASS[0]}/{total} passed")
    sys.exit(1 if FAIL[0] else 0)

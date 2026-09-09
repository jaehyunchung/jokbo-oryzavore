# -*- coding: utf-8 -*-
"""
llm_segment.py — Phase 2 포맷추론 에스컬레이션의 '코드 절단' 레이어(결정론·stdlib·무-API).

배경
----
결정론 분절기(`extract.split_blind_key`)와 Phase1 `format_probe`(--auto-format)는 답 마커나
'반복 답·해설 블록 구분자'에 의존한다. 규칙적 구분자가 없는 freeform 합본 기출(학생 인라인
코멘트형)에서는 둘 다 폴백→오염(해설 침범·유령 문항)을 낸다. 이 한계는 '어디가 stem이고
어디가 해설/정답인지'가 빈도/위치가 아니라 의미 판단이라 결정론으로는 천장이 있다.

설계(블라인드 불변식 강화)
-------------------------
'정답을 본 역할(LLM Segmenter 서브에이전트)'은 **라인ID→역할 라벨(포인터)만** 내보낸다.
실제 절단(blind/key 분리)은 이 모듈이 **원본 라인으로** 한다 — LLM은 텍스트를 한 글자도
재작성하지 않으므로(라운드트립 자동 보장) 답 내용을 stem으로 '섞을' 방법이 없다. 블라인드는
분절기가 regex냐 LLM이냐가 아니라 *정답을 본 역할의 출력을 Solver가 소비하느냐*로 결정되며,
포인터만 받는 이 구조에서는 Solver가 소비하는 blind에 답이 물리적으로 들어가지 않는다.

포인터맵 스키마(어떤 과목/이름/문구도 하드코딩 0)
  {
    "questions": [
      {"qid": 1, "stem_lines": [int], "option_lines": [int],
       "answer_lines": [int], "explanation_lines": [int]}, ...
    ],
    "ignore_lines": [int]      # 러닝헤더/표지/잡음(분절 제외)
  }

`extract`의 순수 헬퍼(clean_stem/split_stem_options/compose_bucket/ANS_RE)와 `parse_warnings`,
`nospoiler_audit`의 토큰화를 재사용한다. 순환 임포트 방지를 위해 extract는 이 모듈을 main()
안에서 지연 임포트한다.
"""
from __future__ import annotations

import json

from extract import (  # noqa: E402  (extract 는 본 모듈을 지연 임포트하므로 순환 아님)
    ANS_RE, clean_stem, split_stem_options, compose_bucket,
)
from parse_warnings import _EXPLANATION_BLEED_RE  # noqa: E402  (해설/정답 마커 단일 진실)
from nospoiler_audit import _core, _tokens        # noqa: E402  (누출 토큰화 재사용)

_ROLE_KEYS = ("stem_lines", "option_lines", "answer_lines", "explanation_lines")


# ─────────────────────────────────────────────────────────────────────────────
# 포인터맵 로드 + 정규화
# ─────────────────────────────────────────────────────────────────────────────
def load_segmentation_map(path):
    """segmentation.json 을 읽어 정규화된 맵을 반환. JSON 으로만 읽는다(코드 실행 0)."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return normalize_segmentation_map(raw)


def normalize_segmentation_map(raw):
    """LLM 산출 맵을 관대하게 정규화 — 누락 키는 빈 리스트, 정수만 통과."""
    def _ints(seq):
        out = []
        for v in seq or []:
            if isinstance(v, bool):
                continue
            if isinstance(v, int):
                out.append(v)
            elif isinstance(v, str) and v.strip().lstrip("-").isdigit():
                out.append(int(v))
        return out

    questions = []
    for q in (raw.get("questions") if isinstance(raw, dict) else None) or []:
        if not isinstance(q, dict):
            continue
        questions.append({
            "qid": q.get("qid"),
            "stem_lines": _ints(q.get("stem_lines")),
            "option_lines": _ints(q.get("option_lines")),
            "answer_lines": _ints(q.get("answer_lines")),
            "explanation_lines": _ints(q.get("explanation_lines")),
        })
    ignore = _ints(raw.get("ignore_lines")) if isinstance(raw, dict) else []
    return {"questions": questions, "ignore_lines": ignore}


# ─────────────────────────────────────────────────────────────────────────────
# 코드 절단 — 포인터맵 → (blind, key). split_blind_key 와 동일 출력 계약.
# ─────────────────────────────────────────────────────────────────────────────
def _line_offsets(lines):
    """라인 인덱스 → full 내 절대 문자 오프셋('\\n' 1자 포함, full = '\\n'.join(lines) 가정)."""
    offs, c = [], 0
    for ln in lines:
        offs.append(c)
        c += len(ln) + 1
    return offs


def _join(lines, ids):
    n = len(lines)
    return "\n".join(lines[i] for i in ids if isinstance(i, int) and 0 <= i < n)


def apply_segmentation(lines, header_for, page_for, smap, tags_for=None):
    """포인터맵으로 full(=lines)을 분절해 (blind, key, profile) 반환.

    blind: 풀이용 — stem/options 만(answer/expl_raw 키 절대 없음 = 블라인드 불변식).
    key:   봉인 — idx + 원본 답 + 원본 해설. 두 리스트는 idx 1:1.
    stem/options 경계는 검증된 split_stem_options 로 정제하되, '답·해설 라인'은 포인터가
    이미 제외했으므로 blind 엔 정답이 물리적으로 들어가지 않는다.
    """
    offs = _line_offsets(lines)
    blind, key = [], []
    for k, q in enumerate(smap.get("questions", [])):
        stem_ids = q.get("stem_lines") or []
        opt_ids = q.get("option_lines") or []
        ans_ids = q.get("answer_lines") or []
        exp_ids = q.get("explanation_lines") or []

        body_ids = [i for i in (stem_ids + opt_ids) if isinstance(i, int)]
        first = min(body_ids) if body_ids else (min(
            [i for grp in (ans_ids, exp_ids) for i in grp if isinstance(i, int)] or [0]))
        abs_start = offs[first] if 0 <= first < len(offs) else 0

        combined = clean_stem("\n".join(p for p in (_join(lines, stem_ids),
                                                    _join(lines, opt_ids)) if p).strip())
        stem, options = split_stem_options(combined)

        y, dp, sc = header_for(abs_start)
        rec = {"idx": k, "page": page_for(abs_start), "year": y, "dept_prof": dp,
               "scope": sc, "stem": stem, "options": options,
               "stem_raw": combined[-450:].strip()}
        if tags_for is not None:
            ty, tc, tp = tags_for(abs_start)
            rec["category"] = tc
            rec["prof"] = tp
            rec["bucket"] = compose_bucket(ty or y, tc, tp)
        blind.append(rec)

        ans_text = _join(lines, ans_ids)
        am = ANS_RE.search(ans_text)
        answer = am.group(1) if am else (ans_text.strip() or None)
        expl = _join(lines, exp_ids).strip()
        key.append({"idx": k, "answer": answer, "expl_raw": expl[:500]})

    profile = {"provenance": "llm-segment", "questions": len(blind),
               "ignored_lines": len(smap.get("ignore_lines") or [])}
    return blind, key, profile


# ─────────────────────────────────────────────────────────────────────────────
# 검증 게이트 — LLM 출력을 신뢰하지 않고 기계적으로 증명한다.
# ─────────────────────────────────────────────────────────────────────────────
def verify_segmentation(lines, smap, blind, key):
    """포인터맵 적용 결과를 검증. 반환: (structural_problems, leak_indices).

    structural_problems: 라인ID 범위·중복할당(파티션)·미할당 본문·블라인드 불변식 위반.
    leak_indices: 봉인 정답/해설이 blind stem/options 로 샜다고 의심되는 idx 목록.
    둘 다 비어야 정상 — 비면 호출부가 SEGMENTATION_INVALID/LEAK(blocker)로 체크포인트를 막는다.
    """
    problems = []
    n = len(lines)
    seen = {}

    def _claim(ids, where):
        for i in ids:
            if not isinstance(i, int) or i < 0 or i >= n:
                problems.append({"kind": "range", "where": where, "line": i})
            elif i in seen:
                problems.append({"kind": "overlap", "where": where, "line": i,
                                 "other": seen[i]})
            else:
                seen[i] = where

    for qi, q in enumerate(smap.get("questions", [])):
        for rk in _ROLE_KEYS:
            _claim(q.get(rk) or [], f"{rk}#{qi}")
    _claim(smap.get("ignore_lines") or [], "ignore")

    unassigned = [i for i in range(n) if i not in seen and lines[i].strip()]
    if unassigned:
        problems.append({"kind": "coverage", "count": len(unassigned),
                         "sample": unassigned[:10]})

    # 블라인드 불변식: blind 레코드엔 answer/expl_raw 키가 절대 없어야 한다.
    for b in blind:
        if "answer" in b or "expl_raw" in b:
            problems.append({"kind": "invariant", "idx": b.get("idx")})

    # 누출: ⓪ '원본 라인' 수준 선제 검사 — stem/option 으로 라벨된 라인에 정답 마커(ANS_RE)나
    #        해설/정답 표기가 있으면 그 자체로 누출이다. 이걸 정제(clean_stem) 이후에만 검사하면
    #        clean_stem 이 '답:' 마커를 절단하면서 값('③')만 blind 에 남겨 증거가 사라진다 —
    #        LLM 이 정답 라인을 stem/option 으로 오라벨해도 '✓ 검증통과'가 뜨는 구멍(블라인드
    #        불변식 위반). 원본 라인에서 잡아야 fail-closed 게이트가 된다(오탐은 Segmenter 가
    #        재라벨해 재시도 — 유한 재시도, INSTRUCTIONS Step 3.5).
    leaks = []
    for qi, q in enumerate(smap.get("questions", [])):
        for i in (q.get("stem_lines") or []) + (q.get("option_lines") or []):
            if isinstance(i, int) and 0 <= i < n and (
                    ANS_RE.search(lines[i]) or _EXPLANATION_BLEED_RE.search(lines[i])):
                leaks.append(qi)
                break

    # 누출: ① blind(stem+options)에 해설/정답 마커가 남았거나(라인 오라벨), ② 봉인 해설의
    #        핵심어가 같은 문항 blind 로 대량 겹치면 해설이 새어든 것.
    for b, kk in zip(blind, key):
        idx = b.get("idx")
        stem = b.get("stem") or ""
        hay = stem + " " + " ".join(b.get("options") or [])
        if _EXPLANATION_BLEED_RE.search(hay):
            leaks.append(idx)
            continue
        etoks = set(_tokens(_core(kk.get("expl_raw") or "")))
        if etoks:
            inter = etoks & set(_tokens(hay))
            if len(inter) >= 3 and len(inter) >= 0.5 * len(etoks):
                leaks.append(idx)

    return problems, sorted({i for i in leaks if i is not None})

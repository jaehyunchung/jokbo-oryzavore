# -*- coding: utf-8 -*-
"""
왕족 변형 병합 → R형 초안 생성 (authoring 보조 도구).

같은 개념을 여러 해에 걸쳐 '오답 선지(distractor) 풀을 바꿔가며' 출제한 왕족 변형들을, 모든
선지를 합쳐 하나의 R형 문항으로 만든다. (기본 규칙은 '변형은 분리' — 이 도구는 대안으로
'여러 해의 distractor 를 다 모은 R형 1문항'을 만들고 싶을 때 쓴다.)

★ 병합 게이트(기존 규칙 유지): **제시문이 비슷하고 '정답이 같을' 때만 병합**한다. 정답이 다르면
  병합하지 않고(None) '별도 분리' 안내를 돌려준다. 정답이 같으므로 union 의 목적은 distractor 통합 →
  **결과는 보통 단일정답 R형**(공통 정답 1 + 누적 distractor > 5선지). R형 ≠ 복수정답.
  (원본이 복수정답이고 그 정답집합이 동일하면 결과도 복수정답.)

핵심 표시(사용자 요구):
  · flags 에 MERGED_RTYPE  → "왕족 변형을 병합해 만든 R형"(합성 문항)임을 명시.
  · flags 에 ORIG_RTYPE / ORIG_SINGLE → 병합 전 '원래 문항'이 R형(>5선지)이었는지 아닌지 표시.
  · 왕족 병합이므로 new_expl 선두에 【왕족】 태그(양쪽에서 왕족 배지).

처리:
  · 선지: 마커 제거·공백 정규화 텍스트로 중복 제거 후 ①..⑳ 재번호(R형).
  · 정답: 변형 공통 정답을 '텍스트'로 추적 → 새 마커로 매핑. 1개면 verified 만(단일정답 R형), 2개↑면 answers.
  · years: 모든 변형 years 합집합. meta: 대표(주어진 것 or 첫 변형).

⚠ 검수 필수(날조 금지): union 된 distractor 가 모두 '실제 오답'으로 타당한지, 정답이 일관된지 사람이 확인.
  자동 생성 결과는 '초안'일 뿐이다.

사용:
  from merge_rtype import merge_to_rtype, format_py
  draft, msgs = merge_to_rtype([v1, v2, v3])   # 정답 같을 때만 병합(아니면 draft=None)
  print(format_py(draft, msgs))
"""
import json
import re

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_MARK = re.compile(r'^\s*([①-⑳])\s*')


def _marker(s):
    m = _MARK.match(str(s)); return m.group(1) if m else None


def _text(opt):
    return _MARK.sub('', str(opt)).strip()


def _norm(t):
    return re.sub(r'\s+', ' ', str(t)).strip().rstrip('.。·,')


def _correct_markers(q):
    """문항의 정답 마커 리스트. answers(복수정답) 우선, 없으면 verified 선두 마커."""
    a = q.get('answers')
    if isinstance(a, list) and a:
        out = []
        for x in a:
            mk = _marker(x)
            if mk:
                out.append(mk)
            else:
                n = re.sub(r'\D', '', str(x))
                if n.isdigit() and 1 <= int(n) <= len(CIRCLED):
                    out.append(CIRCLED[int(n) - 1])
        return out
    mk = _marker(q.get('verified', ''))
    return [mk] if mk else []


def _vtype(q):
    """원본 변형의 유형 라벨."""
    nopt = len(q.get('options') or [])
    nc = len(_correct_markers(q))
    if nopt > 5 or nc > 1:
        return "R형(복수정답)" if nc > 1 else "R형(단일정답)"
    return "A형(단일정답)"


def _is_rtype(q):
    return (len(q.get('options') or []) > 5) or (len(_correct_markers(q)) > 1)


def merge_to_rtype(variants, stem=None, meta=None):
    """변형 문항 리스트 → 병합 R형 초안 dict + 메시지 리스트.

    병합 게이트(기존 규칙 유지): **제시문이 비슷하고 '정답이 같을' 때만 병합**한다.
    변형마다 정답이 다르면 병합하지 않고(None) '별도 분리' 안내를 돌려준다.
    정답이 같으므로 R형 union 의 목적은 '여러 해의 서로 다른 오답 선지 풀을 합치는 것' →
    결과는 보통 **단일정답 R형**(공통 정답 1 + 누적 distractor > 5선지). 원본이 복수정답이고
    그 정답 집합이 동일하면 결과도 복수정답이 된다.
    """
    msgs = []
    union = []          # [(norm, display_text)]  등장 순서 보존
    seen = {}           # norm -> 새 인덱스
    provenance = []     # (year, vtype, orig_verified)

    # 1) 각 변형의 정답 텍스트 집합(normalized) — 병합 가능 여부 판정용
    corr_sets = []
    for v in variants:
        mk2norm = {_marker(o): _norm(_text(o)) for o in (v.get('options') or []) if _marker(o)}
        cs = set()
        for cmk in _correct_markers(v):
            if cmk in mk2norm:
                cs.add(mk2norm[cmk])
            else:
                msgs.append("정답 마커 %s 를 변형 선지에서 못 찾음 (meta=%s)" % (cmk, v.get('meta', '')))
        corr_sets.append(cs)
        yr = re.search(r'(19|20)\d{2}', v.get('meta', ''))
        provenance.append((yr.group(0) if yr else '?', _vtype(v), v.get('verified', '')))

    # 2) 게이트: 모든 변형의 정답 집합이 동일해야 병합(제시문 비슷+정답 같을 때만 — 기존 규칙 유지)
    base = corr_sets[0] if corr_sets else set()
    if not base or any(cs != base for cs in corr_sets):
        out = ["✗ 병합 불가 — '제시문 비슷 + 정답 같음'일 때만 병합한다(기존 규칙). 정답이 변형마다 다르면 별도 dict 로 분리하세요."]
        for v, cs in zip(variants, corr_sets):
            out.append("   %s 정답: %s" % (v.get('meta', ''), ", ".join(sorted(cs)) or "(미상)"))
        return None, out + msgs

    # 3) 선지 union(정규화 텍스트로 중복 제거) + 재번호
    for v in variants:
        for o in (v.get('options') or []):
            nm = _norm(_text(o))
            if nm and nm not in seen:
                seen[nm] = len(union); union.append((nm, _text(o)))
    if len(union) > len(CIRCLED):
        msgs.append("선지 %d개 — 마커 %d개 초과. 직접 정리 필요." % (len(union), len(CIRCLED)))

    new_opts = ["%s %s" % (CIRCLED[i], txt) for i, (_nm, txt) in enumerate(union)]
    # 공통 정답(base)을 새 마커로 — 보통 1개(단일정답 R형). 동일 정답집합이 복수면 복수정답 유지.
    correct_idx = sorted(seen[nm] for nm in base if nm in seen)
    correct_markers = [CIRCLED[i] for i in correct_idx]
    verified_str = ", ".join("%s %s" % (CIRCLED[i], union[i][1]) for i in correct_idx)
    multi = len(correct_markers) >= 2
    if len(union) <= 5:
        msgs.append("union 선지 %d개(≤5) — 변형 distractor 가 거의 같아 R형이 아닐 수 있음(병합 실익 적음)." % len(union))

    years = []
    for v in variants:
        for y in (v.get('years') or []):
            if str(y) not in years:
                years.append(str(y))
    if years and all(y.isdigit() for y in years):
        years = sorted(set(years), key=lambda y: -int(y))

    flags = ["MERGED_RTYPE", "ORIG_RTYPE" if any(_is_rtype(v) for v in variants) else "ORIG_SINGLE"]
    draft = {
        "meta": meta or (variants[0].get('meta', '') if variants else ''),
        "flags": flags,
        "years": years,
        "stem": stem or (variants[0].get('stem', '') if variants else ''),
        "options": new_opts,
        "verified": verified_str,
        "new_expl": "【왕족】 [병합 R형 초안] 정답 근거와 각 오답 선지의 오답 이유를 채우세요(검수 필수).",
    }
    if multi:                       # 단일정답이면 answers 생략(verified 만) — R형≠복수정답
        draft["answers"] = correct_markers
    draft["_merge_provenance"] = provenance   # 사람 검토용. format_py 가 주석으로 출력.
    return draft, msgs


def format_py(draft, msgs=None):
    """초안을 붙여넣기 좋은 Python 리터럴 문자열로. 출처/경고는 주석으로.
    병합 거부(draft=None)면 안내 메시지만 출력."""
    if draft is None:
        return "\n".join(msgs or [])
    d = dict(draft)
    prov = d.pop("_merge_provenance", [])
    multi = isinstance(d.get("answers"), list) and len(d["answers"]) >= 2
    lines = ["# ── 병합 R형 초안 (검수 필수: 정답 근거·오답 이유 채우고 의학 검증) ──",
             "# 유형: %s R형 · union 선지 %d개" % ("복수정답" if multi else "단일정답", len(d.get("options", [])))]
    if prov:
        lines.append("# 원본 변형(왕족 병합 — 정답 동일):")
        for yr, vt, ver in prov:
            lines.append("#   · %s · %s · 원정답 '%s'" % (yr, vt, ver))
    for w in (msgs or []):
        lines.append("# ⚠ " + w)
    body = json.dumps(d, ensure_ascii=False, indent=2)   # str/list 만이라 Python 리터럴로도 유효
    return "\n".join(lines) + "\n" + body


if __name__ == '__main__':
    # 데모 ①: 같은 개념·'같은 정답'을 선지 풀(distractor)만 바꿔 낸 변형 → 단일정답 R형
    v1 = {"meta": "2019 · 김철수", "years": ["2019"],
          "stem": "자궁근종 환자에서 적절한 처치를 고르시오.",
          "options": ["① 경과관찰", "② 전자궁절제술", "③ GnRH agonist", "④ 근종절제술", "⑤ 자궁동맥색전술"],
          "verified": "③ GnRH agonist"}
    v2 = {"meta": "2021 · 이영희", "years": ["2021"],
          "stem": "자궁근종의 약물 치료로 옳은 것은?",
          "options": ["① GnRH agonist", "② 고강도초음파", "③ 경과관찰", "④ 호르몬요법", "⑤ 미페프리스톤"],
          "verified": "① GnRH agonist"}
    print("=== 데모 ① 정답 동일(GnRH agonist) → 단일정답 R형 ===")
    draft, msgs = merge_to_rtype([v1, v2], stem="자궁근종의 약물 치료로 옳은 것은?")
    print(format_py(draft, msgs))

    # 데모 ②: 정답이 다른 변형 → 병합 거부(별도 분리 안내)
    v3 = {"meta": "2018 · 홍길동", "years": ["2018"],
          "stem": "자궁근종의 치료로 옳은 것은?",
          "options": ["① 경과관찰", "② 전자궁절제술", "③ GnRH agonist"],
          "verified": "② 전자궁절제술"}   # v1 과 정답 다름
    print("\n=== 데모 ② 정답 불일치 → 병합 거부 ===")
    draft2, msgs2 = merge_to_rtype([v1, v3])
    print(format_py(draft2, msgs2))

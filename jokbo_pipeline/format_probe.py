# -*- coding: utf-8 -*-
"""
format_probe.py — Phase 1 제네릭 포맷 추론(결정론·stdlib·무-API).

배경
----
기본 분절기 `extract.split_blind_key` 는 답 마커(ANS_RE)로 문항을 쪼갠다. 이는
'문항당 답 줄이 따로 있고, 문항 사이에 해설이 끼지 않는' 깔끔한 기출에선 잘 돈다.
그러나 현실의 일부 기출은 각 문항 뒤에 **인라인 답·해설 블록**(예: 어떤 반복 구분자
다음에 '답:X 해설:…')을 두고, 문항 사이에 **반복 러닝헤더**(출제자 표기+강의 제목)가
박혀 있다. 이런 입력을 답 마커로 선형 분절하면 (a) 직전 해설이 다음 stem 앞에 새고
(b) 해설 속 '답:' 오탐으로 유령 문항이 생기며 (c) 선지가 합쳐진다.

이 모듈은 **그 구조를 입력에서 도출**해(어떤 과목/이름/제목/문구도 하드코딩하지 않음)
답·해설 블록을 분절 경계로 삼는다. 핵심은 'redaction-before-segment' — 답·해설을
분절 전에 떼어내므로, 분절기는 답을 보지 않고(블라인드 안전) 해설 오염도 구조적으로
사라진다.

도출 신호(전부 빈도·위치 기반, 선언 0)
  · 답-블록 구분자  : 답 마커 바로 앞에 반복 등장하는 짧은 문자열(빈도 ≈ 문항수).
  · 질문 시작(QS)   : 출제자 경칭(교수/강사/선생 '님') 러닝헤더 — 단, 뒤에 한국어 조사가
                      오는 산문 언급('… 교수님께서')은 제외해 본문 오인을 막는다.
  · 러닝헤더 제목   : QS 접두를 떼고 남은 stem 들의 공통 선두 부분문자열(여러 문항 공유).
  · 컬럼 수         : 단어 x0 분포로 1단/2단(2단 강신호일 때만). 텍스트 추출 순서 교정용.

`extract` 의 순수 헬퍼(ANS_RE/clean_stem/split_stem_options/compose_bucket)를 재사용한다.
순환 임포트 방지를 위해 extract 는 이 모듈을 main() 안에서 지연 임포트한다.
"""
import re
from collections import Counter

from extract import (  # noqa: E402  (extract 는 본 모듈을 지연 임포트하므로 순환 아님)
    ANS_RE, TEACHER, clean_stem, split_stem_options, compose_bucket,
)

# 질문 시작(러닝헤더) — 출제자 경칭형. 뒤에 한국어 조사가 붙는 산문 언급은 제외(부정형 lookahead).
# 어떤 이름/제목도 박지 않는다 — TEACHER(교수|출제자|강사|선생)만 일반화 앵커로 쓴다.
QS_HEADER_RE = re.compile(
    r'(?:주관식\s*\d*\s*)?(?:\d{1,3}\s*)?'      # 선택적 '주관식 N'·페이지/문항 번호
    r'[가-힣]{2,4}\s*' + TEACHER + r'님'         # 출제자 + 경칭
    r'(?![께은는이가도만을를의에과와로])'         # 산문 조사가 뒤따르면 헤더 아님(본문 언급 제외)
)


def detect_columns(words, page_width, gutter=(0.45, 0.55), max_gutter_share=0.06,
                   min_side_share=0.25, min_words=20):
    """단어 x0 분포로 1단/2단 추정. 2단 '강신호'일 때만 2 반환(보수적 — 오검출 시 단일 컬럼 유지).

    words: [{'x0': float}, …] (pdfplumber extract_words 결과). page_width: 페이지 폭(pt).
    2단 = 중앙 거터가 거의 비고(<max_gutter_share) 좌·우 양쪽에 상당 비율(≥min_side_share).
    """
    if not words or not page_width:
        return 1
    xs = [w['x0'] for w in words if 'x0' in w]
    if len(xs) < min_words:
        return 1
    lo, hi = gutter[0] * page_width, gutter[1] * page_width
    n = len(xs)
    in_gutter = sum(1 for x in xs if lo <= x <= hi)
    left = sum(1 for x in xs if x < lo)
    right = sum(1 for x in xs if x > hi)
    if (in_gutter <= max_gutter_share * n
            and left >= min_side_share * n and right >= min_side_share * n):
        return 2
    return 1


def derive_answer_delimiter(text, ans_re=ANS_RE, min_share=0.5, win=24,
                            min_len=3, max_len=20, min_marks=3):
    """답 마커 바로 앞에 반복 등장하는 '답·해설 블록 구분자'를 빈도로 도출. 없으면 None.

    각 답 마커 앞 win자 윈도의 '가장 긴 빈출 접미사'를 찾는다 — 마커 다수가 동일 문자열로
    선행되면(빈도 ≥ min_share) 그게 블록 구분자다. 어떤 문구도 하드코딩하지 않는다.
    """
    marks = list(ans_re.finditer(text or ''))
    n = len(marks)
    if n < min_marks:
        return None
    wins = [re.sub(r'\s+', ' ', text[max(0, m.start() - win):m.start()]).strip()
            for m in marks]
    threshold = max(3, min_share * n)
    for L in range(max_len, min_len - 1, -1):
        c = Counter(w[-L:] for w in wins if len(w) >= L)
        if not c:
            continue
        cand, cnt = c.most_common(1)[0]
        cand = cand.strip()
        if cnt >= threshold and len(cand) >= min_len:
            return cand            # 가장 긴 빈출 접미 우선
    return None


def _qs_strip(stem):
    """stem 선두의 러닝헤더(출제자 경칭) 접두를 제거."""
    s = stem.lstrip()
    m = QS_HEADER_RE.match(s)
    return s[m.end():] if m else s


def derive_titles(stems_after_qs, min_count=3, min_len=4, max_len=40, fanout=0.5):
    """QS 접두를 뗀 stem 들의 공통 선두(=러닝헤더 '강의 제목')를 빈도 급락 지점까지 도출.

    제목 경계 찾기의 본질: 공통 접두를 한 글자씩 늘리면 빈도가 비단조 감소하는데, 제목이
    끝나고 stem(문항별로 다름)이 시작되는 지점에서 빈도가 '갈라진다(fan-out)'. 그래서
    각 시작 군집에서 '다음 글자 최빈 확장이 군집의 fanout 비율 이상을 유지하는 동안만' 확장하고,
    갈라지면 멈춘다 → 제목+공통 stem-도입부를 stem 으로 오인해 깎는 일을 피한다.
    min_count: 제목으로 인정할 최소 공유 문항수(저빈도 우연 공유 접두 배제).
    문장부호로 끝나는 후보는 stem 본문일 수 있어 제외.
    """
    titles = []
    starts = Counter(s[:min_len] for s in stems_after_qs if len(s) >= min_len)
    for start, c0 in starts.items():
        if c0 < min_count:
            continue
        group = [s for s in stems_after_qs if s.startswith(start)]
        P = start
        while len(P) < max_len:
            ext = Counter(s[:len(P) + 1] for s in group if len(s) > len(P))
            if not ext:
                break
            best, bc = ext.most_common(1)[0]
            if bc >= max(min_count, fanout * len(group)):   # 아직 안 갈라짐 → 확장
                P = best
                group = [s for s in group if s.startswith(P)]
            else:
                break                                       # fan-out = 제목 경계
        P = P.rstrip()
        if len(P) >= min_len and P[-1:] not in '?.!':
            titles.append(P)
    return sorted(set(titles), key=len, reverse=True)[:8]   # 긴 제목 우선 strip


def _strip_title(stem, titles):
    for t in titles:
        if stem.startswith(t):
            return stem[len(t):].strip()
    return stem


def auto_segment(full, header_for, page_for, tags_for=None, delimiter=None):
    """답-블록 구분자 기반 분절 → (blind, key). split_blind_key 와 동일 출력 계약.

    delimiter 를 경계로 full 을 쪼개고, 각 블록에서 답값+해설을 봉인(key)하며 다음 문항
    stem 만 분절(blind)한다. blind 에는 answer/expl_raw 키가 없어야 한다(블라인드 불변식).
    delimiter 가 없으면 (None) 빈 결과 — 호출부가 split_blind_key 로 폴백한다.
    """
    blind, key = [], []
    if not delimiter:
        return blind, key, {}
    dm = list(re.finditer(re.escape(delimiter), full))
    if not dm:
        return blind, key, {}

    # (절대오프셋, stem원문, 흡수의심 QS수) 와 (답값, 해설) 을 1:1로 모은다.
    raw_stems = []   # (abs_start, stem_text, n_qs_in_body)
    raws_ans = []    # (answer, expl)

    p0 = full[:dm[0].start()]
    qs0 = list(QS_HEADER_RE.finditer(p0))
    if qs0:
        raw_stems.append((qs0[-1].start(), p0[qs0[-1].start():], 1))
    else:
        raw_stems.append((0, p0, 0))

    for i, m in enumerate(dm):
        b_start = m.end()
        b_end = dm[i + 1].start() if i + 1 < len(dm) else len(full)
        body = full[b_start:b_end]
        am = ANS_RE.search(body)
        ans = am.group(1) if am else None
        after = am.end() if am else 0
        qs_in_body = list(QS_HEADER_RE.finditer(body, after))
        q = qs_in_body[0] if qs_in_body else None
        if q:
            raws_ans.append((ans, body[after:q.start()].strip()))
            raw_stems.append((b_start + q.start(), body[q.start():], len(qs_in_body)))
        else:
            raws_ans.append((ans, body[after:].strip()))

    # 제목 boilerplate 도출(QS 접두 제거 후 공통 선두). min_count 는 문항수에 비례(최소 3).
    after_qs = [_qs_strip(s) for _, s, _ in raw_stems]
    titles = derive_titles(after_qs, min_count=max(3, len(after_qs) // 10))

    for k, ((abs_start, _orig, n_qs), aq) in enumerate(zip(raw_stems, after_qs)):
        stem, options = split_stem_options(clean_stem(_strip_title(aq, titles)))
        y, dp, sc = header_for(abs_start)
        rec = {'idx': k, 'page': page_for(abs_start), 'year': y, 'dept_prof': dp,
               'scope': sc, 'stem': stem, 'options': options,
               'stem_raw': _orig[-450:].strip()}
        if n_qs >= 2:        # 한 블록에 질문 헤더가 2개 이상 = 구분자 없는 문항 흡수 의심
            rec['absorbed_qnums'] = n_qs
        if tags_for is not None:
            ty, tc, tp = tags_for(abs_start)
            rec['category'] = tc
            rec['prof'] = tp
            rec['bucket'] = compose_bucket(ty or y, tc, tp)
        blind.append(rec)
        ans, expl = raws_ans[k] if k < len(raws_ans) else (None, '')
        key.append({'idx': k, 'answer': ans, 'expl_raw': (expl or '')[:500]})

    return blind, key, {'delimiter': delimiter, 'titles': titles}

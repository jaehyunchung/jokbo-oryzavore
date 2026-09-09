# -*- coding: utf-8 -*-
r"""
족보 PDF 구조 추출기 (과목 무관) — jokbo-oryzavore v2.

사용:
  python3 jokbo_pipeline/extract.py --pdf "<과목>_족보.pdf" --work output/
      [--header-regex r'\[(\d{4})\s+([^\]]+?)\]\s*([^\n0-9\[]{0,35})']

산출:
  output/structure.json     헤더 블록 + 페이지별 이미지 정보
  output/all_questions.json 블라인드 문항(stem/options 만 — 원본 답·해설 없음). 풀이는 이 파일로 한다.
  output/answer_key.json    봉인 정답키(idx + 원본 답 + 원본 해설). '풀고 나서' 비교 단계에서만 연다.
  output/images/            PDF에 임베드된 이미지 전부(pNN_xxx.jpg)

블라인드 기본 경로: 원본 정답을 all_questions.json 에 넣지 않고 answer_key.json 으로 분리한다.
에이전트가 푸는 단계에서 보는 파일에 정답이 물리적으로 없으므로, 블라인드가 '기본 경로'가 된다
(파일시스템 접근 자체를 막진 못하니 완전 강제는 아니나, 앵커링을 구조적으로 줄인다).

v2 파싱 개선(외부 파싱 개선 보고서 반영):
  #1 지문/선지 분리   : split_stem_options() — stem 과 options[] 를 분리해 통짜 텍스트 방지.
  #2 해설 침범 제거   : clean_stem() — '답:'/'해설:' 뒤 새 문제번호부터를 stem 으로(앞 잔여물 절단).
  #3 연도·분류·교수   : parse_categories() — [2025년]·<소화기>·교수명을 동시 추적해 bucket 합성.
  #4 이미지 BBox 매핑 : extract_image_geometry()+assign_candidate_images() — y좌표로 문항별 후보 이미지.
  #5 선지 유실 완화   : 2~3개 선지·'1.'·'1)'·①  마커 모두 인식.
  #6 병합문항 Unmerging: unmerge_glued() — 'N장영실 교수님' 처럼 들러붙은 문항을 강제로 쪼갬.

주의: 족보마다 형식이 다르다. 먼저 몇 페이지를 떠서 헤더/정답 패턴을 확인하고
      --header-regex 와 아래 ANS_RE 를 손보라. 스캔 PDF면 OCR(예: ocrmypdf)을 먼저 돌려라.
"""
import argparse, json, os, re, sys

try:
    from . import parse_warnings
except ImportError:
    import parse_warnings

# format_probe(제네릭 포맷 추론)가 import 하는 출제자 경칭 앵커(러닝헤더 검출용).
# 기존 정규식(GLUE_PROF_RE 등)은 의대 족보 튜닝 유지를 위해 그대로 두고, 이 상수만 추가한다.
TEACHER = r'(?:교수|출제자|강사|선생)'

# 정답 표기 패턴(과목 따라 수정).
# - 한국어(답/정답/딥): 콜론 생략 허용하되, 앞이 한글이면 매칭 안 함(`(?<![가-힣])`)
#   → '응답 2명'·'화답 3'처럼 단어 꼬리의 '답'을 정답마커로 오인하던 false positive 차단(감사 P0-1).
# - 영어(Answer/Ans/A): 콜론 필수 + 앞이 영문자 아닐 때만(ProfA 제외).
# - 정답 값: 숫자(복수 '1, 3')·원문자(③ / ②, ④)·영문(A~E)·O·X·미확인(?/??) 모두 인식
#   → '정답: ③'·'정답: 1, 3'·'답: A' 미인식 문제 해결(감사 P0-1).
ANS_RE = re.compile(
    r'(?:(?<![가-힣])(?:답|정답|딥)\s*[:：]?\s*'
    r'|(?<![A-Za-z])(?:Answer|Ans|A)\s*[:：]\s*)'
    r'([0-9]{1,2}(?:\s*,\s*[0-9]{1,2})*'      # 1  또는  1, 3
    r'|[①-⑳](?:\s*,\s*[①-⑳])*'                # ③  또는  ②, ④
    r'|[A-Ea-e]|[OXＯＸ]|\?\?|\?)'
)

# 기본 헤더 정규식 — [연도 교실/교수명] 범위라벨 형식
DEFAULT_HEADER_REGEX = r'\[(\d{4})\s+([^\]]+?)\]\s*([^\n0-9\[]{0,35})'

# ─── v2 파싱 보조 패턴 ─────────────────────────────────────────────────────────
CIRCLED = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳'

# #5 숫자형 선지 마커: '1.'·'2)' … (마침표/괄호 모두). 한 자리 숫자만 보고(R형 다수선지는
# 원문자 경로가 담당), 앞에 공백이 없어도(=run-on '…이다.2. S2…') 인식한다. 뒤가 숫자면 제외(소수·12 방지).
# 오탐은 '1(또는 2)부터 연속 증가'하는 시퀀스 필터(_split_by_numeric)가 막는다.
NUM_OPT_RE = re.compile(r'(\d)[.)](?![0-9])')

# #2 이전 문항 해설 잔여물 식별: '해설:'·'답:' 마커
EXPL_MARK_RE = re.compile(r'(?:해설|답|정답)\s*[:：]')
# 새 문제번호 시작(해설 뒤 등장): 줄머리/공백 뒤 'N.' 또는 'N)'
# group(1)=Q 접두('Q'/'Question', 없으면 None), group(3)=구분자('.'/')'').
# '진짜 문제 시작' 판정은 _qnum_question_match 로만 한다(접두 없는 'N)' 은 선지/열거식 해설).
QNUM_START_RE = re.compile(r'(?:^|\n)\s*(Q(?:uestion)?\s*)?(\d{1,3})\s*([.)])\s', re.IGNORECASE)


def _qnum_question_match(text):
    """text 안에서 '진짜 문제번호 시작'으로 볼 수 있는 첫 QNUM 매치를 반환(없으면 None).

    한국 기출 관례(count_question_numbers/count_qnum_starts 와 동일 규칙): 문항은 'N.' 또는
    Q 접두('Q1.'), 선지는 'N)'. 접두 없는 'N)' 을 문제 시작으로 취급하면 무번호 문항의
    '1) 2) …' 선지에서 stem 전체가 잘려 나가거나('1)' 을 새 문항으로 오인), 직전 문항의
    열거식 해설('1) 근거 …')이 다음 문항 stem 에 이어 붙는다 — 그래서 건너뛴다.
    """
    for m in QNUM_START_RE.finditer(text or ''):
        if m.group(1) or m.group(3) == '.':
            return m
    return None

# #6 병합(Unmerging): 'N장영실 교수' 처럼 번호가 앞 문항에 들러붙은 패턴(번호 앞에 개행 삽입)
GLUE_PROF_RE = re.compile(r'(?<=[가-힣0-9.)\]])(\d{1,3})([가-힣]{2,4}\s*교수)')

# #3 연도·분류·교수 태그
YEAR_TAG_RE = re.compile(r'\[((?:19|20)\d{2})\s*년?\]')   # [2025년] / [2025]
CAT_TAG_RE = re.compile(r'<([^<>\n]{1,20})>')              # <소화기>
# 교수명 추출(감사 P0-4): 본문에 흩어진 'OOO 교수에게/와' 같은 자유본문 이름이 메타데이터를 오염시키지
# 않도록 두 가지 '헤더성' 패턴만 인정한다.
#  ① 라벨형  '담당교수: 김철수'  → 콜론 뒤 이름을 잡는다('담당'을 이름으로 오인하던 버그 해결).
#  ② 경칭형  '박문수 교수님'     → 경칭 '님'이 붙은 형태만(임상지문 '교수에게/교수가'는 제외).
PROF_LABELED_RE = re.compile(r'담당\s*교수\s*[:：]\s*([가-힣]{2,4})')
PROF_HONORIFIC_RE = re.compile(r'(?<![가-힣])([가-힣]{2,4})\s*교수님')
# 구조 마커는 분류·교수가 아니다(<정답 및 해설>·'문제'/'즉시'·'담당' 등 오탐 컷). 부분일치로 제외.
CAT_STOP = ("정답", "해설", "목차", "후기", "문제", "주관식", "보기")
PROF_STOP = ("정답", "해설", "문제", "즉시", "바로", "그냥", "보기", "다음", "환자",
             "담당", "주임", "책임", "외래", "방문", "협진", "의뢰", "주치", "지도")


def count_extraction_markers(text, header_regex=DEFAULT_HEADER_REGEX):
    """추출된 PDF 전문(全文)에서 구조 마커 개수를 반환한다.

    Parameters
    ----------
    text : str
        pypdf 등으로 연결한 전체 PDF 텍스트.
    header_regex : str, optional
        헤더([연도 교실/교수명]) 패턴. 족보 형식이 다를 경우 교체.
        기본값 = DEFAULT_HEADER_REGEX.

    Returns
    -------
    dict
        {
          "header_count":        int,  # [연도 교실/교수명] 범위 헤더 수
          "answer_marker_count": int,  # 답/정답/딥 마커(문항) 수
        }

    Notes
    -----
    - 매칭 0 이 반환돼도 예외를 던지지 않는다. 호출자가 0 여부를 확인해야 한다.
    - header_count == 0 이면 --header-regex 를 재파생해야 한다는 신호다
      (추출 체크포인트 자동진행 금지 조건).
    """
    hdr_re = re.compile(header_regex)
    header_count = sum(1 for _ in hdr_re.finditer(text))
    answer_marker_count = sum(1 for _ in ANS_RE.finditer(text))
    return {"header_count": header_count, "answer_marker_count": answer_marker_count}


# ─────────────────────────────────────────────────────────────────────────────
# v2 텍스트 파싱 헬퍼 (#1 #2 #5 #6 #3) — 전부 순수함수(테스트 용이)
# ─────────────────────────────────────────────────────────────────────────────

_QNUM_LINE_RE = re.compile(r'^[ \t]*(Q(?:uestion)?\s*)?(\d{1,3})\s*([.)])\s*\S', re.IGNORECASE)
# 한 줄 안의 숫자형 선지 마커(선지 줄 판별용): 'N)'·'N.' 가 2개 이상이면 선지 줄로 본다.
_OPT_MARKER_RE = re.compile(r'(?<!\d)\d{1,2}\s*[.)]')


def count_question_numbers(text):
    """답(정답) 마커와 **독립적인** 보조 문항수 추정 — '문제번호' 시퀀스로 센다(근사·교차검증용).

    파이프라인 기본 문항수는 답 마커 수(ANS_RE)에 의존한다. 답 마커가 누락/오탐돼도 사람이
    알기 어렵다. 이 함수는 답 마커를 보지 않고 문제번호만으로 독립 추정해, 체크포인트에서
    두 신호를 대조(불일치 시 경고)할 수 있게 한다(근사 — '두 번째 의견').
    """
    qcount = 0
    run_max = 0
    for raw in text.splitlines():
        line = raw.strip()
        m = _QNUM_LINE_RE.match(line)
        if not m:
            continue
        if len(_OPT_MARKER_RE.findall(line)) >= 2:   # 'N) … M) …' = 선지 줄
            continue
        q_prefix, num, sep = m.group(1), int(m.group(2)), m.group(3)
        if q_prefix:
            qcount += 1
            run_max = max(run_max, num)
            continue
        if sep != '.':            # 접두 없는 'N)' 는 선지로 간주(문항은 'N.')
            continue
        if num == run_max + 1:               # 시퀀스 연속 → 문항
            qcount += 1
            run_max = num
        elif num == 1 and run_max >= 2:       # 새 섹션 재시작(직전 섹션 ≥2문항)
            qcount += 1
            run_max = 1
    return qcount


def qcount_diverges(primary, secondary):
    """두 독립 문항수 신호(답 마커 vs 문제번호)가 '유의하게' 다른가 — 체크포인트 경고용.

    secondary 는 근사라 작은 차이는 경고하지 않는다(허용오차 = 큰 값의 15% 또는 ±2).
    한쪽이 0이면 비교 불가로 False."""
    if not primary or not secondary:
        return False
    hi, lo = max(primary, secondary), min(primary, secondary)
    return (hi - lo) > max(2, 0.15 * hi)


def count_qnum_starts(seg):
    """세그먼트(답 마커 사이) 안의 '문제번호 시작' 줄 수를 시퀀스 가정 없이 센다.

    답 마커 사이 한 세그먼트에 문제번호가 2개 이상이면 = 답 미표기 문항이 다음(답 있는)
    문항 세그먼트에 흡수된 것 → 흡수 의심으로 플래그한다(체크포인트 ABSORBED_QUESTION)."""
    n = 0
    for raw in (seg or '').splitlines():
        line = raw.strip()
        m = _QNUM_LINE_RE.match(line)
        if not m:
            continue
        if len(_OPT_MARKER_RE.findall(line)) >= 2:
            continue
        if m.group(1) or m.group(3) == '.':
            n += 1
    return n


def unmerge_glued(full):
    """#6 병합문항 Unmerging — 번호가 앞 문항에 들러붙은 경우 번호 앞에 개행을 넣는다.

    예) '…장영실 교수님2장영실 교수님…' → '…장영실 교수님\n2장영실 교수님…'
    'N이름 교수' 패턴(번호+한글이름+'교수')만 대상으로 해, '제2형당뇨' 같은 일반 숫자는 건드리지 않는다.
    ANS_RE 세그먼트 분리 '이전' 전처리 단계에서 호출한다.
    """
    return GLUE_PROF_RE.sub(lambda m: '\n' + m.group(1) + m.group(2), full or '')


def clean_stem(seg):
    """#2 이전 문항 해설 침범 제거 + 선두 공백·특수문자 정제.

    seg = 직전 답 마커 끝 ~ 현재 답 마커 시작. 앞부분에 직전 해설 잔여물이 섞일 수 있다.
    '해설:'/'답:' 마커가 있으면 그 뒤 처음 등장하는 문제번호부터를 현재 stem 으로 잘라낸다
    (마커가 없으면 전체를 stem 으로 보고 선두 잡문자만 정제 — 선지 번호를 오절단하지 않음).
    """
    s = seg or ''
    em = list(EXPL_MARK_RE.finditer(s))
    if em:
        after = s[em[-1].end():]
        qm = _qnum_question_match(after)   # 'N)' 열거식 해설은 문제 시작이 아님
        s = after[qm.start():] if qm else after
    # 본문 선두의 공백·괄호·구두점 등 잡문자 제거
    s = re.sub(r'^[\s)\]>。.·•:：、,]+', '', s)
    return s.strip()


def _split_by_circled(text):
    idxs = [i for i, ch in enumerate(text) if ch in CIRCLED]
    if len(idxs) < 2:
        return text, []
    stem = text[:idxs[0]].strip()
    opts = []
    for j, i in enumerate(idxs):
        end = idxs[j + 1] if j + 1 < len(idxs) else len(text)
        opts.append(text[i:end].strip())
    return stem, opts


def _split_by_numeric(text):
    """#5 '1.'·'2)' … 숫자형 선지 분리. 1(또는 2)부터 연속 증가하는 run 만 선지로 인정.

    한 문항의 선지 마커는 구분자(마침표 '.' / 괄호 ')')가 일관된다는 점을 이용한다:
      · run 안의 마커는 모두 같은 구분자여야 한다.
      · 길이가 같은 run 이 여럿이면 '가장 늦게 시작하는' run 을 택한다.
    이 둘이 합쳐져, 앞에 붙은 문제번호('Q1.' 의 '1.' 이나 '1.' 뒤 '1) 2)' 의 선두 '1.')를
    선지로 빨아들이지 않고 stem 에 남긴다(감사 P2: Q1. 의 '1.' 이 선지 1로 오인되던 버그).
    - 'Q1. … 1) 2) 3)' : '.' run 은 [1.] 한 개뿐(탈락) → ')' run [1)2)3)] 만 선지.
    - '1. … 1) 2)'      : 동일.
    - '1. 가이다.2. 나이다.3. 다이다' : '.' run [1.2.3.] 만 존재 → 그대로 선지(회귀 없음).
    - '1. 다음? 1. 가 2. 나 3. 다'    : 같은 길이 run 둘 → 늦은 시작(선지 '1.가')을 택해 문제번호 보존.
    """
    matches = [(m.start(), int(m.group(1)), m.group(0)[1])
               for m in NUM_OPT_RE.finditer(text)]
    best = None  # (length, start_pos, seq)
    for i, (pos, val, delim) in enumerate(matches):
        if val not in (1, 2):        # 선지 시작은 보통 1, 가끔 2
            continue
        seq = [(pos, val, delim)]
        expected = val + 1
        for (p2, v2, d2) in matches[i + 1:]:   # 같은 구분자 + 연속 증가만 누적
            if d2 == delim and v2 == expected:
                seq.append((p2, v2, d2))
                expected += 1
        if len(seq) < 2:             # 2~3개도 인정하되, 최소 2개는 있어야 선지로 본다
            continue
        cand = (len(seq), pos)       # 길이 우선, 동률이면 늦게 시작(=문제번호를 stem 에 남김)
        if best is None or cand > (best[0], best[1]):
            best = (cand[0], cand[1], seq)
    if best is None:
        return text, []
    seq = best[2]
    stem = text[:seq[0][0]].strip()
    opts = []
    for j, (pos, val, delim) in enumerate(seq):
        end = seq[j + 1][0] if j + 1 < len(seq) else len(text)
        opts.append(text[pos:end].strip())
    return stem, opts


def split_stem_options(text):
    """#1 지문/선지 분리. (stem, options[]) 반환. 원문자(①) 우선, 없으면 숫자형(1./1)).

    어떤 마커도 2개 미만이면 선지 없음으로 보고 (전체, []) 반환(단답·주관식 보호 — #5).
    """
    text = (text or '').strip()
    if not text:
        return '', []
    stem, opts = _split_by_circled(text)
    if len(opts) >= 2:
        return stem, opts
    stem, opts = _split_by_numeric(text)
    if len(opts) >= 2:
        return stem, opts
    return text, []


def parse_categories(full):
    """#3 [2025년]·<소화기>·교수명 태그를 위치순으로 추적하는 tags_for(idx) 콜백을 만든다.

    Returns
    -------
    Callable[[int], tuple]
        문자 인덱스 → (year, category, prof). 각 값은 해당 위치 직전 '가장 최근' 태그(없으면 '').
    """
    years = [(m.start(), m.group(1)) for m in YEAR_TAG_RE.finditer(full or '')]
    cats = [(m.start(), m.group(1).strip()) for m in CAT_TAG_RE.finditer(full or '')
            if not any(w in m.group(1) for w in CAT_STOP)]      # 구조 마커 제외
    # 라벨형(담당교수:)·경칭형(…교수님)만 인정 + 비이름 토큰 컷 → 자유본문 이름 오염 방지
    profs = sorted(
        [(m.start(), m.group(1).strip())
         for rx in (PROF_LABELED_RE, PROF_HONORIFIC_RE)
         for m in rx.finditer(full or '')
         if not any(w in m.group(1) for w in PROF_STOP)]
    )

    def _recent(seq, idx):
        cur = ''
        for s, v in seq:
            if s <= idx:
                cur = v
            else:
                break
        return cur

    def tags_for(idx):
        return (_recent(years, idx), _recent(cats, idx), _recent(profs, idx))

    return tags_for


def compose_bucket(year, category, prof):
    """표시용 분류키 '[연도] <분류> 담당교수:OOO' 합성(빈 부분은 생략)."""
    parts = []
    if year:
        parts.append("[%s]" % year)
    if category:
        parts.append("<%s>" % category)
    if prof:
        parts.append("담당교수:%s" % prof)
    return " ".join(parts)


def strip_leading_header(seg, header_re):
    """#2b seg 선두의 헤더 블록(및 그 앞 배너/표지 잡문)을 제거해 stem 오염을 막는다.

    답 마커 사이 세그먼트에는 문항이 1개뿐이고, 헤더([연도 교실/교수] 범위)는 항상 그 앞에 온다.
    따라서 seg 안에 헤더가 있으면 '마지막 헤더 끝'까지를 잘라낸다 — 이로써 블록 첫 문항 stem 에
    배너('=== … ===')와 헤더 라벨이 통째로 빨려들던 감사 P2 증상을 제거한다(헤더는 이미 메타로 파싱됨).
    헤더가 없으면(블록 내 2번째 이후 문항) 손대지 않는다.
    """
    if not seg or header_re is None:
        return seg
    last = None
    for m in header_re.finditer(seg):
        last = m
    return seg[last.end():] if last is not None else seg


def split_blind_key(full, header_for, page_for, tags_for=None, header_re=None):
    """답 마커 기준으로 문항을 (blind, key) 두 리스트로 분리한다.

    blind: 풀이용 — stem/options 만(원본 답·해설 없음). 에이전트가 '블라인드'로 답을 정한다.
    key:   봉인 — idx + 원본 답 + 원본 해설. '풀고 나서' 비교 단계에서만 연다.
    두 리스트는 idx 로 1:1 정렬된다. blind 에는 'answer'·'expl_raw' 키가 절대 없어야 한다(불변식).

    v2: 각 blind 문항에 stem(정제)·options[]·(tags_for 주면)category·prof·bucket 을 채운다.
        stem_raw(원시 덩어리)는 호환을 위해 그대로 보존한다.

    Parameters
    ----------
    full : str
        연결된 PDF 전문(unmerge_glued 적용 후).
    header_for : Callable[[int], tuple]
        문자 인덱스 → (year, dept_prof, scope_label).
    page_for : Callable[[int], int]
        문자 인덱스 → 페이지 번호.
    tags_for : Callable[[int], tuple], optional
        문자 인덱스 → (year, category, prof). 주어지면 #3 세분화 필드를 채운다.
    """
    blind, key = [], []
    marks = list(ANS_RE.finditer(full))
    prev_end = 0
    for k, m in enumerate(marks):
        aidx = m.start()
        seg = full[prev_end:aidx]
        nxt = marks[k + 1].start() if k + 1 < len(marks) else len(full)
        expl = full[m.end():min(nxt, m.end() + 700)]
        hb = expl.find('[20')
        if hb > 0:
            expl = expl[:hb]
        # 감사 P0-2: 해설을 '다음 답 마커'가 아니라 '다음 문제 시작'에서 자른다.
        # (unmerge 로 들러붙은 'N교수님' 경계엔 이미 개행이 있어 QNUM_START_RE 가 잡는다.)
        # 해설이 없어 expl 선두가 곧 다음 문항인 경우(예 'Q2. …') 도 Q 접두면 위치 0에서 자른다.
        # 접두 없는 'N)' 은 열거식 해설일 수 있어 위치 0(qm.start()==0)에선 보존한다(오절단 방지).
        qm = _qnum_question_match(expl)
        if qm and (qm.start() > 0 or qm.group(1)):
            expl = expl[:qm.start()]
        y, dp, sc = header_for(aidx)
        stem, options = split_stem_options(clean_stem(strip_leading_header(seg, header_re)))
        rec = {'idx': k, 'page': page_for(aidx), 'year': y, 'dept_prof': dp,
               'scope': sc, 'stem': stem, 'options': options,
               'stem_raw': seg[-450:].strip()}      # stem_raw 보존(블라인드 불변식 테스트)
        # P1-5(b) 세그먼트 정합성: 답 마커 사이에 문제번호가 2개 이상이면 답 미표기 문항 흡수 의심.
        nq = count_qnum_starts(seg)
        if nq >= 2:
            rec['absorbed_qnums'] = nq
        if tags_for is not None:                     # #3 세분화 필드(있을 때만)
            ty, tc, tp = tags_for(aidx)
            rec['category'] = tc
            rec['prof'] = tp
            rec['bucket'] = compose_bucket(ty or y, tc, tp)
        blind.append(rec)
        key.append({'idx': k, 'answer': m.group(1), 'expl_raw': expl.strip()[:500]})
        prev_end = m.end()
    return blind, key


# ─────────────────────────────────────────────────────────────────────────────
# #4 이미지 BBox 매핑 (pdfplumber) — 없으면 graceful fallback(None)
# ─────────────────────────────────────────────────────────────────────────────

def _load_pdfplumber():
    try:
        import pdfplumber
        return pdfplumber
    except Exception:
        return None


def extract_image_geometry(pdf_path):
    """pdfplumber 로 페이지별 이미지 y구간·단어 좌표를 읽는다. pdfplumber 없으면 None.

    Returns
    -------
    dict | None
        {page(int): {'images': [(top, bottom), …y오름차순], 'words': [(top, text), …]}}
        None 이면 #4 비활성(호출자는 candidate_images 를 생략한다).
    """
    plumber = _load_pdfplumber()
    if plumber is None:
        return None
    geo = {}
    try:
        with plumber.open(pdf_path) as pdf:
            for pi, page in enumerate(pdf.pages, start=1):
                imgs = sorted(
                    (float(im['top']), float(im['bottom']))
                    for im in (page.images or [])
                    if im.get('top') is not None and im.get('bottom') is not None
                )
                words = []
                try:
                    for w in page.extract_words():
                        words.append((float(w['top']), w.get('text', '')))
                except Exception:
                    pass
                geo[pi] = {'images': imgs, 'words': words}
    except Exception as e:
        print("[#4] pdfplumber 지오메트리 추출 실패 → 페이지단위 후보로 폴백:", e, file=sys.stderr)
    return geo


def _locate_stem_y(words, stem):
    """페이지 단어목록에서 stem 선두 토큰의 y(top)를 찾는다. 못 찾으면 None."""
    s = re.sub(r'\s+', '', stem or '')[:8]
    if not s:
        return None
    for top, text in words:
        t = re.sub(r'\s+', '', text or '')
        if t and (t.startswith(s[:3]) or s[:4] in t):
            return top
    return None


def assign_candidate_images(geometry, page_images, blind):
    """#4 문항별 후보 이미지(candidate_images)를 blind 레코드에 부여한다(in-place).

    geometry is None  → 아무것도 하지 않는다(pdfplumber 부재 = #4 비활성, 현행 평면 동작).
    그 외 → 문항이 속한 페이지의 이미지 중, 문항 stem 의 y구간에 해당하는 파일을 후보로 단다.
    페이지에 문항이 1개거나 y추정 실패·이미지수 불일치면 '페이지 전체'를 후보로 둔다(안전 폴백).

    Parameters
    ----------
    geometry : dict | None
        extract_image_geometry() 결과.
    page_images : dict[int, list[str]]
        페이지 → 추출된 이미지 파일명 목록(추출 순서=문서 위→아래 근사).
    blind : list[dict]
        split_blind_key() 의 blind. 'page'·'stem' 키 사용. 'candidate_images' 를 추가한다.
    """
    if geometry is None:
        return
    from collections import defaultdict
    by_page = defaultdict(list)
    for q in blind:
        by_page[q.get('page')].append(q)

    for page, qs in by_page.items():
        files = list(page_images.get(page, []))
        if not files:
            continue
        g = geometry.get(page) or {}
        img_bands = g.get('images') or []     # [(top, bottom)] y오름차순
        words = g.get('words') or []
        q_y = [_locate_stem_y(words, q.get('stem') or q.get('stem_raw') or '') for q in qs]

        # 안전 폴백: 문항 1개 / y추정 실패 / 이미지수 불일치 → 페이지 전체 후보
        if len(qs) == 1 or any(y is None for y in q_y) or len(img_bands) != len(files):
            for q in qs:
                q['candidate_images'] = list(files)
            continue

        # 파일(추출 순서) ↔ 이미지 y(상단) 정렬 zip → 파일별 y
        file_y = sorted(zip([b[0] for b in img_bands], files))   # [(top, fname)…]
        order = sorted(range(len(qs)), key=lambda i: q_y[i])      # 문항 y오름차순
        bounds = [q_y[i] for i in order]
        for oi, qi in enumerate(order):
            lo = bounds[oi]
            hi = bounds[oi + 1] if oi + 1 < len(order) else float('inf')
            qs[qi]['candidate_images'] = [fn for (ty, fn) in file_y if lo <= ty < hi]
        # 첫 문항 stem 위(헤더 영역)의 이미지는 첫 문항에 귀속
        above = [fn for (ty, fn) in file_y if ty < bounds[0]]
        if above:
            first = order[0]
            qs[first]['candidate_images'] = above + qs[first].get('candidate_images', [])


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def columnaware_page_texts(pdf_path, pypdf_reader):
    """Phase1 컬럼 인지 추출: 2단으로 감지된 페이지만 컬럼 순서로 재구성, 1단은 pypdf 그대로.

    1단 페이지는 baseline(pypdf extract_text)과 동일하게 유지 → 단일컬럼 입력은 회귀 0.
    pdfplumber 가 없으면 None(호출부가 전 페이지를 pypdf 로 처리).
    """
    pp = _load_pdfplumber()
    if pp is None:
        return None
    import format_probe
    texts = []
    with pp.open(pdf_path) as doc:
        for i, page in enumerate(doc.pages):
            words = page.extract_words() or []
            ncol = format_probe.detect_columns(words, page.width)
            if ncol >= 2:
                mid = page.width * 0.5
                left = [w for w in words if w['x0'] < mid]
                right = [w for w in words if w['x0'] >= mid]
                ordered = sorted(left, key=lambda w: (round(w['top']), w['x0'])) + \
                          sorted(right, key=lambda w: (round(w['top']), w['x0']))
                texts.append(' '.join(w['text'] for w in ordered))
            else:
                texts.append(pypdf_reader.pages[i].extract_text() or '')
    return texts


def main():
    import pypdf  # PDF 처리는 main()에서만 필요; 위 순수함수들은 pypdf 불필요
    ap = argparse.ArgumentParser()
    ap.add_argument('--pdf', required=True)
    ap.add_argument('--work', required=True)
    ap.add_argument('--header-regex', default=DEFAULT_HEADER_REGEX)
    ap.add_argument('--auto-format', action='store_true',
                    help='Phase1 제네릭 포맷 추론: 답·해설 블록 구분자/러닝헤더/컬럼을 입력에서 '
                         '도출해 인라인 블록형 족보의 해설 침범·유령 문항을 구조적으로 제거(결정론).')
    ap.add_argument('--segmentation', default='',
                    help='Phase2 포맷추론 에스컬레이션: LLM Segmenter 가 만든 포인터맵(JSON, '
                         '라인ID→역할)을 받아 코드가 절단한다. 결정론/--auto-format 대신 사용. '
                         '검증(파티션·블라인드 불변식·no-leak) 실패 시 blocker 경고로 막힌다.')
    args = ap.parse_args()

    os.makedirs(os.path.join(args.work, 'images'), exist_ok=True)
    r = pypdf.PdfReader(args.pdf)

    # 1) 페이지별 텍스트 + 이미지 수, 전체 텍스트 + 페이지 맵
    #    --auto-format 시 2단 감지 페이지는 컬럼 순서로 재구성(1단 페이지는 baseline 유지).
    col_texts = columnaware_page_texts(args.pdf, r) if args.auto_format else None
    # full     = 파이프라인 분절 입력(2단 감지 페이지는 컬럼 순서로 재구성).
    # raw_full = '문제번호 기준' 보조 카운트(count_question_numbers)용 원문 — 컬럼 재구성 '이전'.
    #            컬럼 재구성은 2단 페이지를 한 줄로 join(라인 구조 소실)하므로, 그 위에서 보조
    #            카운트를 세면 by_number 가 0 으로 떨어져 답마커-독립 second-opinion 이 무력화된다.
    #            단일컬럼(col_texts is None) 기본 경로는 raw_full 을 쓰지 않고 full 로 세어 동작 불변.
    full = ""; raw_full = ""; pagemap = []; pages = []
    for i, p in enumerate(r.pages):
        raw_t = p.extract_text() or ''
        t = (col_texts[i] if col_texts is not None else raw_t) or ''
        full += t + "\n"; raw_full += raw_t + "\n"; pagemap.append((len(full), i + 1))
        xo = p.get('/Resources', {}).get('/XObject')
        nimg = 0
        if xo:
            try:
                nimg = sum(1 for k in xo if xo[k].get('/Subtype') == '/Image')
            except Exception:
                pass
        pages.append({'page': i + 1, 'textlen': len(t), 'n_images': nimg})

    # #6 병합문항 Unmerging — 세그먼트 분리 '이전' 전처리(페이지맵은 길이 보존 위해 동일 치환수 가정)
    n_unmerged = len(GLUE_PROF_RE.findall(full))
    full = unmerge_glued(full)
    # unmerge 는 '\n' 1자만 삽입하므로 pagemap 오프셋이 소폭 밀린다. 페이지 정확도가 중요하면
    # page_at 은 근사로 충분(문항 페이지 표기는 ±1 허용). 정밀 필요시 재계산 가능.

    def page_at(idx):
        for end, pg in pagemap:
            if idx < end: return pg
        return len(r.pages)

    # 2) 헤더 블록([연도 교실 교수] 범위라벨)
    hdr_re = re.compile(args.header_regex)
    hdrs = [(m.start(), m.group(1), m.group(2).strip(), m.group(3).strip())
            for m in hdr_re.finditer(full)]

    def header_for(idx):
        cur = (None, None, None)
        for s, y, dp, sc in hdrs:
            if s <= idx: cur = (y, dp, sc)
            else: break
        return cur

    blocks = [{'page': page_at(s), 'year': y, 'dept_prof': dp, 'scope_label': sc}
              for s, y, dp, sc in hdrs]

    # 3) 문항 세그먼트 — 블라인드/정답키 분리 + #1/#2/#5 stem·options + #3 분류 태그
    tags_for = parse_categories(full)
    auto_profile = None
    provenance = 'deterministic'
    seg_problems, seg_leaks = [], []
    if args.segmentation:
        # Phase2: LLM Segmenter 포인터맵 → 코드가 절단(라인ID로만, 텍스트 재작성 0).
        # 답을 본 역할은 라벨만 내보내므로 blind 에 정답이 물리적으로 들어갈 수 없다.
        import llm_segment  # 지연 임포트(순환 방지)
        lines = full.split('\n')
        smap = llm_segment.load_segmentation_map(args.segmentation)
        blind, key, auto_profile = llm_segment.apply_segmentation(
            lines, header_for, page_at, smap, tags_for=tags_for)
        seg_problems, seg_leaks = llm_segment.verify_segmentation(lines, smap, blind, key)
        provenance = 'llm-segment'
    elif args.auto_format:
        import format_probe  # 지연 임포트(순환 방지)
        delim = format_probe.derive_answer_delimiter(full)
        if delim:
            # Phase1: 답·해설 블록을 분절 경계로 — 해설 침범·유령 문항 구조적 제거(redact-before-segment)
            blind, key, auto_profile = format_probe.auto_segment(
                full, header_for, page_at, tags_for=tags_for, delimiter=delim)
            provenance = 'auto-format'
        else:
            blind, key = split_blind_key(full, header_for, page_at, tags_for=tags_for, header_re=hdr_re)
    else:
        blind, key = split_blind_key(full, header_for, page_at, tags_for=tags_for, header_re=hdr_re)

    # 4) 임베드 이미지 추출(+ 페이지별 파일명 맵)
    from collections import defaultdict
    page_images = defaultdict(list)
    cnt = 0
    for i, p in enumerate(r.pages):
        try:
            imgs = list(p.images)
        except Exception as e:
            print("img err p", i + 1, e, file=sys.stderr)
            continue
        for img in imgs:
            # 이미지 '개별' try — 한 이미지의 깨진 스트림/이상 이름이 그 페이지의 나머지
            # 이미지 추출까지 통째로 삼키지 않게 한다. 파일명은 PDF 리소스명 유래라
            # OS 예약문자(\ : * ? " < > |)를 전부 무해화한다('/' 만 바꾸면 Windows 에서 실패).
            try:
                cnt += 1
                raw_name = f"p{i+1:02d}_{cnt:03d}_{img.name}"
                name = re.sub(r'[^\w.\-가-힣]', '_', raw_name)
                with open(os.path.join(args.work, 'images', name), 'wb') as f:
                    f.write(img.data)
                page_images[i + 1].append(name)
            except Exception as e:
                print("img err p", i + 1, e, file=sys.stderr)

    # 4b) #4 이미지 BBox 매핑 — pdfplumber 있으면 문항별 candidate_images, 없으면 비활성
    geometry = extract_image_geometry(args.pdf)
    assign_candidate_images(geometry, page_images, blind)
    n_mapped = sum(1 for q in blind if q.get('candidate_images'))
    pdfplumber_on = geometry is not None

    json.dump({'pages': pages, 'blocks': blocks},
              open(os.path.join(args.work, 'structure.json'), 'w'), ensure_ascii=False, indent=1)
    # lines.json = LLM Segmenter(Phase2 에스컬레이션) 입력용 라인 인덱싱 덤프(full = '\n'.join(lines)).
    # 답 포함 → output/ 하위라 .gitignore 됨. answer_key.json 과 동일 노출 수준(새 노출 아님).
    json.dump({'lines': full.split('\n')},
              open(os.path.join(args.work, 'lines.json'), 'w'), ensure_ascii=False, indent=1)
    # P1-5 보조 신호: 답 마커와 무관한 '문제번호 기준' 문항수(교차검증용). 답 누락/오탐을 사람이 보게.
    # --auto-format 컬럼 재구성 시엔 재구성 '이전' 원문(raw_full)으로 센다(2단 collapse 가 문제번호
    # 라인을 뭉개 by_number 를 0 으로 떨구는 것 방지). 기본 경로는 full 로 세어 동작 불변.
    n_by_number = count_question_numbers(raw_full if args.auto_format else full)
    n_absorbed = sum(1 for q in blind if q.get('absorbed_qnums'))
    # counts.json = 기계 판독용 매니페스트(감사 권고). main.py 가 stdout 정규식 대신 이걸 읽는다.
    counts_manifest = {'pages': len(pages), 'images': cnt, 'headers': len(blocks),
                       'questions': len(blind), 'questions_by_number': n_by_number,
                       'absorbed_segments': n_absorbed,
                       'mapped': n_mapped, 'unmerged': n_unmerged,
                       'pdfplumber': pdfplumber_on}
    if args.auto_format:
        # Phase1 프로필 키(기본 경로에는 없던 필드 — 플래그가 있을 때만 추가해 기본 산출을 보존).
        counts_manifest.update({
            'auto_format': True,
            'provenance': provenance,
            'column_aware': col_texts is not None,
            'auto_delimiter': auto_profile.get('delimiter') if auto_profile else None,
            'auto_titles': auto_profile.get('titles') if auto_profile else []})
    if args.segmentation:
        # Phase2 프로필 키(플래그가 있을 때만 추가해 기본 산출을 보존 — auto_format 과 동일 규율).
        counts_manifest.update({
            'segmentation': True,
            'provenance': provenance,
            'segmentation_problems': len(seg_problems),
            'segmentation_leaks': seg_leaks,
            'ignored_lines': auto_profile.get('ignored_lines') if auto_profile else 0})
    # 추출 경고 taxonomy + 체크포인트 blocker(HEADER_MISSING 등) — main.py 가 counts.json 으로 읽는다.
    warnings = parse_warnings.build_parse_warnings(counts_manifest, blind)
    if args.segmentation:
        # Phase2 검증 게이트: 구조 결함·누출은 blocker 로 주입해 체크포인트가 막게 한다.
        # LLM 출력을 신뢰하지 않고 기계적으로 증명한 결과만 통과시킨다(fail-closed).
        if seg_problems:
            warnings.append(parse_warnings.make_warning('SEGMENTATION_INVALID'))
        if seg_leaks:
            warnings.append(parse_warnings.make_warning('SEGMENTATION_LEAK', seg_leaks))
        warnings = parse_warnings.sort_parse_warnings(warnings)
    if args.auto_format:
        # 컬럼 인지 추출 후 확인된 문항이 문제번호 기준의 절반 이하로 급감하면 읽기 순서 오류 의심.
        q_seg = counts_manifest["questions"]
        q_num = counts_manifest["questions_by_number"]
        if counts_manifest.get("column_aware") and q_num >= 4 and q_seg <= max(1, 0.5 * q_num):
            warnings.append(parse_warnings.make_warning("COLUMN_ORDER_SUSPECT"))
        warnings = parse_warnings.sort_parse_warnings(warnings)
    blind = parse_warnings.enrich_question_warnings(blind, warnings)
    counts_manifest['warnings'] = warnings
    # all_questions.json = 블라인드(원본 답 없음). answer_key.json = 봉인 정답키.
    json.dump(blind, open(os.path.join(args.work, 'all_questions.json'), 'w'), ensure_ascii=False, indent=1)
    json.dump(key, open(os.path.join(args.work, 'answer_key.json'), 'w'), ensure_ascii=False, indent=1)
    json.dump(counts_manifest, open(os.path.join(args.work, 'counts.json'), 'w'), ensure_ascii=False, indent=1)

    from collections import Counter
    sc = Counter(b['scope_label'] or '(빈 라벨)' for b in blocks)
    # ↓ 이 첫 줄 형식은 main.py 가 정규식으로 파싱한다(변경 금지).
    print(f"페이지 {len(pages)} · 임베드 이미지 {cnt} · 헤더 {len(blocks)} · 답마커(문항) {len(blind)}")
    if args.auto_format:
        if auto_profile:
            print(f"#P1 자동포맷: 답·해설 블록 구분자 도출 '{auto_profile['delimiter']}' · "
                  f"러닝헤더 제목 {auto_profile['titles']} · 컬럼인지 {'on' if col_texts is not None else 'off'}")
        else:
            print("#P1 자동포맷: 반복 답·해설 블록 구분자 미검출 → 기본 분절(split_blind_key) 사용")
    if args.segmentation:
        _vp = f" · 구조결함 {len(seg_problems)}건" if seg_problems else ""
        _vl = f" · 누출의심 idx {seg_leaks}" if seg_leaks else ""
        _vok = " ✓ 검증통과" if not seg_problems and not seg_leaks else " ⚠ blocker(체크포인트 차단)"
        print(f"#P2 포맷추론(LLM Segmenter 포인터맵): 문항 {len(blind)}{_vp}{_vl}{_vok}")
    _xc = " ⚠ 불일치(답 누락/오탐 의심 — 확인 요망)" if qcount_diverges(len(blind), n_by_number) else ""
    print(f"문항수 교차검증 — 답마커 기준 {len(blind)} · 문제번호 기준(보조) {n_by_number}{_xc}")
    if n_absorbed:
        bad = [q['idx'] for q in blind if q.get('absorbed_qnums')]
        print(f"⚠ 세그먼트 정합성: 답 미표기 흡수 의심 {n_absorbed}건 (idx {bad}) — 해당 문항에 문제번호가 2개 이상 합쳐졌습니다(답 누락 가능).")
    if pdfplumber_on:
        print(f"#4 이미지 매핑: 후보 이미지 보유 문항 {n_mapped} (pdfplumber on)")
    else:
        print("#4 이미지 매핑: pdfplumber 미설치 → 비활성(이미지는 images/ 에서 수동 배정)")
    if n_unmerged:
        print(f"#6 병합 분리: {n_unmerged}건 unmerge")
    print("범위 라벨:", dict(sc))
    print("→ structure.json / all_questions.json(블라인드) / answer_key.json(봉인) / images/ 저장 완료")
    print("   ※ 블라인드 재검증: all_questions.json 으로 먼저 풀고, 그 다음에만 answer_key.json 을 열 것.")


if __name__ == '__main__':
    main()

# -*- coding: utf-8 -*-
"""
족보 재편집·재검증 DOCX 빌더 (과목 무관).

사용:
  python3 build.py --data "/path/과목/_work/questions_data.py" \
                   --img  "/path/과목/_work/images" \
                   --raw  "/path/과목/_work/all_questions.json" \
                   --out  "/path/과목/○○ 족보_재편집·재검증본.docx" \
                   --title "○○ 족보 — 재편집·재검증본" \
                   --subtitle "△△대 의대 2024 ... · 정렬: 범위 > 연도 > 교수"

questions_data.py 는 다음을 정의해야 한다:
  SCOPES = [ (범위헤더str, [문항dict, ...]), ... ]
문항 dict 스키마(필수 ★ / 선택):
  ★meta: "연도 · 교실 교수"    ★flags: [FLAG_TAXONOMY...]
  ★stem ★options:[..]         recon, image, image_caption, image_missing, scope_note
  ★verified ★source ★new_expl  ★orig_ans ★orig_expl
FLAG_TAXONOMY 7종: ANSWER_MATCH/ANSWER_CORRECTED/ANSWER_DISPUTED/TEXT_RECONSTRUCTED/
                   STEM_IMAGE_A_PRESENT/IMAGE_MISSING/SCOPE_RECLASSIFIED_OR_INFERRED
"""
import argparse, json, os, re, sys
# python-docx 는 빌드 시에만 필요 → main() 안에서 지연 import 한다.
# validate.py 가 build(스키마 게이트 헬퍼)를 import 해도 python-docx 없이 돌도록 계층 분리
# (모듈 최상단 import 면 '구조만 검사'하는 게이트가 docx 의존이 돼 main.py lazy-import 원칙과 모순).

FONT = "맑은 고딕"
NAVY=(0x1F,0x3A,0x5F); GREEN=(0x1B,0x6B,0x3A); RED=(0xB0,0x2A,0x2A); ORANGE=(0xB0,0x6A,0x00); GRAY=(0x66,0x66,0x66)

# ─── 스키마 헬퍼: schema.py 단일 정의를 import(복붙 금지). 뷰어/validate 와 공유. ──
from schema import (
    clean_scope, scope_prof, scope_year, is_royal, strip_royal, n_correct, as_text,
    split_prof, meta_nameonly, load_scopes, ROYAL_TAG,
)

# ─── 범위 오배치 검출(--strict-scope): 복원 오류로 다른 범위에 들어간 문항 잡기 ─────
# 고정밀 전략: 각 범위 헤더에서 '대표 키워드'(헤더 문서빈도 ≤ HEAD_DF_MAX 인 희소 토큰 = 질환·토픽명)
# 만 뽑는다(범용 해부어 '자궁/여성' 등은 여러 헤더에 나와 자동 제외). stem 만 본다(해설 교차참조 제외).
# stem 이 '다른 범위'의 대표 키워드를 SCOPE_HITS 개 이상 포함하고 + '자기 범위'보다 많으면 오배치 의심.
HEAD_DF_MAX = 2     # 헤더 토큰이 이 개수 이하 범위에만 등장해야 '대표 키워드'(희소)
SCOPE_HITS = 2      # 다른 범위 대표 키워드를 stem 에서 이만큼 이상 맞춰야 플래그(노이즈 컷)
_TOKRE = re.compile(r'[가-힣]{2,}|[A-Za-z]{3,}')
_SCOPE_STOP = set("환자 여성 남성 질환 검사 치료 진단 소견 증상 통증 내원 시행 가능 가장 적절 경우 정상 "
                  "옳은 옳지 것은 것을 다음 모두 해당 원인 영향 관련 위한 위해 그리고 또한 처치 방법 결과 "
                  # 범용 해부/증상어(특정 토픽 아님 — 단독으론 범위 식별 신호가 아니므로 제외)
                  "자궁 난소 월경 골반 난관 자궁내막 호르몬 출혈 질출혈 복통 하복부 종괴 부속기 양성 음성 임신".split())
def _toks(text):
    return [w for w in _TOKRE.findall(text or '') if w not in _SCOPE_STOP]
def _distinct_head_keywords(SCOPES):
    """범위별 대표 키워드 set. 헤더에 희소(≤HEAD_DF_MAX 범위)하게 나오는 토픽 토큰만."""
    from collections import Counter
    headtok = [set(_toks(clean_scope(h))) for h, _ in SCOPES]
    df = Counter(t for s in headtok for t in s)
    return [set(t for t in s if df[t] <= HEAD_DF_MAX) for s in headtok]
def scope_misplacements(SCOPES):
    labels = [clean_scope(h) for h, _ in SCOPES]
    distinct = _distinct_head_keywords(SCOPES)
    out = []
    for i, (h, qs) in enumerate(SCOPES):
        for q in qs:
            st = set(_toks(q.get('stem') or ''))
            if not st: continue
            own = len(distinct[i] & st)
            hits = [(len(distinct[j] & st), j) for j in range(len(SCOPES)) if j != i]
            best, bj = max(hits) if hits else (0, -1)
            if best >= SCOPE_HITS and best > own:
                ev = sorted(distinct[bj] & st)
                out.append((labels[i], labels[bj], q.get('meta', ''), (q.get('stem') or '')[:46], ev, own, best))
    return out

# ─── --strict-detail: '자세한 authoring' 강제 기준 ─────────────────────────
# 기준(사용자 확정): ① 충실한 new_expl(최소 글자수) ② imp(한 줄 핵심) ③ 오답 선지 해설(정답 외 보기 각각).
# 날조 금지 원칙상 '항상 진짜로 답할 수 있는' 항목만 강제(clinical_summary/tip/related_theory 는 선택 유지).
MIN_NEW_EXPL = 40   # new_expl 최소 글자수(왕족 태그 제거 후, 공백 포함). 필요시 이 값만 조정.

def detail_gaps(q):
    """--strict-detail 기준 미달 사유 목록. 빈 리스트면 통과."""
    gaps = []
    ne = q.get('new_expl')
    txt = " ".join(str(x) for x in ne) if isinstance(ne, list) else (ne or "")
    if len(strip_royal(txt)) < MIN_NEW_EXPL:
        gaps.append("new_expl<%d자" % MIN_NEW_EXPL)
    if not (q.get('imp') and str(q['imp']).strip()):
        gaps.append("imp")
    woe = q.get('wrong_option_explanations')
    nopt = len(q.get('options') or [])
    # 감사 P0-5: 주관식(options=[])은 오답 선지가 없으므로 강제하지 않는다(max(0,…)).
    # 객관식만 '전체-정답수'개의 오답 선지 해설을 요구한다.
    need = max(0, nopt - n_correct(q)) if nopt else 0
    have = len(woe) if isinstance(woe, list) else 0
    if have < need:
        gaps.append("오답선지(%d/%d)" % (have, need))
    return gaps

def main():
    # 지연 import (위 주석 참고): 빌드 시점에만 python-docx 를 끌어온다.
    from docx import Document
    from docx.shared import Pt, RGBColor, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True); ap.add_argument('--img', default='')
    ap.add_argument('--raw', default=''); ap.add_argument('--out', required=True)
    ap.add_argument('--title', default='족보 — 재편집·재검증본'); ap.add_argument('--subtitle', default='정렬: 범위 > 연도 > 교수')
    ap.add_argument('--year-desc', action='store_true', help='연도 정렬을 최신→과거(내림차순)로')
    ap.add_argument('--strict-years', action=argparse.BooleanOptionalAction, default=True,
                    help="(기본 ON) 날조 금지: years 미입력 문항은 자동추정 대신 '(연도 미확인)' 표기. "
                         "--no-strict-years 로 끄면 freq() 토큰유사도 자동추정 폴백(노이즈, 비권장)")
    ap.add_argument('--inscope', default='',
                    help='freq() 폴백 대상 bucket(쉼표구분, 예 "2차,총론"). 비우면 전체. '
                         '--no-strict-years 일 때만 의미 있음.')
    ap.add_argument('--strict-detail', action='store_true',
                    help="자세한 authoring 강제: imp(한줄 핵심)·오답선지 해설(정답 외 보기 각각)·충실한 new_expl 미달 시 빌드 거부")
    ap.add_argument('--strict-meta', action='store_true',
                    help="교수명 '이름만' 강제: meta 교수란에 과/교실명('○○과 …' 등)이 붙어 있으면 빌드 거부")
    ap.add_argument('--strict-scope', action='store_true',
                    help="범위 오배치 검출: 복원 오류로 다른 범위에 들어간 의심 문항을 추천 범위와 함께 출력하고 빌드 거부")
    args = ap.parse_args()

    SCOPES = load_scopes(args.data)

    # 자세한 authoring 강제(opt-in). 미달 문항 있으면 목록 출력하고 빌드 중단(날조 유도 방지 위해 채움은 수작업).
    if args.strict_detail:
        bad = [(clean_scope(head), q.get('meta', ''), g)
               for head, qs in SCOPES for q in qs if (g := detail_gaps(q))]
        if bad:
            print("✗ --strict-detail: 자세한 authoring 기준 미달 %d문항 — 빌드 중단" % len(bad))
            for sc, meta, g in bad[:60]:
                print("   [%s] %s — 누락: %s" % (sc, meta, ", ".join(g)))
            if len(bad) > 60:
                print("   … 외 %d문항" % (len(bad) - 60))
            print("   → imp·오답선지 해설·충실한 new_expl 을 채우거나, --strict-detail 없이 빌드하세요.")
            sys.exit(1)
        print("✓ --strict-detail 통과: %d문항 전부 기준 충족" % sum(len(v) for _, v in SCOPES))

    # 교수명 '이름만' 강제(opt-in). meta 교수란에 과/교실명이 붙어 있으면 차단.
    if args.strict_meta:
        bad = [(clean_scope(head), q.get('meta', ''), split_prof(q.get('meta', ''))[1])
               for head, qs in SCOPES for q in qs if split_prof(q.get('meta', ''))[1]]
        if bad:
            print("✗ --strict-meta: 교수명에 과/교실명 포함('이름만' 위반) %d문항 — 빌드 중단" % len(bad))
            for sc, meta, dept in bad[:60]:
                print("   [%s] %s  ← '%s' 제거(이름만)" % (sc, meta, dept))
            if len(bad) > 60:
                print("   … 외 %d문항" % (len(bad) - 60))
            print("   → meta 를 '연도 · 교수이름' 형식(과/교실명 없이)으로 수정하세요.")
            sys.exit(1)
        print("✓ --strict-meta 통과: 교수명 전부 이름만")

    # 범위 오배치 검출(opt-in). 다른 범위가 현저히 더 맞는 문항을 추천 범위와 함께 출력하고 차단.
    if args.strict_scope:
        mis = scope_misplacements(SCOPES)
        if mis:
            print("✗ --strict-scope: 범위 오배치 의심 %d문항 — 빌드 중단(복원 오류 가능성)" % len(mis))
            for cur_sc, sug_sc, meta, stem, ev, cs, bs in mis[:60]:
                print("   [%s] → 추천 [%s]  (점수 %d→%d, 근거: %s)" % (cur_sc, sug_sc, cs, bs, ", ".join(ev)))
                print("        %s · %s…" % (meta, stem))
            if len(mis) > 60:
                print("   … 외 %d문항" % (len(mis) - 60))
            print("   → 해당 문항을 추천 범위로 재배치하거나(오판이면 무시), --strict-scope 없이 빌드하세요.")
            sys.exit(1)
        print("✓ --strict-scope 통과: 명백한 범위 오배치 없음")

    # 출제 빈도(원본 all_questions.json 토큰 유사도 기반 추정)
    rawtok = []
    if args.raw and os.path.exists(args.raw):
        raw = json.load(open(args.raw))
        STOP = set("다음 으로 옳은 옳지 것은 것을 고르 고르시오 환자 소아 신생아 대해 대한 설명 진단 진단은 처치 치료 가장 적절 경우 무엇 보기 내원 하였다 한다 있다 있는 있으며 통해 위해 위한 그리고 또한 모두 해당 나타 나타나 보인다 시행 검사".split())
        def toks(x):
            return set(w for w in re.findall(r'[가-힣]{2,}|[A-Za-z]{3,}', x or '') if w not in STOP)
        # 'bucket' 필드가 있으면(과목별 추출기 산출) in-scope 마커만 빈도 추정 대상으로.
        # 과목값은 하드코딩하지 않고 --inscope 인자로 받는다(비우면 전체).
        INSCOPE = set(x.strip() for x in args.inscope.split(',') if x.strip())
        if INSCOPE:
            raw = [q for q in raw if ('bucket' not in q) or (q.get('bucket') in INSCOPE)]
        rawtok = [(q.get('year'), toks((q.get('stem_raw') or '') + ' ' + (q.get('expl_raw') or ''))) for q in raw]
    def freq(stem):
        # 자동 추정(폴백). 명시 years 가 없을 때만 사용. 오집계 줄이려 임계 상향(AND 조건).
        if not rawtok: return 1, []
        qt = set(w for w in re.findall(r'[가-힣]{2,}|[A-Za-z]{3,}', stem or ''))
        if not qt: return 1, []
        ys = [y for y, rt in rawtok
              if rt and y and len(qt & rt) >= 8 and len(qt & rt) / len(qt | rt) >= 0.45]
        return max(len(ys), 1), sorted(set(ys))

    doc = Document()
    st = doc.styles['Normal']; st.font.name = FONT; st.font.size = Pt(10.5)
    st.element.rPr.rFonts.set(qn('w:eastAsia'), FONT)
    def setf(run, size=10.5, bold=False, color=None):
        run.font.name = FONT; run.font.size = Pt(size); run.font.bold = bold
        run._element.rPr.rFonts.set(qn('w:eastAsia'), FONT)
        if color: run.font.color.rgb = RGBColor(*color)
    def para(t="", size=10.5, bold=False, color=None, before=0, after=2, align=None, indent=None):
        p = doc.add_paragraph()
        if align: p.alignment = align
        pf = p.paragraph_format; pf.space_before = Pt(before); pf.space_after = Pt(after)
        if indent is not None: pf.left_indent = Cm(indent)
        if t:
            r = p.add_run(t); setf(r, size, bold, color)
        return p
    def runs(p, parts):
        for t, kw in parts:
            r = p.add_run(t); setf(r, **kw)
        return p
    def hr(p):
        pPr = p._p.get_or_add_pPr(); b = OxmlElement('w:pBdr'); bot = OxmlElement('w:bottom')
        bot.set(qn('w:val'), 'single'); bot.set(qn('w:sz'), '6'); bot.set(qn('w:space'), '1'); bot.set(qn('w:color'), '999999')
        b.append(bot); pPr.append(b)
    def scope_head(text):
        # viewer 와 동일하게 '· [<연도> 담당교수: …]' 꼬리는 헤딩에서 제거하고,
        # 담당교수는 작은 부제 줄로 보존(이모지 금지 — 텍스트만). 연도는 헤더에서 읽어 그대로 표기.
        p = para(clean_scope(text), 13, True, NAVY, before=8, after=2)
        pPr = p._p.get_or_add_pPr(); sh = OxmlElement('w:shd'); sh.set(qn('w:val'), 'clear'); sh.set(qn('w:fill'), 'E8EEF4'); pPr.append(sh)
        prof = scope_prof(text)
        if prof:
            yr = scope_year(text)
            label = (yr + " 담당교수: ") if yr else "담당교수: "
            runs(para("", 9, after=4), [(label, {"size":8.5,"bold":True,"color":GRAY}),
                                        (prof, {"size":9,"color":NAVY})])
    def yearkey(q):
        m = re.search(r'(19|20)\d{2}', q.get('meta', '')); y = int(m.group(0)) if m else 9999
        return (-y if args.year_desc else y, q.get('meta', ''))

    def render_rich(q):
        # 리치 블록(optional) — viewer showExpl 와 동일 필드·순서. 비면 미렌더.
        if q.get('imp'):
            runs(para("",9.5,after=1,indent=0.3), [("IMP: ",{"size":9.5,"bold":True,"color":NAVY}),(str(q['imp']),{"size":9.5,"color":(0,0,0)})])
        cs = q.get('clinical_summary')
        if isinstance(cs, dict):
            rows = [(k, v) for k, v in cs.items() if v not in (None, "")]
            if rows:
                runs(para("",9.5,after=1,indent=0.3), [("CLINICAL",{"size":9.5,"bold":True,"color":NAVY})])
                for k, v in rows:
                    runs(para("",9,after=1,indent=0.6), [(f"{k}: ",{"size":9,"bold":True,"color":GRAY}),(str(v),{"size":9,"color":(0,0,0)})])
        woe = q.get('wrong_option_explanations')
        if isinstance(woe, list) and woe:
            runs(para("",9.5,after=1,indent=0.3), [("오답 선지",{"size":9.5,"bold":True,"color":NAVY})])
            for it in woe: para("· " + str(it), 9, after=1, indent=0.6)
        if q.get('tip'):
            runs(para("",9.5,after=1,indent=0.3), [("TIP: ",{"size":9.5,"bold":True,"color":GREEN}),(str(q['tip']),{"size":9.5,"color":(0,0,0)})])
        if q.get('related_theory'):
            runs(para("",9.5,after=2,indent=0.3), [("관련 이론: ",{"size":9.5,"bold":True,"color":NAVY}),(str(q['related_theory']),{"size":9.5,"color":(0,0,0)})])

    def render(q):
        years = [str(y) for y in (q.get('years') or [])]
        if years:           # 명시 출제연도(수기 검증) 우선 — 정확
            ys = sorted(set(years), key=lambda y: -int(y)) if all(y.isdigit() for y in years) else years
            c = q.get('exam_count') or len(ys)
            badge = " · " + ("출제 1회 (%s)" % ys[0] if c == 1 else "출제 %d회 (%s)" % (c, ", ".join(ys)))
        elif args.strict_years:  # 날조 금지: 미확인은 숫자 안 만든다
            c, badge = None, " · (연도 미확인)"
        else:               # 폴백: 자동 추정(임계 상향, in-scope 한정)
            c, ys = freq(q.get('stem', ''))
            badge = (" · 출제 %d회" % c) + ((" (" + ", ".join(ys) + ")") if ys else " (고유)")
        meta_parts = [(meta_nameonly(q.get('meta', '')), {"size":9.5,"bold":True,"color":GRAY}),  # 교수명 이름만 표시
                      (badge, {"size":9,"bold":True,"color":GREEN if (c and c>=3) else GRAY})]
        if is_royal(q):     # viewer 👑 왕족 배지 대응(DOCX 이모지 금지 → 텍스트 배지)
            meta_parts.append(("   【왕족】", {"size":9,"bold":True,"color":ORANGE}))
        runs(para("", 9.5, after=1), meta_parts)
        if q.get('flags'):  # optional — 없으면 미렌더
            runs(para("", 8.5, after=2), [("FLAGS  ", {"size":8,"bold":True,"color":GRAY}), (" ".join(q['flags']), {"size":8.5,"bold":True,"color":ORANGE})])
        if q.get('recon'):
            runs(para("",9,after=1), [("[추정 재구성] ",{"size":9,"bold":True,"color":ORANGE}),(q['recon'],{"size":9,"color":ORANGE})])
        runs(para("",11,after=2), [(q.get('stem',''),{"size":11,"bold":True,"color":(0,0,0)})])
        for o in (q.get('options') or []): para(o, 10.5, after=1, indent=0.5)
        # 이미지: 단일 image(하위호환) + 다중 images[](v2 #4). 캡션은 image_caption / image_captions[].
        def _add_img(fname, caption):
            if not fname:
                return
            # --img 미지정이면 경로 자체가 없다 → 조용히 넘기지 않고 아래 else 에서 누락 기록.
            path = (fname if os.path.isabs(fname) else os.path.join(args.img, fname)) if args.img else None
            if path and os.path.exists(path):
                ip = doc.add_paragraph(); ip.alignment = WD_ALIGN_PARAGRAPH.CENTER
                ip.add_run().add_picture(path, width=Cm(7))
                cap = para(caption or '', 8.5, False, GRAY, after=4); cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
            else:
                # 조용한 탈락 방지: 파일 부재·--img 미지정으로 못 실은 이미지를 기록해
                # 빌드 끝에 한 번에 경고한다(뷰어 빌더의 missing_img 경고와 동일한 계약).
                missing_imgs.append(str(fname))
        if q.get('image'):
            _add_img(q['image'], q.get('image_caption', ''))
        imgs = q.get('images')
        if isinstance(imgs, list):
            caps = q.get('image_captions') or []
            for i, fn in enumerate(imgs):
                _add_img(fn, caps[i] if i < len(caps) else '')
        if q.get('image_missing'):
            miss = q['image_missing'] if isinstance(q['image_missing'], str) else "원본 참조 이미지가 PDF에 없음"
            runs(para("",10,after=4,indent=0.5), [("[이미지 누락] ",{"size":10,"bold":True,"color":RED}),(miss,{"size":9.5,"color":GRAY})])
        if q.get('scope_note'):
            runs(para("",9,after=3), [("[범위 추론] ",{"size":9,"bold":True,"color":ORANGE}),(q['scope_note'],{"size":9,"color":GRAY})])
        hr(para("",2,after=3))
        vlabel = "검증 정답: " + ("(복수 정답) " if n_correct(q) > 1 else "")
        runs(para("",10.5,after=1), [(vlabel,{"size":10.5,"bold":True,"color":GREEN}),(q.get('verified',''),{"size":10.5,"bold":True,"color":GREEN})])
        if q.get('source'):  # optional
            runs(para("",9.5,after=1,indent=0.3), [("근거(출처): ",{"size":9.5,"bold":True,"color":(0,0,0)}),(q['source'],{"size":9.5,"color":(0,0,0)})])
        # 새 의학 해설: 문자열 또는 불릿 배열 (viewer bulletize 대응). 【왕족】 태그는 본문에서 제거.
        ne = q.get('new_expl')
        if isinstance(ne, list):
            runs(para("",9.5,after=1,indent=0.3), [("새 의학 해설: ",{"size":9.5,"bold":True,"color":(0,0,0)})])
            for it in ne: para("· " + strip_royal(it), 9.5, after=1, indent=0.6)
        elif ne:
            runs(para("",9.5,after=2,indent=0.3), [("새 의학 해설: ",{"size":9.5,"bold":True,"color":(0,0,0)}),(strip_royal(ne),{"size":9.5,"color":(0,0,0)})])
        render_rich(q)
        # 원본 보존(optional) — orig_ans/orig_expl 둘 다 없으면 블록 자체 생략
        oa, oe = q.get('orig_ans'), q.get('orig_expl')
        if oa or oe:
            hr(para("",2,after=3))
            if oa: runs(para("",9.5,after=(1 if oe else 8)), [("원본 답: ",{"size":9.5,"bold":True,"color":GRAY}),(oa,{"size":9.5,"color":GRAY})])
            if oe: runs(para("",9,after=8,indent=0.3), [("원본 해설: ",{"size":9,"bold":True,"color":GRAY}),(oe,{"size":9,"color":GRAY})])
        else:
            para("",2,after=8)  # 문항 간 간격

    total = sum(len(v) for _, v in SCOPES)
    missing_imgs = []   # _add_img 가 임베드하지 못한 이미지(파일 부재·--img 미지정) — 빌드 끝에 경고
    t = para(args.title, 18, True, NAVY, after=2); t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    s = para(args.subtitle + f" · 검증완료 {total}문항", 9, False, GRAY, after=2); s.alignment = WD_ALIGN_PARAGRAPH.CENTER
    lp = para("", 9, after=2); lp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    runs(lp, [("FLAG 7종: ",{"size":8.5,"bold":True,"color":GRAY}),
              ("ANSWER_MATCH·CORRECTED·DISPUTED · TEXT_RECONSTRUCTED · STEM_IMAGE_A_PRESENT · IMAGE_MISSING · SCOPE_RECLASSIFIED_OR_INFERRED",{"size":8.5,"color":GRAY})])
    note = para("", 8, False, GRAY, after=2); note.alignment = WD_ALIGN_PARAGRAPH.CENTER
    runs(note, [("‘출제 N회 (연도)’ = 수기 확인 출제연도 기준(미확인 문항은 in-scope 토큰유사도 추정)", {"size":8,"color":GRAY})])
    hr(para("",2,after=8))
    for head, qlist in SCOPES:
        scope_head(head)
        for q in sorted(qlist, key=yearkey):
            render(q)
    doc.save(args.out)
    print("SAVED:", args.out, "/ 문항수:", total)
    if missing_imgs:
        print("⚠ 임베드 못한 이미지 %d개(파일 없음/--img 미지정): %s"
              % (len(missing_imgs), missing_imgs[:20]))
        print("  → images 폴더와 questions_data.py 의 image/images 필드를 대조하세요.")

if __name__ == '__main__':
    main()

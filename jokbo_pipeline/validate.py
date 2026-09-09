# -*- coding: utf-8 -*-
"""
빌드 전 통합 검증 게이트 (과목 무관) — authoring 후 빌드 전에 이거 하나만 돌린다.

기존엔 coverage_audit → nospoiler_audit → build --strict-* 를 따로 돌렸다. validate.py 는
그 게이트들을 **한 번에** 묶고, build.py 에 없던 **스키마 필수필드 검사**까지 추가한다(빌드는 안 함).

검사:
  [스키마]   REQUIRED 필드 누락/빈값 = 에러 / years 미입력·미상 flag·채점불가 = 경고   ← 항상
  [무결성]   정답 인덱스·flag 그룹·이미지 플래그 정합성 = 에러 / 선지 마커 불연속·
             마크다운 잔존·이미지 설명 누락 = 경고                                   ← 항상
  [strict-detail]  imp·오답선지·충실한 new_expl 미달 = 에러                         ← --strict-detail
  [strict-meta]    교수명에 과/교실명 포함 = 에러                                    ← --strict-meta
  [strict-scope]   범위 오배치 의심 = 에러                                          ← --strict-scope
  [no-spoiler]     정답 노출 후보(정보)                                            ← --raw 무관, 끄려면 --no-nospoiler
  [coverage]       놓친 distinct 후보(정보)                                        ← --raw 있을 때만

에러가 하나라도 있으면 exit 1(빌드 막기용). 경고/정보 섹션은 종료코드에 영향 없음.

사용:
  python3 validate.py --data "$WORK/questions_data.py" --raw "$WORK/all_questions.json" \
      --inscope "2차,총론" --strict-detail --strict-meta --strict-scope
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

import schema
from build import detail_gaps, scope_misplacements, MIN_NEW_EXPL

HERE = Path(__file__).resolve().parent
MARKER_RE = re.compile(r"\s*[①-⑳]")   # ①–⑳


def _nonempty(v):
    if isinstance(v, (list, dict)):
        return len(v) > 0
    return bool(v and str(v).strip())


def schema_check(SCOPES):
    """REQUIRED 누락/빈값 = 에러, years 미입력·미상flag·채점불가 = 경고."""
    errors, warns = [], []
    for head, qs in SCOPES:
        sc = schema.clean_scope(head)
        for q in qs:
            tag = "[%s] %s" % (sc, q.get('meta', '?'))
            for f in schema.REQUIRED:
                if not _nonempty(q.get(f)):
                    errors.append("%s — 필수 '%s' 누락/빈값" % (tag, f))
            # 타입 검사: 텍스트 필드에 숫자 등 비문자열이 들어오면 빌더가 늦게(렌더 중) 죽는다 —
            # 게이트에서 조기에 막는다. new_expl 은 문자열 또는 불릿 리스트 둘 다 허용(빌더 계약).
            for f in ("meta", "stem", "verified"):
                v = q.get(f)
                if v is not None and not isinstance(v, str):
                    errors.append("%s — '%s' 는 문자열이어야 함(현재 %s)" % (tag, f, type(v).__name__))
            ne = q.get('new_expl')
            if ne is not None and not isinstance(ne, (str, list)):
                errors.append("%s — 'new_expl' 은 문자열 또는 리스트여야 함(현재 %s)" % (tag, type(ne).__name__))
            opts = q.get('options')
            if opts is not None and not isinstance(opts, list):
                errors.append("%s — options 는 리스트여야 함" % tag)
            ans = q.get('answers')
            if ans is not None:
                if not isinstance(ans, list):
                    errors.append("%s — answers 는 리스트여야 함" % tag)
                elif len(ans) == 1:
                    warns.append("%s — answers 길이 1(복수정답 아니면 생략, 단일정답은 verified 만)" % tag)
            # years 권장
            for f in schema.RECOMMENDED:
                if not _nonempty(q.get(f)):
                    warns.append("%s — 권장 '%s' 미입력(빌드 시 '연도 미확인')" % (tag, f))
            # 알 수 없는 flag
            for fl in (q.get('flags') or []):
                if fl not in schema.FLAG_TAXONOMY:
                    warns.append("%s — 알 수 없는 flag '%s'" % (tag, fl))
            # 채점 불가: 보기 있는데 정답 마커 없음(answers 없고 verified 가 ①–⑳ 로 시작 안 함)
            if isinstance(opts, list) and opts and not ans \
               and not MARKER_RE.match(str(q.get('verified', ''))):
                warns.append("%s — 채점 불가(options 有·정답 마커 없음 → 뷰어 미채점)" % tag)
    return errors, warns


# ─── 데이터 무결성 검사(감사 권고) — 의학적 정확성 이전의 '구조 일관성' ──────────
_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_ANS_GROUP = {"ANSWER_MATCH", "ANSWER_CORRECTED", "ANSWER_DISPUTED"}
_IMG_GROUP = {"STEM_IMAGE_A_PRESENT", "IMAGE_MISSING"}
_NEED_SOURCE = {"ANSWER_CORRECTED", "ANSWER_DISPUTED"}

# ─── 마크다운 잔존 검출 ───────────────────────────────────────────────────────
# build.py(DOCX)·viewer_template.html(뷰어) 어느 쪽도 마크다운을 파싱하지 않는다.
# `**강조**` 는 별표째 출력되고 학명 이탤릭 `*Klebsiella*` 도 마찬가지다.
# 오탐 주의: 치식 표기('*'/'**')처럼 별표가 '내용'인 경우가 있다 → 별표 안쪽이 비지 않고
# 양옆이 단어 경계인 '쌍'만 잡는다(단독 별표·공백 낀 별표는 통과).
_MD_RE = re.compile(
    r"\*\*(?=\S)[^*\n]{1,60}(?<=\S)\*\*"          # **강조**
    r"|(?<![\w*])\*(?=\S)[^*\n]{1,40}(?<=\S)\*(?![\w*])"   # *이탤릭*
)
# 마크다운을 훑을 텍스트 필드(리치블록 포함). 문자열·리스트·dict 값 모두 본다.
_PROSE_FIELDS = ("new_expl", "imp", "tip", "related_theory",
                 "wrong_option_explanations", "clinical_summary")


def _prose_texts(q):
    """문항에서 산문 텍스트를 모아 리스트로. 마크다운 검사 대상."""
    out = []
    for f in _PROSE_FIELDS:
        v = q.get(f)
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, list):
            out += [str(x) for x in v]
        elif isinstance(v, dict):
            out += [str(x) for x in v.values()]
    return out


def _marker_index(tok):
    """정답 마커를 1-based 정수로. '②'→2, '2'·'2번'→2, 해석불가면 None."""
    s = str(tok or "").strip()
    if not s:
        return None
    if s[0] in _CIRCLED:
        return _CIRCLED.index(s[0]) + 1
    m = re.match(r"(\d{1,2})", s)
    return int(m.group(1)) if m else None


def integrity_check(SCOPES):
    """구조 무결성 검사. (errors, warns) 반환. 에러는 빌드를 막는다.

    검사: 정답 인덱스 범위·중복, verified↔answers 일치, flag 그룹 상호배타,
          images↔image_captions 길이, years 형식, 정정/논쟁 source 필수(에러),
          STEM_IMAGE_A_PRESENT↔실제 이미지(에러), IMAGE_MISSING↔image_missing 설명,
          선지 마커 연속성, 해설의 마크다운 잔존, 동일 stem 중복(경고).
    """
    errors, warns = [], []
    seen = {}   # 정규화 stem → 최초 위치 tag (중복 탐지)
    for head, qs in SCOPES:
        sc = schema.clean_scope(head)
        for q in qs:
            tag = "[%s] %s" % (sc, q.get('meta', '?'))
            opts = q.get('options') or []
            nopt = len(opts)
            ans = q.get('answers')
            # 복수정답 마커: 범위·중복
            if isinstance(ans, list) and ans:
                idxs = []
                for a in ans:
                    i = _marker_index(a)
                    if i is None:
                        errors.append("%s — answers 항목 '%s' 마커 해석 불가" % (tag, a))
                    else:
                        idxs.append(i)
                        if nopt and i > nopt:
                            errors.append("%s — answers '%s'(=%d)이 선지 수(%d) 초과" % (tag, a, i, nopt))
                if len(idxs) != len(set(idxs)):
                    errors.append("%s — answers 중복 정답(%s)" % (tag, ans))
            # verified 선두 마커: 범위 + answers 와 일치
            vi = _marker_index(q.get('verified', ''))
            if vi is not None and nopt and vi > nopt:
                errors.append("%s — verified 정답(%d)이 선지 수(%d) 초과" % (tag, vi, nopt))
            if isinstance(ans, list) and ans and vi is not None:
                if vi not in [_marker_index(a) for a in ans]:
                    errors.append("%s — verified 선두(%d)가 answers 에 없음(불일치)" % (tag, vi))
            # flag 그룹 상호배타
            flags = set(q.get('flags') or [])
            if len(flags & _ANS_GROUP) > 1:
                errors.append("%s — answer_group flag 동시 다수: %s" % (tag, sorted(flags & _ANS_GROUP)))
            if len(flags & _IMG_GROUP) > 1:
                errors.append("%s — image_group flag 동시 다수: %s" % (tag, sorted(flags & _IMG_GROUP)))
            # 정정/논쟁은 근거(source) 필수
            if (flags & _NEED_SOURCE) and not _nonempty(q.get('source')):
                errors.append("%s — %s 인데 source(근거) 없음(정정/논쟁은 출처 필수)"
                              % (tag, ", ".join(sorted(flags & _NEED_SOURCE))))
            # 이미지 플래그 ↔ 실제 데이터 정합성.
            # questions_data_template.py 가 'image → STEM_IMAGE_A_PRESENT' 대응을 규약으로
            # 적어 두었지만 여태 강제가 없었다 — 플래그만 붙고 사진이 안 붙은 문항이
            # 조용히 지나간다(뷰어·DOCX 에 아무것도 안 나온다).
            has_img = bool(q.get('image')) or bool(q.get('images'))
            if 'STEM_IMAGE_A_PRESENT' in flags and not has_img:
                errors.append("%s — STEM_IMAGE_A_PRESENT 인데 image/images 없음"
                              "(사진을 붙였는지 확인하거나 IMAGE_MISSING 으로 바꿀 것)" % tag)
            if has_img and not (flags & _IMG_GROUP):
                warns.append("%s — 이미지가 있는데 image_group flag 없음"
                             "(STEM_IMAGE_A_PRESENT 권장)" % tag)
            # IMAGE_MISSING 은 '그 사진이 무엇이었는지' 한 줄이 있어야 뷰어의 [이미지 누락]
            # 표시가 정보 구실을 한다. 애초에 도판이 없던 문항에 플래그를 붙이는 오용도
            # 여기서 걸린다(없던 사진은 설명을 쓸 수 없다).
            has_missing_desc = _nonempty(q.get('image_missing'))
            if 'IMAGE_MISSING' in flags and not has_missing_desc:
                warns.append("%s — IMAGE_MISSING 인데 image_missing 설명 없음"
                             "(무슨 사진이었는지 한 줄; 원래 도판이 없던 문항이면 플래그를 뗄 것)" % tag)
            if has_missing_desc and 'IMAGE_MISSING' not in flags:
                warns.append("%s — image_missing 설명이 있는데 IMAGE_MISSING flag 없음" % tag)
            # 선지 마커 연속성. ①②③⑤ 처럼 건너뛰면 정답 번호와 실제 위치가 어긋난다.
            # 복원이 안 된 선지는 비우지 말고 "④ (족보에 복원되어 있지 않음)" 으로 채운다.
            midx = [_CIRCLED.index(o.strip()[0]) + 1
                    for o in opts if str(o).strip() and str(o).strip()[0] in _CIRCLED]
            if midx and midx != list(range(1, len(midx) + 1)):
                warns.append("%s — 선지 마커 불연속 %s(누락 선지는 플레이스홀더로 채울 것)"
                             % (tag, midx))
            # 마크다운 잔존 — 빌더가 파싱하지 않아 별표째 출력된다.
            for t in _prose_texts(q):
                m = _MD_RE.search(t)
                if m:
                    warns.append("%s — 해설에 마크다운 '%s'(빌더가 파싱 안 함 → 별표째 출력)"
                                 % (tag, m.group(0)[:40]))
                    break
            # images ↔ image_captions 길이
            imgs, caps = q.get('images'), q.get('image_captions')
            if isinstance(caps, list) and caps:
                n_imgs = (len(imgs) if isinstance(imgs, list) else 0) + (1 if q.get('image') else 0)
                if len(caps) > n_imgs:
                    errors.append("%s — image_captions(%d) > 이미지 수(%d) 길이 불일치" % (tag, len(caps), n_imgs))
            # years 형식(4자리 연도)
            for y in (q.get('years') or []):
                if not re.fullmatch(r"(?:19|20)\d{2}", str(y)):
                    errors.append("%s — years 비연도 값 '%s'" % (tag, y))
            # 동일 stem 중복(경고 — 정당한 변형일 수도 있어 차단은 안 함)
            key = re.sub(r"\s+", "", (q.get('stem') or ''))[:60]
            if key:
                if key in seen and seen[key] != tag:
                    warns.append("%s — 동일 stem 이 %s 와 중복(의도된 변형이면 무시)" % (tag, seen[key]))
                seen.setdefault(key, tag)
    return errors, warns


def gate_detail(SCOPES):
    return ["[%s] %s — 누락: %s" % (schema.clean_scope(h), q.get('meta', '?'), ", ".join(g))
            for h, qs in SCOPES for q in qs if (g := detail_gaps(q))]


def gate_meta(SCOPES):
    out = []
    for h, qs in SCOPES:
        for q in qs:
            dept = schema.split_prof(q.get('meta', ''))[1]
            if dept:
                out.append("[%s] %s — '%s' 제거(이름만)" % (schema.clean_scope(h), q.get('meta', ''), dept))
    return out


def gate_scope(SCOPES):
    out = []
    for cur, sug, meta, stem, ev, cs, bs in scope_misplacements(SCOPES):
        out.append("[%s] → 추천 [%s] (점수 %d→%d, 근거 %s) · %s · %s…"
                   % (cur, sug, cs, bs, ", ".join(ev), meta, stem))
    return out


def section(title, items, kind):
    """kind: 'err'(에러)·'warn'(경고)·'info'(정보)."""
    mark = {'err': '✗', 'warn': '△', 'info': 'ℹ'}[kind]
    print("\n%s %s (%d건)" % (mark, title, len(items)))
    for it in items[:60]:
        print("   " + it)
    if len(items) > 60:
        print("   … 외 %d건" % (len(items) - 60))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True)
    ap.add_argument('--raw', default='', help='all_questions.json — 있으면 커버리지 감사 실행')
    ap.add_argument('--inscope', default='', help='커버리지 감사 bucket(쉼표구분)')
    ap.add_argument('--strict-detail', action='store_true', help='자세한 authoring 미달을 에러로')
    ap.add_argument('--strict-meta', action='store_true', help='교수명 과/교실명 포함을 에러로')
    ap.add_argument('--strict-scope', action='store_true', help='범위 오배치 의심을 에러로')
    ap.add_argument('--no-nospoiler', action='store_true', help='no-spoiler 정보 섹션 건너뜀')
    ap.add_argument('--no-coverage', action='store_true', help='커버리지 정보 섹션 건너뜀')
    args = ap.parse_args()

    SCOPES = schema.load_scopes(args.data)
    total = sum(len(v) for _, v in SCOPES)
    print("=" * 70)
    print(" validate.py — 빌드 전 통합 검증  (문항 %d · 범위 %d)" % (total, len(SCOPES)))
    print("=" * 70)

    errors = []   # 종료코드 1 을 만드는 하드 에러 전부

    sch_err, warns = schema_check(SCOPES)
    if sch_err:
        section("스키마: 필수필드 누락/빈값·형식 오류", sch_err, 'err')
    errors += sch_err

    # 구조 무결성(항상 ON) — 의학정확성 이전의 데이터 일관성
    int_err, int_warn = integrity_check(SCOPES)
    if int_err:
        section("무결성: 정답범위·flag배타·길이·연도·출처 오류", int_err, 'err')
    errors += int_err
    warns += int_warn

    if args.strict_detail:
        d = gate_detail(SCOPES)
        section("strict-detail: 자세한 authoring 미달(≥%d자·imp·오답선지)" % MIN_NEW_EXPL, d, 'err')
        errors += d
    if args.strict_meta:
        m = gate_meta(SCOPES)
        section("strict-meta: 교수명에 과/교실명 포함", m, 'err')
        errors += m
    if args.strict_scope:
        s = gate_scope(SCOPES)
        section("strict-scope: 범위 오배치 의심", s, 'err')
        errors += s

    if warns:
        section("경고(종료코드 무관)", warns, 'warn')

    # ── 정보 섹션(종료코드 무관): 기존 audit 스크립트 재사용 ──────────────────
    # 정보 섹션 결과는 종료코드에 반영하지 않지만, 감사 스크립트 '자체의 크래시'(rc!=0)는
    # 조용히 넘기지 않는다 — 크래시가 '통과'처럼 보이면 감사가 없던 것과 같다.
    if not args.no_nospoiler:
        print("\n" + "─" * 70 + "\nℹ no-spoiler 감사 (정보 — 사람 검수)")
        r = subprocess.run([sys.executable, str(HERE / "nospoiler_audit.py"), "--data", args.data])
        if r.returncode != 0:
            warns.append("no-spoiler 감사 실행 실패(rc=%d) — 감사가 수행되지 않았습니다. 수동 실행으로 확인하세요." % r.returncode)
            print("△ no-spoiler 감사 실행 실패(rc=%d) — 위 출력 확인" % r.returncode)
    if args.raw and not args.no_coverage:
        print("\n" + "─" * 70 + "\nℹ 커버리지 감사 (정보)")
        cov = [sys.executable, str(HERE / "coverage_audit.py"), "--data", args.data, "--raw", args.raw]
        if args.inscope:
            cov += ["--inscope", args.inscope]
        r = subprocess.run(cov)
        if r.returncode != 0:
            warns.append("커버리지 감사 실행 실패(rc=%d) — 감사가 수행되지 않았습니다. 수동 실행으로 확인하세요." % r.returncode)
            print("△ 커버리지 감사 실행 실패(rc=%d) — 위 출력 확인" % r.returncode)

    print("\n" + "=" * 70)
    if errors:
        print(" 결과: ✗ 에러 %d건 — 빌드 차단(고친 뒤 재실행)" % len(errors))
        sys.exit(1)
    print(" 결과: ✓ 에러 0 (경고 %d건은 검토 권장). 빌드 진행 가능." % len(warns))


if __name__ == '__main__':
    main()

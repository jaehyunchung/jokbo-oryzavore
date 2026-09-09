# -*- coding: utf-8 -*-
"""No-spoiler 감사 (과목 무관) — 문제·도식·캡션이 정답을 노출하는지 전수 스캔.

초기 과목 작업 교훈: 이미지로 맞혀야 할 문항을 재구성하며 진단명을 stem 에 박거나,
참고 도식·캡션에 정답(장기·진단·판정)을 라벨링하거나, 복원 편집메모를 학생용 stem 에
남기면 문제가 무력화된다. 이 도구는 그 후보들을 찾아 사람 검수용으로 출력한다.

사용:
  python3 nospoiler_audit.py --data "$WORK/questions_data.py"

검사 항목:
  [1] 정답어 stem 노출 — verified 의 핵심어가 stem 에 그대로 등장(공통 불용어 제외).
  [2] 캡션 답 라벨    — image_caption 에 verified 핵심어가 등장(도식이 답을 표시).
  [3] 편집메모 leak   — 학생용 stem 에 복원 주석(※/원본/복원/소실/(…관련) 등) 잔존.
  ⚠ 전부 '후보'다(오탐 있음). 사람이 보고 판단한다. verified(정답란) 안의 주석은 답 영역이라 정상.
  ※ '도식-정답 불일치(오매칭)'는 자동 판정이 어려워 제외 — 가계도(미토/AD/XR) 등은 사람이 확인.
"""
import argparse, importlib.util, re

# 정답 핵심어 추출에서 빼는 일반어(노이즈). 과목 따라 build.py 상단처럼 조정 가능.
STOP = set((
    "것은 것을 옳은 옳지 않은 가장 적절 적절한 환자 소아 신생아 영아 진단 진단은 치료 처치 검사 "
    "설명 이다 있다 없다 한다 위해 대해 대한 다음 무엇 경우 모두 관련 양상 보이는 나타나는 시행 "
    "함유 종류 정도 원칙 질환 증후군 결핍 장애 발달 지연 연령 성별 아이 반사 출생 직후 수술 염색체 "
    "이상 disease syndrome reflex 그래프 곡선 사진 도식 가계도 pedigree 환아 소견 검진 평가"
).split())
EDIT_MARKERS = ["※", "원본은", "복원 과정", "보기 소실", "선지가 복원", "(이미지 누락)"]
# 편집메모로 보이는 괄호 패턴(복원 '사정' 설명 — 임상 '반사 소실' 등은 제외)
EDIT_PAREN = re.compile(r'\([^)]*(원본|복원|보기 소실|선지.*소실|미상|추정 재구성)[^)]*\)')
# 캡션이 진단명/유전양식을 적었는지(=도식·사진이 답을 노출) — 캡션엔 소견만 둬야 한다.
CAP_DIAG = re.compile(
    r'증후군|syndrome|disease|염\b|itis|melanosis|장염|괴사|핵형\s*47|'
    r'상염색체\s*(우성|열성)|X-?연관|반성유전|미토콘드리아|inheritance|autosomal|recessive|dominant')


def _core(ans):
    a = re.sub(r'^[①-⑳A-E\)\.\,\s]+', '', ans or '')
    a = re.sub(r'\([^)]*\)', '', a)
    a = re.sub(r'\s*[—\-].*$', '', a)            # ' — 논쟁/수정' 류 꼬리 제거
    a = re.sub(r'\s*원본.*$', '', a)
    return a.strip()


def _tokens(t):
    return [w for w in re.findall(r'[가-힣]{2,}|[A-Za-z]{4,}|\d{2},?X+Y*', t or '')
            if w not in STOP and len(w) >= 2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True)
    ap.add_argument('--show-ok', action='store_true', help='문제없는 문항도 카운트 출력')
    args = ap.parse_args()

    spec = importlib.util.spec_from_file_location('qd', args.data)
    qd = importlib.util.module_from_spec(spec); spec.loader.exec_module(qd)

    stem_leak, cap_leak, edit_leak = [], [], []
    total = 0
    for head, qs in qd.SCOPES:
        sc = re.split(r'·|\[', head)[0].strip()[:14]
        for q in qs:
            total += 1
            stem = q.get('stem', '')
            ctoks = _tokens(_core(q.get('verified', '')))
            leak = sorted(set(t for t in ctoks if t in stem))
            if leak:
                stem_leak.append((sc, q.get('meta', ''), leak, stem[:60]))
            # 단일 image_caption + 다중 image_captions[](v2 #4) 전부 감사 대상 — 다중 캡션만
            # 빼면 그쪽으로 새는 정답어를 못 잡는다(빌더가 image_captions 를 렌더한다).
            caps = [q.get('image_caption', '') or ''] + \
                   [str(c) for c in (q.get('image_captions') or []) if c]
            cap = ' '.join(c for c in caps if c)
            cleak = sorted(set(t for t in ctoks if t in cap))
            cdiag = CAP_DIAG.search(cap)
            if cleak or cdiag:
                why = cleak + ([f"진단명패턴:{cdiag.group(0)}"] if cdiag else [])
                cap_leak.append((sc, q.get('meta', ''), why, cap[:64]))
            em = [m for m in EDIT_MARKERS if m in stem] + EDIT_PAREN.findall(stem)
            if em or EDIT_PAREN.search(stem):
                edit_leak.append((sc, q.get('meta', ''), stem[:80]))

    def block(title, rows, fmt):
        print('=' * 74); print(f' {title}  ({len(rows)}건)'); print('=' * 74)
        for r in rows:
            print(fmt(r))
        print()

    block("[1] 정답어 stem 노출 후보 (오탐 多 — 진단명/정답항목 직접 노출만 진짜)",
          stem_leak, lambda r: f"  [{r[0]}] {r[1]:14} 노출={r[2]}\n      {r[3]}")
    block("[2] 캡션 답 라벨 후보 (도식 캡션이 정답어 포함 → 중립화)",
          cap_leak, lambda r: f"  [{r[0]}] {r[1]:14} 노출={r[2]}\n      {r[3]}")
    block("[3] 편집메모 leak 후보 (학생용 stem → recon/source 로 이동)",
          edit_leak, lambda r: f"  [{r[0]}] {r[1]:14} {r[2]}")

    print(f"문항 {total} · 후보: stem노출 {len(stem_leak)} / 캡션 {len(cap_leak)} / 편집메모 {len(edit_leak)}")
    print("→ 전부 사람 검수. 진단명·정답항목·판정의 직접 노출만 수정(정당한 임상 단서·전제는 유지).")


if __name__ == '__main__':
    main()

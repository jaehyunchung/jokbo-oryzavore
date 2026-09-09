# -*- coding: utf-8 -*-
"""
커버리지 감사 (과목 무관) — '놓친 distinct 문항' 방지용.

핵심 아이디어(신뢰 가능한 카운트 대조):
  raw 답마커 수  vs  authored 문항의 '출제연도 출현 합'(= Σ len(set(years))).
  왕족을 years로 제대로 병합했다면 authored 출현합이 raw 마커 수에 근접해야 한다.
  raw 마커가 출현합보다 크게 많은 toc/범위 = 아직 정리 안 된 distinct(또는 같은 해 중복)가 남은 곳.
  (퍼지 텍스트 매칭은 족보 stem 노이즈로 신뢰도가 낮아 1차 신호로 쓰지 않는다.)

사용:
  python3 coverage_audit.py --data "$WORK/questions_data.py" --raw "$WORK/all_questions.json" \
      [--inscope "2차,총론"] [--bucket 2차] [--head-map "총론=총론,수술=수술"]

과목 고유의 범위 이름은 코드에 넣지 않는다 — 번호 없는 범위 헤더는 --head-map 으로 넘긴다.

해석:
  - gap(=raw - 출현합)이 큰 toc부터 해당 페이지를 다시 읽어 distinct/주관식 문항을 보완.
  - gap 일부는 '같은 해 중복 마커'(복원자 중복 등)라 0까지 안 줄 수 있음 → gap 추세/상대비교로 판단.
  - years 미입력 문항이 많으면 출현합이 과소→gap 과대. years 채우면 정확해진다.
"""
import argparse, importlib.util, json
from collections import Counter


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True)
    ap.add_argument('--raw', required=True)
    ap.add_argument('--inscope', default='', help='쉼표구분 bucket(예 "2차,총론"). 비우면 전체')
    ap.add_argument('--bucket', default='2차',
                    help='번호형 범위 헤더("NN. …")를 묶을 bucket 이름 (기본 "2차")')
    ap.add_argument('--head-map', default='',
                    help='번호 없는 범위 헤더의 매핑. "키워드=버킷" 을 쉼표로 (예 "총론=총론,수술=수술")')
    args = ap.parse_args()

    spec = importlib.util.spec_from_file_location('qd', args.data)
    qd = importlib.util.module_from_spec(spec); spec.loader.exec_module(qd)

    raw = json.load(open(args.raw))
    inscope = set(x.strip() for x in args.inscope.split(',') if x.strip())
    if inscope:
        raw = [q for q in raw if ('bucket' not in q) or (q.get('bucket') in inscope)]

    # raw 키: bucket/toc 있으면 그걸로, 없으면 scope 라벨로
    def rawkey(q):
        if q.get('bucket') is not None or q.get('toc') is not None:
            return f"{q.get('bucket')}/toc{q.get('toc')}"
        return f"scope:{q.get('scope')}"
    raw_cnt = Counter(rawkey(q) for q in raw)

    # authored 키: 섹션 헤더 앞부분(범위 번호) 사용 + years 출현합/문항수
    auth_q = Counter(); auth_yr = Counter(); auth_noyear = Counter()
    # 섹션 헤더 → bucket/toc 추론(헤더 맨 앞 'NN.' 또는 키워드)
    import re
    head_map = []
    for pair in args.head_map.split(','):
        kw, sep, bucket = pair.partition('=')
        if sep and kw.strip() and bucket.strip():
            head_map.append((kw.strip(), bucket.strip()))

    def head_to_key(head):
        m = re.match(r'\s*(\d+)\.', head)
        if m: return f"{args.bucket}/toc{int(m.group(1))}"
        for kw, bucket in head_map:
            if kw in head: return f"{bucket}/tocNone"
        return head[:18]
    for head, qs in qd.SCOPES:
        k = head_to_key(head)
        for q in qs:
            auth_q[k] += 1
            ys = set(str(y) for y in q.get('years', []))
            if ys: auth_yr[k] += len(ys)
            else: auth_noyear[k] += 1

    keys = sorted(set(raw_cnt) | set(auth_q), key=lambda x: -(raw_cnt.get(x, 0) - auth_yr.get(x, 0)))
    print('=' * 70)
    print(' 커버리지 감사 — raw 마커 vs authored 출제연도 출현합 (gap 큰 곳 보완)')
    print('=' * 70)
    print(f"{'범위(bucket/toc)':22s} {'raw':>5s} {'문항':>5s} {'출현합':>6s} {'gap':>5s}  {'years미입력':>9s}")
    tot_raw = tot_q = tot_yr = 0
    for k in keys:
        r = raw_cnt.get(k, 0); nq = auth_q.get(k, 0); yr = auth_yr.get(k, 0); ny = auth_noyear.get(k, 0)
        gap = r - yr
        tot_raw += r; tot_q += nq; tot_yr += yr
        flag = '  ◀ 보완 권장' if (r and gap > max(5, r * 0.35)) else ''
        print(f"  {k:22s} {r:5d} {nq:5d} {yr:6d} {gap:5d}  {ny:9d}{flag}")
    print('-' * 70)
    print(f"  {'합계':22s} {tot_raw:5d} {tot_q:5d} {tot_yr:6d} {tot_raw-tot_yr:5d}")
    print('\n해석: gap = (같은 해 중복 마커) + (놓친 distinct). gap·비율 큰 toc부터 페이지 재독으로 보완.')
    print('      years 미입력 문항이 있으면 출현합 과소→gap 과대이니 years부터 채울 것.')


if __name__ == '__main__':
    main()

# -*- coding: utf-8 -*-
"""
test_imgwork.py — imgwork 도판 재배치의 비자명한 규칙 회귀 테스트.

검사: (문항, slot) 충돌 정리 — 페이지 경계를 넘는 정상 배치를 중복으로 오인하지 않는가,
      도판 하나가 여러 문항에 걸릴 때 한 문항만 떼어 내는가, 화소 예산 축소 비율.

실행: python3 jokbo_pipeline/tests/test_imgwork.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from imgwork import _dedup, _qids, MAX_PIXELS, MAX_SIDE  # noqa: E402

PASS = [0]
FAIL = [0]


def ok(cond, msg):
    if cond:
        PASS[0] += 1
    else:
        FAIL[0] += 1
        print("  ✗", msg)


def fig(n, qid, slot, verdict="attach"):
    return {"fig": n, "qid": qid, "slot": slot, "verdict": verdict,
            "box": [0.1, 0.1, 0.5, 0.5]}


def rec(src, page, figs):
    return {"src": src, "page": page, "figures": figs}


# _qids — 문자열과 배열 둘 다 받는다(한 도판이 여러 문항에 걸릴 수 있다)
ok(_qids({"qid": "S01Q001"}) == ["S01Q001"], "qid 문자열 → 1개")
ok(_qids({"qid": ["A", "B"]}) == ["A", "B"], "qid 배열 → 그대로")
ok(_qids({}) == [], "qid 없으면 빈 리스트")

# 같은 문항의 같은 slot 을 두 페이지가 주장 → 한쪽만 남는다
r1, r2 = rec("j", 10, [fig(1, "Q1", 1)]), rec("j", 20, [fig(1, "Q1", 1)])
dropped = _dedup([r1, r2])
ok(len(dropped) == 1, "동일 (문항, slot) 충돌 1건 정리")
kept = [r for r in (r1, r2) if r["figures"][0]["verdict"] == "attach"]
ok(len(kept) == 1, "충돌 시 한쪽만 attach 로 남는다")

# 페이지 경계를 넘는 정상 배치(slot 1 은 앞 페이지, 2~4 는 다음 페이지)는 건드리지 않는다
r1 = rec("j", 27, [fig(1, "Q2", 1)])
r2 = rec("j", 28, [fig(1, "Q2", 2), fig(2, "Q2", 3), fig(3, "Q2", 4)])
ok(_dedup([r1, r2]) == [], "slot 이 다르면 페이지가 달라도 충돌 아님")
ok(all(f["verdict"] == "attach" for r in (r1, r2) for f in r["figures"]),
   "페이지 경계를 넘는 도판은 모두 살아 있어야 한다")

# 도판 하나가 두 문항에 걸린 경우, 충돌한 문항만 떼고 도판 자체는 살린다
shared = fig(1, ["Qtopic", "Qappendix"], 1)
r1, r2 = rec("j", 45, [shared]), rec("e", 1, [fig(1, "Qappendix", 1)])
_dedup([r1, r2])
ok(shared["verdict"] == "attach", "다른 문항이 아직 쓰고 있으면 도판은 살아 있어야 한다")
ok(_qids(shared) == ["Qtopic"], "충돌한 문항만 qid 에서 빠진다")

# 도판이 더 많은 페이지를 대표로 채택한다(같은 문항의 나머지 도판과 흩어지지 않게)
r1 = rec("j", 98, [fig(1, "Q3", 1), fig(2, "Q9", 1)])
r2 = rec("j", 101, [fig(1, "Q3", 1)])
_dedup([r1, r2])
ok(r1["figures"][0]["verdict"] == "attach" and r2["figures"][0]["verdict"] == "duplicate",
   "도판이 많은 페이지를 대표로 채택")

# 화소 예산 — 긴 변만 제한하면 가로로 긴 다패널 크롭이 과도하게 커진다
def shrink(w, h):
    return min(1.0, (MAX_PIXELS / (w * h)) ** 0.5, MAX_SIDE / max(w, h))


ok(shrink(800, 600) == 1.0, "예산 안쪽 크롭은 축소하지 않는다")
big = shrink(3000, 2000)
ok(round(big * 3000 * big * 2000) <= MAX_PIXELS + 1, "축소 후 화소수가 예산 이하")
ok(shrink(4000, 300) * 4000 <= MAX_SIDE + 1, "가로로 긴 크롭은 긴 변 상한에 걸린다")

print(f"\n[test_imgwork] {PASS[0]} passed, {FAIL[0]} failed")
sys.exit(1 if FAIL[0] else 0)

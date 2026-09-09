# -*- coding: utf-8 -*-
"""
test_builders.py — jokbo_pipeline 파이썬 측 회귀 테스트(자기 소유 코드만).

schema.py(공유 스키마 헬퍼) · build.detail_gaps(자세한 authoring 게이트)를 본다.
(build_viewer 는 kd_library 소유라 kd_library/tests/test_build_viewer.py 에서 따로 테스트 —
 jokbo_pipeline 은 kd_library 없이 단독으로도 테스트가 돌아야 한다.)

실행: python3 tests/test_builders.py   (pytest 불필요, plain assert)
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent                       # jokbo_pipeline/
sys.path.insert(0, str(PIPE))

import schema                            # noqa: E402
from build import detail_gaps           # noqa: E402

PASS = [0]
FAIL = [0]


def ok(cond, msg):
    if cond:
        PASS[0] += 1
    else:
        FAIL[0] += 1
        print("  ✗", msg)


def eq(a, b, msg):
    ok(a == b, f"{msg}  (got {a!r}, want {b!r})")


# ── schema.py ────────────────────────────────────────────────────────────────
eq(schema.clean_scope("자궁경부암 · [2026 담당교수: 홍길동]"), "자궁경부암", "clean_scope 꼬리 제거")
eq(schema.scope_prof("자궁경부암 · [2026 담당교수: 홍길동]"), "홍길동", "scope_prof 담당교수")
eq(schema.split_prof("2023 · 예시과 김철수"), ("2023", "예시과", "김철수"), "split_prof 과/교실 분리")
eq(schema.split_prof("2023 · 김철수"), ("2023", "", "김철수"), "split_prof 이미 이름만")
eq(schema.meta_nameonly("2023 · 예시과 김철수"), "2023 · 김철수", "meta_nameonly 이름만")
ok(schema.is_royal({"new_expl": "【왕족】 핵심"}), "is_royal 문자열")
ok(schema.is_royal({"new_expl": ["【왕족】 a", "b"]}), "is_royal 불릿배열")
ok(schema.is_royal({"new_expl": "【킹왕족】 x"}), "is_royal 킹왕족 별칭")
ok(not schema.is_royal({"new_expl": "일반"}), "is_royal 태그없음")
eq(schema.strip_royal("【왕족】 핵심"), "핵심", "strip_royal 태그 제거")
eq(schema.strip_royal("【킹왕족】 x"), "x", "strip_royal 킹왕족 별칭 제거")
eq(schema.n_correct({}), 1, "n_correct 기본 1")
eq(schema.n_correct({"answers": ["②", "④"]}), 2, "n_correct 복수")
eq(schema.n_correct({"answers": []}), 1, "n_correct 빈 answers → 1")
eq(schema.as_text(["a", "b"]), "a b", "as_text 리스트")
eq(schema.as_text("x"), "x", "as_text 문자열")
eq(schema.as_text(None), "", "as_text None")

status = schema.scope_status(
    "총론 · [2026 담당교수: 이몽룡·성춘향]", {"임꺽정", "성춘향"}
)
eq(status["status"], "same", "scope_status (a) 복수 교수 중 동일 교수 우선")
eq(status["weight"], 1.0, "scope_status (a) 동일 교수 weight")
eq(status["tokens"], ["이몽룡", "성춘향"], "scope_status (a) raw 토큰 배열")

status = schema.scope_status(
    "… · [2026 담당교수: 미개설 (2025 장보고)]", {"장보고"}
)
eq(status["status"], "closed", "scope_status (b) 미개설 우선")
eq(status["weight"], 0.3, "scope_status (b) 미개설 weight")

status = schema.scope_status(
    "… · [2026 담당교수: 임꺽정(세부단원 신설) · CPX 미개설]", {"강감찬", "유관순"}
)
eq(status["status"], "new", "scope_status (c) 신설이 미개설보다 높은 weight")
eq(status["weight"], 0.7, "scope_status (c) 신설 weight")
eq(
    status["tokens"],
    ["임꺽정(세부단원 신설)", "CPX 미개설"],
    "scope_status (c) 괄호를 보존한 raw 토큰",
)

status = schema.scope_status("부록 — 2022학년도 원본 시험지", {"아무개"})
eq(
    status,
    {"status": "unknown", "weight": 1.0, "prof2026": "", "tokens": []},
    "scope_status (d) 교수란 없는 헤더",
)

changed = schema.scope_status("… · [2026 담당교수: 김구]", {"안중근"})
eq(changed["status"], "changed", "scope_status (e) 담당교수 변경")
eq(changed["weight"], 0.7, "scope_status (e) 변경 weight")
same = schema.scope_status("… · [2026 담당교수: 김구]", {"김구"})
eq(same["status"], "same", "scope_status (f) 담당교수 동일")

status = schema.scope_status("… · [2026 담당교수: 미정 (2025 김유신)]", {"김유신"})
eq(status["status"], "unknown", "scope_status (g) 미정은 과거 교수와 무관하게 unknown")
eq(status["weight"], 1.0, "scope_status (g) 미정 weight")

status = schema.scope_status("… · [2026 담당교수: 임꺽정(세부단원 신설)]", {"임꺽정"})
eq(status["status"], "new", "scope_status (h) 신설은 동일 교수보다 우선")

unknown_status = {"status": "unknown", "weight": 1.0, "prof2026": "", "tokens": []}
eq(schema.scope_status("", set()), unknown_status, "scope_status 빈 헤더")
eq(schema.scope_status(None, None), unknown_status, "scope_status None 입력")

# ── build.detail_gaps (strict-detail 게이트) ─────────────────────────────────
full = {"new_expl": "충분히 긴 해설" * 5, "imp": "한 줄 핵심",
        "options": ["①a", "②b", "③c"], "verified": "①a",
        "wrong_option_explanations": ["② 오답", "③ 오답"]}
eq(detail_gaps(full), [], "detail_gaps 충족 → 빈 리스트")
bare = {"new_expl": "짧음", "options": ["①a", "②b"], "verified": "①a"}
ok(len(detail_gaps(bare)) >= 2, "detail_gaps 미달(new_expl 짧음·imp 없음·오답선지 없음)")
# 복수정답: 오답선지 필요수 = 보기 - 정답수
multi = {"new_expl": "충분히 긴 해설" * 5, "imp": "x", "options": ["①a", "②b", "③c", "④d"],
         "verified": "②④", "answers": ["②", "④"], "wrong_option_explanations": ["① 오답", "③ 오답"]}
eq(detail_gaps(multi), [], "복수정답 오답선지 need=보기-정답수 반영")

print(f"\n[test_builders] {PASS[0]} passed, {FAIL[0]} failed")
sys.exit(1 if FAIL[0] else 0)

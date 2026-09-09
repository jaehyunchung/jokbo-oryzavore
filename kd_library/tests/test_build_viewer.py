# -*- coding: utf-8 -*-
"""
test_build_viewer.py — build_viewer.build_questions 회귀 테스트.

주관식 가드(options 키 항상 보장 → 뷰어 q.options.map 크래시 차단)·이미지 base64 인라인·
없는 이미지 보고·빈 optional 제거·clean_scope 적용을 본다.

실행: python3 tests/test_build_viewer.py   (pytest 불필요, plain assert)
"""
import base64
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
KD = HERE.parent                         # kd_library/
ROOT = KD.parent
sys.path.insert(0, str(ROOT))

from kd_library import build_viewer      # noqa: E402

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


# 1x1 PNG (투명) — 이미지 인라인 테스트용
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)

with tempfile.TemporaryDirectory() as td:
    imgdir = Path(td)
    (imgdir / "pic.png").write_bytes(_PNG)
    scopes = [(
        "범위A · [2026 담당교수: 김]",
        [
            {"meta": "2023 · 김", "stem": "s1", "options": ["①a", "②b"], "verified": "②b",
             "new_expl": "해설", "image": "pic.png", "source": ""},          # source 빈값 → 제거
            {"meta": "2022 · 이", "stem": "주관식", "verified": "서술", "new_expl": "해설"},  # 주관식(options 없음)
            {"meta": "2021 · 박", "stem": "s3", "options": ["①a"], "verified": "①a",
             "new_expl": "해설", "image": "nope.png"},                        # 이미지 파일 없음
            {"meta": "2020 · 최", "stem": "s4", "options": ["①a"], "verified": "①a",
             "new_expl": "해설", "image_missing": "원본 PDF에 없음"},          # image_missing 플래그
        ],
    )]
    items, missing = build_viewer.build_questions(scopes, imgdir)

eq(len(items), 4, "build_questions 4문항")
ok(all("options" in it for it in items), "모든 item 에 options 키 보장(주관식 크래시 방지)")
eq(items[1]["options"], [], "주관식 → options == []")
ok(items[0]["image"].startswith("data:image/"), "이미지 base64 인라인")
ok("source" not in items[0], "빈 optional(source) 제거")
eq(items[0]["scope"], "범위A", "scope 는 clean_scope 적용")
eq(items[0]["scope_order"], 0, "scope_order 부여")
eq(missing, ["nope.png"], "없는 이미지 파일은 missing 으로 보고")
eq(items[2].get("image_missing_file"), "nope.png", "없는 파일 → image_missing_file")
ok(items[3].get("image_missing") is True, "image_missing 플래그 → True")


duplicate_prefix = "가" * 60
duplicate_scopes = [(
    "중복 범위 · [2026 담당교수: 박]",
    [
        {"meta": "2021 · 박", "stem": duplicate_prefix + "첫째", "verified": "①"},
        {"meta": "2021 · 박", "stem": duplicate_prefix + "둘째", "verified": "②"},
        {"meta": "2020 · 최", "stem": duplicate_prefix + "고유", "verified": "③"},
        {"meta": "2021 · 박", "stem": "완전히 고유한 문항", "verified": "④"},
    ],
)]
duplicate_items, _ = build_viewer.build_questions(duplicate_scopes, Path("unused-images"))
duplicate_groups = build_viewer.find_duplicate_qids(duplicate_items)

eq(len(duplicate_groups), 1, "qid가 같은 그룹만 1건 감지")
eq(len(duplicate_groups[0]), 2, "중복 qid 그룹은 충돌한 두 문항만 포함")
eq([item["verified"] for item in duplicate_groups[0]], ["①", "②"],
   "stem 60자 뒤와 verified가 달라도 qid 충돌로 판정")


fixture = HERE / "fixtures" / "smoke_questions_data.py"
template = KD / "viewer_template.html"
builder = KD / "build_viewer.py"

with tempfile.TemporaryDirectory() as td:
    out_dir = Path(td)
    full_out = out_dir / "full.html"
    light_out = out_dir / "light.html"
    common_cmd = [
        sys.executable,
        str(builder),
        "--data", str(fixture),
        "--template", str(template),
        "--title", "전날 모드 스모크",
        "--subject", "테스트",
        "--storage-key", "jeonnal_smoke",
    ]
    full_run = subprocess.run(
        [*common_cmd, "--out", str(full_out)], capture_output=True, text=True,
    )
    light_run = subprocess.run(
        [*common_cmd, "--out", str(light_out), "--no-jeonnal"],
        capture_output=True,
        text=True,
    )

    ok(full_run.returncode == 0, "실제 템플릿+공용 픽스처 full 빌드 성공")
    ok(full_out.exists(), "full 빌드 출력 파일 생성")
    full_html = full_out.read_text(encoding="utf-8") if full_out.exists() else ""
    ok("const APP_DATA=" in full_html and '"questions": [' in full_html,
       "full 빌드 출력에 APP_DATA 문항 배열 포함")
    ok("임신 후기 무통성 질출혈" in full_html and "갑상선자극호르몬" in full_html,
       "full 빌드 APP_DATA 에 픽스처 문항 포함")

    ok(light_run.returncode == 0, "실제 템플릿+공용 픽스처 light 빌드 성공")
    light_html = light_out.read_text(encoding="utf-8") if light_out.exists() else ""
    eq(light_html.count("JEONNAL"), 0, "light 빌드에서 JEONNAL 마커 완전 제거")
    eq(light_html.count('onclick="jn'), 0, "light 빌드에서 jn onclick 완전 제거")
    eq(light_html.count("function jnPriority("), 1, "light 빌드에서 jnPriority 선언 정확히 1개")
    eq(light_html.count("function scopeStatus("), 1, "light 빌드에서 scopeStatus 선언 정확히 1개")
    eq(light_html.count("function jnCoverage("), 1, "light 빌드에서 jnCoverage 선언 정확히 1개")
    eq(light_html.count("function jnStudyCostFromStat("), 1,
       "light 빌드에서 jnStudyCostFromStat 선언 정확히 1개")
    ok(light_out.exists() and full_out.exists()
       and light_out.stat().st_size < full_out.stat().st_size,
       "light 빌드 바이트 크기는 full 빌드보다 작음")

    script_start = light_html.find("<script>")
    script_end = light_html.rfind("</script>")
    js_path = out_dir / "light.js"
    if script_start >= 0 and script_end > script_start:
        js_path.write_text(
            light_html[script_start + len("<script>"):script_end], encoding="utf-8",
        )
        node_run = subprocess.run(
            ["node", "--check", str(js_path)], capture_output=True, text=True,
        )
        ok(node_run.returncode == 0, "light 빌드 출력에서 추출한 JS가 node --check 통과")
    else:
        ok(False, "light 빌드 출력의 script 구획을 찾을 수 있음")


malformed = """<!doctype html>
<!-- JEONNAL:START -->
<script>/* JEONNAL:START *//* JEONNAL:END *//*__DATA__*/</script>
"""
try:
    build_viewer.validate_jeonnal_markers(malformed)
    malformed_error = ""
except SystemExit as exc:
    malformed_error = str(exc)
ok(malformed_error.startswith("템플릿의 JEONNAL 마커가 손상되었습니다:"),
   "손상된 marker pair는 명확한 한국어 오류로 중단")

print(f"\n[test_build_viewer] {PASS[0]} passed, {FAIL[0]} failed")
sys.exit(1 if FAIL[0] else 0)

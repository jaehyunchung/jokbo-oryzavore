#!/usr/bin/env bash
# 족보 오리자보어 정본 파이프라인 회귀 테스트 — 편집/빌드 전에 돌릴 것.
#   ./run_tests.sh
# 종료코드 0 = 전부 통과. 하나라도 실패하면 비0.
# 파이프라인·뷰어의 핵심 로직 회귀만 본다(빌드는 하지 않는다).
set -u
cd "$(dirname "$0")"
fail=0

run() { echo "── $1"; shift; "$@" || fail=1; echo; }

echo "==== 1) 문법 컴파일 체크 ===="
python3 -m py_compile jokbo_pipeline/*.py kd_library/build_viewer.py || fail=1
echo

echo "==== 2) 파이썬 회귀 테스트 ===="
run "extract.count/split_blind_key"     python3 jokbo_pipeline/tests/test_extract.py
run "extract_cols 2단 분리"             python3 jokbo_pipeline/tests/test_extract_cols.py
run "v2 파싱 6대 개선(extract helpers)"  python3 jokbo_pipeline/tests/test_extract_improvements.py
run "validate 무결성(정답범위·flag·이미지·마크다운)" python3 jokbo_pipeline/tests/test_validate_integrity.py
run "llm_segment 포인터맵 절단·검증"     python3 jokbo_pipeline/tests/test_llm_segment.py
run "schema + build.detail_gaps"         python3 jokbo_pipeline/tests/test_builders.py
run "batch_stats 배치 통계"              python3 jokbo_pipeline/tests/test_batch_stats.py
run "main.py lifecycle 통합"            python3 jokbo_pipeline/tests/test_main_lifecycle.py
run "build_viewer.build_questions"       python3 kd_library/tests/test_build_viewer.py

echo "==== 3) JS 엔진 회귀 테스트 (뷰어 채점/키 로직) ===="
run "viewer_template 엔진"               node kd_library/tests/test_engine.js

echo "===================================================="
if [ "$fail" -eq 0 ]; then
  echo "✓ 전체 통과"
else
  echo "✗ 실패 있음 — 위 로그 확인"
fi
exit $fail

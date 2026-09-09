# -*- coding: utf-8 -*-
import importlib
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Final, Protocol, TypeVar, runtime_checkable

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
CLI = ROOT / "jokbo_pipeline" / "batch_stats.py"
FIXTURE = ROOT / "kd_library" / "tests" / "fixtures" / "smoke_questions_data.py"
sys.path.insert(0, str(ROOT))

from jokbo_pipeline.batch_stats import Stats


@runtime_checkable
class JsonApi(Protocol):
    def loads(self, value: str) -> Stats: ...

PASS = [0]
FAIL = [0]
T = TypeVar("T")
json_module = importlib.import_module("json")
assert isinstance(json_module, JsonApi)
json_api: Final[JsonApi] = json_module


def ok(cond: bool, msg: str) -> None:
    if cond:
        PASS[0] += 1
    else:
        FAIL[0] += 1
        print("  ✗", msg)


def eq(actual: T, expected: T, msg: str) -> None:
    ok(actual == expected, f"{msg}  (got {actual!r}, want {expected!r})")


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


# Given: 3개 범위·6문항인 공용 스모크 픽스처
# When: JSON 통계를 요청
fixture_result = run_cli("--data", str(FIXTURE), "--json")
# Then: 총계·연도·왕족·선택 필드 사용률이 정확하다.
eq(fixture_result.returncode, 0, "픽스처 JSON CLI exit 0")
if fixture_result.returncode == 0:
    fixture_stats = json_api.loads(fixture_result.stdout)
    eq(fixture_stats["total_questions"], 6, "총 문항 수")
    eq(
        fixture_stats["year_counts"],
        {"2025": 1, "2024": 1, "2023": 2, "2022": 2,
         "2021": 2, "2020": 1, "2019": 1},
        "연도별 출현 수",
    )
    eq(fixture_stats["royal_count"], 2, "왕족 수")
    for field in (
        "imp", "tip", "wrong_option_explanations", "image|images", "answers",
        "recon", "scope_note", "source",
    ):
        eq(
            fixture_stats["field_usage"][field],
            {"count": 0, "percent": 0.0},
            f"{field} 사용률",
        )
    ok(
        all("status" in scope for scope in fixture_stats["scopes"]),
        "JSON 범위표에 status 열 존재",
    )


# Given: 공용 스모크 픽스처
# When: 기본 마크다운 통계를 요청
markdown_result = run_cli("--data", str(FIXTURE))
# Then: 범위표에 상태 열이 있다.
eq(markdown_result.returncode, 0, "픽스처 Markdown CLI exit 0")
ok(
    "| 범위 | 문항 수 | 2026 담당 | 상태 |" in markdown_result.stdout,
    "Markdown 범위표 상태 열 존재",
)


# Given: 2026 담당교수와 과거 출제교수가 같은 합성 데이터
with tempfile.TemporaryDirectory() as temp_dir:
    synthetic_data = Path(temp_dir) / "questions_data.py"
    _ = synthetic_data.write_text(
        "\n".join(
            [
                "SCOPES = [(",
                "    '단위 · [2026 담당교수: 김철수]',",
                "    [{'meta': '2025 · 김철수', 'years': ['2025'], "
                + "'stem': '합성 문항', 'verified': '정답', 'new_expl': '해설'}],",
                ")]",
            ]
        ),
        encoding="utf-8",
    )
    # When: 합성 데이터의 JSON 통계를 요청
    same_result = run_cli("--data", str(synthetic_data), "--json")

# Then: split_prof의 이름 부분으로 비교되어 same이다.
eq(same_result.returncode, 0, "합성 same CLI exit 0")
if same_result.returncode == 0:
    same_stats = json_api.loads(same_result.stdout)
    eq(same_stats["scopes"][0]["status"], "same", "합성 헤더 상태")


# Given: questions_data.py가 없는 작업 폴더
with tempfile.TemporaryDirectory() as temp_dir:
    # When: --work로 통계를 요청
    missing_result = run_cli("--work", temp_dir)
# Then: 조립 선행 안내와 exit 1을 반환한다.
eq(missing_result.returncode, 1, "questions_data.py 누락 exit 1")
ok(
    "먼저 assemble.py 를 실행하세요" in missing_result.stdout + missing_result.stderr,
    "questions_data.py 누락 안내",
)


# Given/When: 상호 배타 인자를 동시에 주거나 모두 생략
conflict_result = run_cli("--data", "a", "--work", "b")
empty_result = run_cli()
# Then: argparse가 두 경우를 모두 exit 2로 거부한다.
eq(conflict_result.returncode, 2, "--data/--work 동시 지정 exit 2")
eq(empty_result.returncode, 2, "입력 인자 없음 exit 2")


print(f"\n[test_batch_stats] {PASS[0]} passed, {FAIL[0]} failed")
sys.exit(1 if FAIL[0] else 0)

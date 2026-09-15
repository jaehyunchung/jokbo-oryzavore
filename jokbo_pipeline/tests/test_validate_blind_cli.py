import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
CLI = ROOT / "jokbo_pipeline" / "validate.py"

PASS = [0]
FAIL = [0]


def ok(cond, msg):
    if cond:
        PASS[0] += 1
    else:
        FAIL[0] += 1
        print("  ✗", msg)


def run_cli(data_path, *args):
    return subprocess.run(
        [sys.executable, str(CLI), "--data", str(data_path), "--no-nospoiler", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def write_fixture(path, with_blind):
    question: dict[str, object] = {
        "meta": "2025 · 홍길동",
        "years": ["2025"],
        "stem": "합성 문항?",
        "options": ["① 첫째", "② 둘째"],
        "verified": "②",
        "new_expl": "합성 해설",
    }
    if with_blind:
        question.update({
            "qid": "synthetic-001",
            "blind": {
                "verified": "①",
                "note": "정답을 보지 않고 독립적으로 풀이함",
                "confidence": "high",
            },
        })
    path.write_text("SCOPES = " + repr([("예시범위", [question])]) + "\n", encoding="utf-8")


def write_noisy_fixture(path):
    professors = ["홍길동", "이몽룡", "성춘향"]
    questions = [
        {
            "meta": f"2025 · {professors[index % len(professors)]}",
            "years": [],
            "stem": f"합성 문항 {index + 1}?",
            "options": ["① 첫째", "② 둘째"],
            "verified": "②",
            "new_expl": "합성 해설",
        }
        for index in range(61)
    ]
    path.write_text("SCOPES = " + repr([("예시과", questions)]) + "\n", encoding="utf-8")


with tempfile.TemporaryDirectory() as temp_dir:
    missing_data = Path(temp_dir) / "missing_blind.py"
    complete_data = Path(temp_dir) / "complete_blind.py"
    noisy_data = Path(temp_dir) / "noisy_missing_blind.py"
    write_fixture(missing_data, with_blind=False)
    write_fixture(complete_data, with_blind=True)
    write_noisy_fixture(noisy_data)

    missing_default = run_cli(missing_data)
    missing_strict = run_cli(missing_data, "--strict-blind")
    complete_strict = run_cli(complete_data, "--strict-blind")
    complete_default = run_cli(complete_data)
    noisy_default = run_cli(noisy_data)
    noisy_strict = run_cli(noisy_data, "--strict-blind")

ok(missing_default.returncode == 0,
   "blind 없는 데이터의 기본 모드는 exit 0")
ok("블라인드 답(blind) 없는 문항 1/1" in missing_default.stdout,
   "blind 없는 데이터의 기본 모드는 단일 요약 경고")
ok(missing_strict.returncode == 1,
   "blind 없는 데이터의 --strict-blind는 exit 1"
   f" (rc={missing_strict.returncode}, stderr={missing_strict.stderr.strip()!r})")
ok("strict-blind:" in missing_strict.stdout,
   "blind 없는 데이터의 --strict-blind는 오류 섹션 출력")
ok(complete_strict.returncode == 0,
   "정상 blind+qid 데이터의 --strict-blind는 exit 0"
   f" (rc={complete_strict.returncode}, stderr={complete_strict.stderr.strip()!r})")
ok(complete_default.returncode == 0,
   "정상 blind+qid 데이터의 기본 모드는 exit 0")
ok("블라인드 답(blind) 없는 문항" not in complete_default.stdout,
   "정상 blind+qid 데이터의 기본 모드는 누락 경고 없음")
ok(noisy_default.returncode == 0,
   "60건 초과 기존 경고가 있어도 기본 모드는 exit 0")
ok("블라인드 답(blind) 없는 문항 61/61" in noisy_default.stdout,
   "60건 초과 기존 경고 뒤에서도 blind 누락 요약이 stdout에 표시됨")
ok(noisy_strict.returncode == 1,
   "60건 초과 기존 경고가 있는 데이터의 --strict-blind는 exit 1"
   f" (rc={noisy_strict.returncode}, stderr={noisy_strict.stderr.strip()!r})")

print(f"\n[test_validate_blind_cli] {PASS[0]} passed, {FAIL[0]} failed")
sys.exit(1 if FAIL[0] else 0)

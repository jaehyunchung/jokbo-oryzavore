import argparse
import ast
import json
import pprint
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from docx import Document


HERE = Path(__file__).resolve().parent
PIPE = HERE.parent
ROOT = PIPE.parent
CLI = PIPE / "blindwork.py"
VALIDATE = PIPE / "validate.py"
DOCX_BUILD = PIPE / "build.py"
VIEWER_BUILD = ROOT / "kd_library" / "build_viewer.py"
VIEWER_TEMPLATE = ROOT / "kd_library" / "viewer_template.html"
DEFAULT_FIXTURES = HERE / "fixtures" / "blindwork"
SENTINEL = "BLIND_SENTINEL_7f3a"
QID_PREFIX = '"qid": "u01_예시단위#'
SUMMARY = (
    "E2E OK · validate rc=0 · audit match · dispositions enforced · "
    "sentinel absent (html,docx) · sentinel probe positive · brief literals pass key-rules"
)
KEY_RULE_MESSAGES = ("허용되지 않은 키", "이 단계는 해설만")
COMMAND_TIMEOUT = 60


def run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=COMMAND_TIMEOUT,
    )


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return run_command([sys.executable, str(CLI), *args])


def require_rc(
    result: subprocess.CompletedProcess[str], expected: int, label: str
) -> None:
    assert result.returncode == expected, (
        f"{label} 종료코드가 {result.returncode}입니다(기대 {expected}).\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def parse_json(text: str) -> object:
    return cast(object, json.loads(text))


def load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return parse_json(handle.read())


def copy_stage(fixtures: Path, fixture_name: str, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    _ = shutil.copy2(fixtures / "stages" / fixture_name, target)
    return target


def extract_brief_literal(path: Path, name: str) -> list[dict[str, object]]:
    text = path.read_text(encoding="utf-8")
    blocks: list[str] = re.findall(r"```python\s*\n(.*?)```", text, flags=re.DOTALL)
    for block in blocks:
        tree = ast.parse(block, filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == name:
                value = cast(object, ast.literal_eval(node.value))
                assert isinstance(value, list), f"{path.name}의 {name} 예시는 목록이어야 합니다"
                values = cast(list[object], value)
                assert all(isinstance(row, dict) for row in values), (
                    f"{path.name}의 {name} 예시는 dict 목록이어야 합니다"
                )
                return cast(list[dict[str, object]], values)
    raise AssertionError(f"{path.name}에서 {name} 예시 리터럴을 찾지 못했습니다")


def write_brief_stage(
    work: Path,
    brief_name: str,
    literal_name: str,
    qids: Sequence[str],
    relative_path: str,
) -> Path:
    rows = extract_brief_literal(PIPE / brief_name, literal_name)
    assert len(rows) == len(qids), (
        f"{brief_name} 예시 문항 수가 바뀌었습니다: {len(rows)}개(기대 {len(qids)}개)"
    )
    for row, qid in zip(rows, qids):
        row["qid"] = qid
    target = work / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    _ = target.write_text(
        f"{literal_name} = {pprint.pformat(rows, width=108, sort_dicts=False)}\n",
        encoding="utf-8",
    )
    return target


def check_brief_literals(work: Path) -> None:
    cases = (
        (
            "BRIEF_solve.md",
            "SOLVED",
            "solve",
            ["u01_예시단위#003"],
            "brief/solve/u01_예시단위__t01.py",
        ),
        (
            "BRIEF_adjudicate.md",
            "ADJUDICATED",
            "adjudicate",
            ["u01_예시단위#002", "u01_예시단위#004", "u01_예시단위#006"],
            "brief/adjudicate/u01_예시단위.py",
        ),
        (
            "BRIEF_explain.md",
            "EXPLAINED",
            "explain",
            ["u01_예시단위#005", "u01_예시단위#002"],
            "brief/explain/u01_예시단위.py",
        ),
    )
    for brief_name, literal_name, stage, qids, relative_path in cases:
        path = write_brief_stage(work, brief_name, literal_name, qids, relative_path)
        result = run_cli("check", "--work", str(work), "--stage", stage, str(path))
        output = result.stdout + result.stderr
        for message in KEY_RULE_MESSAGES:
            assert message not in output, (
                f"{brief_name} 예시가 {stage} 키 규칙을 위반했습니다: {message}\n{output}"
            )


def run_e2e(fixtures: Path) -> None:
    assert fixtures.is_dir(), f"픽스처 폴더가 없습니다: {fixtures}"
    for required in ("batches", "stages", "images", "expected.json"):
        assert (fixtures / required).exists(), f"필수 픽스처가 없습니다: {fixtures / required}"

    work = Path(tempfile.mkdtemp())
    try:
        result = run_cli(
            "split", "--batches", str(fixtures / "batches"), "--work", str(work)
        )
        require_rc(result, 0, "split")
        result = run_cli("slice", "--work", str(work))
        require_rc(result, 0, "slice")

        solved_text = copy_stage(
            fixtures, "solved_ok__t01.py", work / "solved" / "u01_예시단위__t01.py"
        )
        solved_image = copy_stage(
            fixtures, "solved_ok__i01.py", work / "solved" / "u01_예시단위__i01.py"
        )
        for solved in (solved_text, solved_image):
            result = run_cli(
                "check", "--work", str(work), "--stage", "solve", str(solved)
            )
            require_rc(result, 0, f"solve 검사({solved.name})")

        expected_value = load_json(fixtures / "expected.json")
        assert isinstance(expected_value, dict), "expected.json 최상위 값은 객체여야 합니다"
        expected = cast(dict[str, object], expected_value)
        result = run_cli("scan", "--work", str(work), "--json")
        require_rc(result, 0, "scan")
        assert parse_json(result.stdout) == expected["scan"], (
            f"scan JSON이 기대값과 다릅니다.\n실제: {result.stdout}\n기대: {expected['scan']!r}"
        )

        adjudicated = copy_stage(
            fixtures,
            "adjudicated_ok.py",
            work / "_reconcile" / "adjudicated" / "u01_예시단위.py",
        )
        result = run_cli(
            "check", "--work", str(work), "--stage", "adjudicate", str(adjudicated)
        )
        require_rc(result, 0, "adjudicate 검사")
        result = run_cli("resolve", "--work", str(work))
        require_rc(result, 0, "resolve")

        explained = copy_stage(
            fixtures,
            "explained_objection.py",
            work / "_reconcile" / "explained" / "u01_예시단위.py",
        )
        result = run_cli(
            "check", "--work", str(work), "--stage", "explain", str(explained)
        )
        require_rc(result, 0, "explain 검사")

        for output_flag, output_path in (
            ("--out-batches", work / "batches"),
            ("--out-data", work / "questions_data.py"),
        ):
            result = run_cli(
                "build", "--work", str(work), output_flag, str(output_path)
            )
            require_rc(result, 0, f"1차 build {output_flag}")
            assert "이의 1건 (미판정 1건)" in result.stdout, (
                f"1차 build {output_flag}가 미판정 이의 건수를 출력하지 않았습니다.\n{result.stdout}"
            )

        result = run_cli(
            "build",
            "--work",
            str(work),
            "--out-data",
            str(work / "questions_data.py"),
            "--require-dispositions",
        )
        require_rc(result, 1, "미판정 이의 차단 build")

        _ = copy_stage(
            fixtures,
            "adversarial_disposition.py",
            work / "_reconcile" / "adversarial" / "u01_예시단위.py",
        )
        result = run_cli(
            "build",
            "--work",
            str(work),
            "--out-data",
            str(work / "questions_data.py"),
            "--require-dispositions",
        )
        require_rc(result, 0, "처분 반영 build")

        result = run_command(
            [
                sys.executable,
                str(VALIDATE),
                "--data",
                str(work / "questions_data.py"),
                "--strict-blind",
                "--strict-detail",
                "--strict-meta",
                "--strict-qid",
            ]
        )
        require_rc(result, 0, "validate strict 게이트")

        result = run_cli("audit", "--work", str(work), "--json")
        require_rc(result, 0, "audit")
        audit_value = expected["audit"]
        assert isinstance(audit_value, dict), "expected.json audit 값은 객체여야 합니다"
        expected_audit = dict(cast(dict[str, object], audit_value))
        expected_audit["open_objections"] = 0
        assert parse_json(result.stdout) == expected_audit, (
            f"audit JSON이 기대값과 다릅니다.\n실제: {result.stdout}\n기대: {expected_audit!r}"
        )
        objections_value = load_json(work / "_reconcile" / "objections.json")
        assert isinstance(objections_value, list), "objections.json 최상위 값은 목록이어야 합니다"
        objections = cast(list[object], objections_value)
        assert len(objections) == 1, f"objections.json 항목 수가 1이 아닙니다: {len(objections)}"
        objection = objections[0]
        assert isinstance(objection, dict), "objections.json 항목은 객체여야 합니다"
        objection_dict = cast(dict[str, object], objection)
        disposition = objection_dict.get("disposition")
        assert isinstance(disposition, dict), "이의 disposition은 객체여야 합니다"
        disposition_dict = cast(dict[str, object], disposition)
        assert disposition_dict.get("verdict") == "rejected", (
            f"이의 처분 verdict가 rejected가 아닙니다: {objection!r}"
        )

        viewer = work / "v.html"
        result = run_command(
            [
                sys.executable,
                str(VIEWER_BUILD),
                "--data",
                str(work / "questions_data.py"),
                "--images",
                str(fixtures / "images"),
                "--template",
                str(VIEWER_TEMPLATE),
                "--out",
                str(viewer),
                "--title",
                "t",
                "--subject",
                "예시과",
                "--storage-key",
                "예시과_test",
            ]
        )
        require_rc(result, 0, "학생용 HTML build")
        html = viewer.read_text(encoding="utf-8")
        assert SENTINEL not in html, "학생용 HTML에 블라인드 센티널이 노출되었습니다"
        assert QID_PREFIX not in html, "학생용 HTML에 내부 qid가 노출되었습니다"

        docx_path = work / "d.docx"
        result = run_command(
            [
                sys.executable,
                str(DOCX_BUILD),
                "--data",
                str(work / "questions_data.py"),
                "--img",
                str(fixtures / "images"),
                "--out",
                str(docx_path),
                "--title",
                "t",
                "--subtitle",
                "s",
            ]
        )
        require_rc(result, 0, "학생용 DOCX build")
        paragraph_text = "\n".join(
            paragraph.text for paragraph in Document(str(docx_path)).paragraphs
        )
        assert SENTINEL not in paragraph_text, "학생용 DOCX 문단에 블라인드 센티널이 노출되었습니다"
        print("비렌더 검사 · sentinel absent (html,docx)")

        probe = work / "probe.html"
        probe_code = (
            "from jokbo_pipeline import schema; "
            "schema.KEEP.append('blind'); "
            "from kd_library import build_viewer; "
            "build_viewer.main()"
        )
        result = run_command(
            [
                sys.executable,
                "-c",
                probe_code,
                "--data",
                str(work / "questions_data.py"),
                "--images",
                str(fixtures / "images"),
                "--template",
                str(VIEWER_TEMPLATE),
                "--out",
                str(probe),
                "--title",
                "t",
                "--subject",
                "예시과",
                "--storage-key",
                "예시과_probe",
            ]
        )
        require_rc(result, 0, "KEEP monkeypatch 센티널 자기 점검")
        assert SENTINEL in probe.read_text(encoding="utf-8"), (
            "KEEP monkeypatch 뒤에도 센티널이 나타나지 않아 비렌더 검사가 유효하지 않습니다"
        )
        print("자기 점검 · sentinel probe positive")

        check_brief_literals(work)
        print("브리프 리터럴 검사 · key-rules pass")
    finally:
        shutil.rmtree(work)
        assert not work.exists(), f"임시 작업 폴더 정리에 실패했습니다: {work}"


def parse_args() -> Path:
    parser = argparse.ArgumentParser(description="blindwork 합성 전체 흐름 검사")
    _ = parser.add_argument(
        "--fixtures",
        type=Path,
        default=DEFAULT_FIXTURES,
        help="blindwork 합성 픽스처 폴더",
    )
    return cast(Path, parser.parse_args().fixtures)


def main() -> int:
    try:
        run_e2e(parse_args().resolve())
    except subprocess.TimeoutExpired as exc:
        print(f"E2E 실패: 명령이 {COMMAND_TIMEOUT}초 안에 끝나지 않았습니다: {exc}", file=sys.stderr)
        return 1
    except (AssertionError, OSError, ValueError, SyntaxError) as exc:
        print(f"E2E 실패: {exc}", file=sys.stderr)
        return 1
    print(SUMMARY)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

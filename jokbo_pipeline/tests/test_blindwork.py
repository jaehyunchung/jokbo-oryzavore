# -*- coding: utf-8 -*-
# pyright: reportMissingImports=false
"""blindwork split/slice와 공통 로더의 stdlib 회귀 테스트."""
import json
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent
ROOT = PIPE.parent
CLI = PIPE / "blindwork.py"
FIXTURE = HERE / "fixtures" / "blindwork"
sys.path.insert(0, str(ROOT))

from jokbo_pipeline import blindwork, schema  # noqa: E402
from jokbo_pipeline.blindwork import classify, load_literal_list, parse_orig  # noqa: E402
from jokbo_pipeline.schema import load_scopes  # noqa: E402


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """blindwork CLI를 저장소 루트에서 실행하고 결과를 반환한다."""
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def copy_fixture(parent: Path, name: str) -> Path:
    """읽기 전용 합성 픽스처를 테스트 임시 폴더로 복사한다."""
    source = FIXTURE / name
    target = parent / name
    if source.is_dir():
        shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return target


def load_json(path: Path) -> Any:
    """UTF-8 JSON 파일을 파싱한다."""
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def split_batches(work: Path, parent: Path, fixture: str = "batches"):
    """복사한 배치 픽스처를 split하고 실행 결과를 반환한다."""
    batches = copy_fixture(parent, fixture)
    return run_cli("split", "--batches", str(batches), "--work", str(work))


def make_blind_work(work: Path, batches: list[tuple[str, list[dict[str, Any]]]]) -> None:
    """slice 단위 테스트용 blind 입력과 manifest를 만든다."""
    blind = work / "blind"
    blind.mkdir(parents=True)
    manifest = []
    for batch, rows in batches:
        (blind / f"{batch}.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        manifest.append(
            {
                "batch": batch,
                "count": len(rows),
                "with_image": sum(bool(r.get("image") or r.get("images")) for r in rows),
                "source": "batches",
                "input": "합성 입력",
            }
        )
    (blind / "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def prepare_solved_work(root: Path) -> Path:
    work = root / "work"
    assert split_batches(work, root).returncode == 0
    assert run_cli("slice", "--work", str(work)).returncode == 0
    solved = work / "solved"
    assert solved.is_dir()
    shutil.copy2(
        FIXTURE / "stages" / "solved_ok__t01.py",
        solved / "u01_예시단위__t01.py",
    )
    shutil.copy2(
        FIXTURE / "stages" / "solved_ok__i01.py",
        solved / "u01_예시단위__i01.py",
    )
    return work


def install_stage(work: Path, directory: str, fixture: str, filename: str) -> Path:
    target = work / directory / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(FIXTURE / "stages" / fixture, target)
    return target


def write_stage(path: Path, name: str, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{name} = {rows!r}\n", encoding="utf-8")


def prepare_resolved_work(root: Path) -> Path:
    work = prepare_solved_work(root)
    install_stage(
        work,
        "_reconcile/adjudicated",
        "adjudicated_ok.py",
        "u01_예시단위.py",
    )
    result = run_cli("resolve", "--work", str(work))
    assert result.returncode == 0, result.stderr + result.stdout
    return work


def prepare_build_work(root: Path, explained: str = "explained_ok.py") -> Path:
    work = prepare_resolved_work(root)
    install_stage(
        work,
        "_reconcile/explained",
        explained,
        "u01_예시단위.py",
    )
    return work


def load_questions(path: Path) -> list[dict[str, Any]]:
    spec = importlib.util.spec_from_file_location("built_questions", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.QUESTIONS


def write_scopes(path: Path, scopes: list[tuple[str, list[dict[str, Any]]]]) -> None:
    path.write_text("SCOPES = " + repr(scopes) + "\n", encoding="utf-8")


def test_split_batches_projects_struct_sealed_audit() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = root / "work"
        result = split_batches(work, root)
        assert result.returncode == 0, result.stderr + result.stdout
        assert not (root / "batches" / "__pycache__").exists()
        blind = load_json(work / "blind" / "u01_예시단위.json")
        sealed = load_json(work / "sealed" / "sealed_key.json")
        prior = load_json(work / "_audit" / "prior_snapshot.json")
        assert len(blind) == len(sealed) == len(prior) == 8
        struct = {"qid", "meta", "years", "stem", "options", "image", "images", "scope"}
        assert all(set(row) <= struct for row in blind)
        assert blind[0]["qid"] == "u01_예시단위#000"
        assert blind[0]["scope"] == "u01_예시단위"
        assert sealed["u01_예시단위#003"]["recon"]
        assert prior["u01_예시단위#000"]["verified"] == "③"


def test_split_struct_only_no_audit() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = root / "work"
        result = split_batches(work, root, "batches_struct_only")
        assert result.returncode == 0, result.stderr + result.stdout
        assert not (work / "_audit").exists()
        assert len(load_json(work / "sealed" / "sealed_key.json")) == 8


def test_split_leak_blocks_and_writes_nothing() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = root / "work"
        result = split_batches(work, root, "batches_leak")
        assert result.returncode == 1
        assert "누출" in result.stdout + result.stderr
        assert not (work / "blind").exists()
        assert not (work / "sealed").exists()


def test_split_allow_leak() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        batches = copy_fixture(root, "batches_leak")
        work = root / "work"
        result = run_cli(
            "split", "--batches", str(batches), "--work", str(work),
            "--allow-leak", "u02_누출예시#000=합성 검증용",
        )
        assert result.returncode == 0, result.stderr + result.stdout
        allowed = load_json(work / "blind" / "_leak_allow.json")
        assert allowed == [
            {"qid": "u02_누출예시#000", "token": "정답", "reason": "합성 검증용"}
        ]
        malformed = run_cli(
            "split", "--batches", str(batches), "--work", str(root / "bad"),
            "--allow-leak", "x",
        )
        assert malformed.returncode == 2


def test_split_extract_mapping() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        extract = copy_fixture(root, "extract")
        work = root / "work"
        result = run_cli("split", "--extract", str(extract), "--work", str(work))
        assert result.returncode == 0, result.stderr + result.stdout
        rows = load_json(work / "blind" / "extract.json")
        sealed = load_json(work / "sealed" / "sealed_key.json")
        candidates = load_json(work / "blind" / "_image_candidates.json")
        assert [row["qid"] for row in rows] == [f"extract#{i:03d}" for i in range(1, 5)]
        assert rows[0]["meta"] == "2025 · 홍길동"
        assert rows[0]["years"] == ["2025"]
        assert sealed["extract#002"]["orig_ans"] == "미표기"
        assert "image" not in rows[2] and "images" not in rows[2]
        assert candidates == {"extract#003": ["p02_1.jpg"]}
        assert rows[3]["scope"] == ""


def test_split_extract_unpaired_idx_fails() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        extract = copy_fixture(root, "extract")
        keys = load_json(extract / "answer_key.json")
        (extract / "answer_key.json").write_text(
            json.dumps(keys[:-1], ensure_ascii=False), encoding="utf-8"
        )
        work = root / "work"
        result = run_cli("split", "--extract", str(extract), "--work", str(work))
        assert result.returncode == 1
        assert "idx" in result.stdout + result.stderr
        assert not (work / "blind").exists()
        assert not (work / "sealed").exists()


def test_split_image_map_overrides() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        batches = copy_fixture(root, "batches")
        image_map = copy_fixture(root, "image_map.json")
        work = root / "work"
        result = run_cli(
            "split", "--batches", str(batches), "--work", str(work),
            "--image-map", str(image_map),
        )
        assert result.returncode == 0, result.stderr + result.stdout
        rows = load_json(work / "blind" / "u01_예시단위.json")
        assert rows[3]["image"] == "p02_1.jpg"
        assert "images" not in rows[3]


def test_split_refuses_rerun_without_force() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        batches = copy_fixture(root, "batches")
        work = root / "work"
        first = run_cli("split", "--batches", str(batches), "--work", str(work))
        second = run_cli("split", "--batches", str(batches), "--work", str(work))
        assert first.returncode == 0
        assert second.returncode == 1
        assert "--force" in second.stdout + second.stderr


def test_slice_sizes() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        work = Path(temp_dir) / "work"
        text_rows = [{"qid": f"u01_텍스트#{i:03d}"} for i in range(21)]
        image_rows = [
            {"qid": f"u02_도판#{i:03d}", "image": f"p{i:02d}.jpg"}
            for i in range(11)
        ]
        make_blind_work(work, [("u01_텍스트", text_rows), ("u02_도판", image_rows)])
        result = run_cli("slice", "--work", str(work), "--text-size", "20", "--image-size", "10")
        assert result.returncode == 0, result.stderr + result.stdout
        manifest = load_json(work / "slices" / "_manifest.json")
        assert [m["count"] for m in manifest if m["batch"] == "u01_텍스트"] == [11, 10]
        assert [m["count"] for m in manifest if m["batch"] == "u02_도판"] == [6, 5]


def test_slice_fixture_layout() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = root / "work"
        assert split_batches(work, root).returncode == 0
        result = run_cli("slice", "--work", str(work))
        assert result.returncode == 0, result.stderr + result.stdout
        manifest = load_json(work / "slices" / "_manifest.json")
        counts = {row["slice"]: row["count"] for row in manifest}
        assert counts == {"u01_예시단위__t01": 7, "u01_예시단위__i01": 1}
        qids = [qid for row in manifest for qid in row["qids"]]
        assert len(qids) == len(set(qids)) == 8
        assert len(load_json(work / "slices" / "u01_예시단위__t01.json")) == 7


def test_slice_refuses_when_solved_exists_without_force() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        work = Path(temp_dir) / "work"
        make_blind_work(work, [("u01_예시", [{"qid": "u01_예시#000"}])])
        solved = work / "solved"
        solved.mkdir()
        (solved / "old.py").write_text("SOLVED = []\n", encoding="utf-8")
        result = run_cli("slice", "--work", str(work))
        assert result.returncode == 1
        assert not (work / "slices").exists()


def test_slice_force_removes_stale() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        work = Path(temp_dir) / "work"
        make_blind_work(work, [("u01_예시", [{"qid": "u01_예시#000"}])])
        assert run_cli("slice", "--work", str(work)).returncode == 0
        stale = work / "slices" / "stale.json"
        stale.write_text("[]", encoding="utf-8")
        result = run_cli("slice", "--work", str(work), "--force")
        assert result.returncode == 0, result.stderr + result.stdout
        assert not stale.exists()
        assert load_json(work / "slices" / "u01_예시__t01.json")[0]["qid"] == "u01_예시#000"


def test_loader_rejects_exec() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        bad = copy_fixture(root, "stages/solved_exec__t01.py")
        good = copy_fixture(root, "stages/solved_ok__i01.py")
        assert len(load_literal_list(good, "SOLVED")) == 1
        try:
            load_literal_list(bad, "SOLVED")
        except Exception as exc:
            assert "리터럴만 허용" in str(exc)
        else:
            raise AssertionError("import 문이 있는 stage 파일을 거부하지 않음")


def test_parse_orig_table() -> None:
    assert parse_orig("") == (None, "empty")
    assert parse_orig("미표기") == (None, "none_recorded")
    assert parse_orig("2020년 1번 / 2019년 3번") == (None, "ambiguous")
    assert parse_orig("답: C6") == (None, "unparsed")
    assert parse_orig("답: 2, 4") == (["②", "④"], "ok")
    cases = [
        ("정답: 3", (["③"], "ok"), 5, (["③"], "ok")),
        ("답: 2, 4", (["②", "④"], "ok"), 5, (["②", "④"], "ok")),
        ("답: 12", (["⑫"], "ok"), 5, (["①", "②"], "ok")),
        ("답: 12", (["⑫"], "ok"), 15, (["⑫"], "ok")),
        ("정답: 10", (["⑩"], "ok"), 5, (None, "unparsed")),
        ("정답: 10", (["⑩"], "ok"), 12, (["⑩"], "ok")),
        ("답: 20", (["⑳"], "ok"), 5, (None, "unparsed")),
        ("답: 20", (["⑳"], "ok"), 20, (["⑳"], "ok")),
        ("답: 11, 13", (["⑪", "⑬"], "ok"), 5, (["①", "③"], "ok")),
        ("답: 1,2", (["①", "②"], "ok"), 5, (["①", "②"], "ok")),
        ("정답: ⑫", (["⑫"], "ok"), 5, (None, "unparsed")),
        ("정답: ⑫", (["⑫"], "ok"), 15, (["⑫"], "ok")),
        ("답: 0", (None, "unparsed"), 5, (None, "unparsed")),
    ]
    for text, without_count, option_count, with_count in cases:
        assert parse_orig(text) == without_count, text
        assert parse_orig(text, option_count) == with_count, (text, option_count)
    assert classify(
        {"verified": "예시답안"}, {"orig_ans": "답: C6"}, {"options": []}
    ) == (None, "subjective")
    assert classify(
        {"verified": "①"}, {"orig_ans": "미표기"}, {"options": []}
    ) == (["TEXT_RECONSTRUCTED"], "none_recorded")
    assert classify(
        {"verified": "①"}, {"orig_ans": "답: ①"}, {"options": ["① A", "② B"]}
    ) == (["ANSWER_MATCH"], "auto_match")
    assert classify(
        {"verified": "②"}, {"orig_ans": "답: ①"}, {"options": ["① A", "② B"]}
    ) == (None, "mismatch")
    assert classify(
        {"verified": "①"},
        {"orig_ans": "정답: 10"},
        {"options": ["① A", "② B", "③ C", "④ D", "⑤ E"]},
    ) == (None, "unparsed")


def test_shared_marker_normalization() -> None:
    assert blindwork.CIRC is schema.CIRCLED_MARKERS
    assert blindwork.markers("답은 ⑫, ③, ⑫") == schema.norm_markers("답은 ⑫, ③, ⑫")


def test_split_force_refused_when_downstream_exists() -> None:
    for directory, filename in (("solved", "answer.json"), ("_reconcile", "memo.txt")):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            batches = copy_fixture(root, "batches")
            work = root / "work"
            assert run_cli("split", "--batches", str(batches), "--work", str(work)).returncode == 0
            downstream = work / directory
            downstream.mkdir()
            (downstream / filename).write_text("합성 하류 산출물\n", encoding="utf-8")
            before = load_json(work / "blind" / "_manifest.json")
            result = run_cli(
                "split", "--batches", str(batches), "--work", str(work), "--force"
            )
            assert result.returncode == 1
            assert directory in result.stdout + result.stderr
            assert load_json(work / "blind" / "_manifest.json") == before


def test_split_force_before_slice_allows_empty_downstream_dirs() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        batches = copy_fixture(root, "batches")
        work = root / "work"
        first = run_cli("split", "--batches", str(batches), "--work", str(work))
        assert first.returncode == 0, first.stderr + first.stdout
        (work / "solved" / "_patch").mkdir(parents=True)
        (work / "_reconcile").mkdir()
        rerun = run_cli("split", "--batches", str(batches), "--work", str(work), "--force")
        assert rerun.returncode == 0, rerun.stderr + rerun.stdout


def test_manifest_has_source() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = root / "work"
        batches = copy_fixture(root, "batches")
        result = run_cli("split", "--batches", str(batches), "--work", str(work))
        assert result.returncode == 0, result.stderr + result.stdout
        manifest = load_json(work / "blind" / "_manifest.json")
        assert manifest[0]["source"] == "batches"
        assert manifest[0]["input"] == str(batches)


def test_allow_leak_unknown_qid_usage_error() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        batches = copy_fixture(root, "batches")
        work = root / "work"
        result = run_cli(
            "split", "--batches", str(batches), "--work", str(work),
            "--allow-leak", "u99_없음#000=합성 검증용",
        )
        assert result.returncode == 2
        assert "qid" in result.stderr
        assert not (work / "blind").exists()


def test_allow_leak_unused_warns() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        batches = copy_fixture(root, "batches")
        work = root / "work"
        result = run_cli(
            "split", "--batches", str(batches), "--work", str(work),
            "--allow-leak", "u01_예시단위#000=합성 검증용",
        )
        assert result.returncode == 0, result.stderr + result.stdout
        assert "미사용 허용" in result.stdout
        assert not (work / "blind" / "_leak_allow.json").exists()


def test_slice_force_refused_when_patch_exists() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        work = Path(temp_dir) / "work"
        make_blind_work(work, [("u01_예시", [{"qid": "u01_예시#000"}])])
        assert run_cli("slice", "--work", str(work)).returncode == 0
        patch = work / "solved" / "_patch"
        patch.mkdir(parents=True, exist_ok=True)
        (patch / "x.py").write_text("SOLVED = []\n", encoding="utf-8")
        result = run_cli("slice", "--work", str(work), "--force")
        assert result.returncode == 1
        assert "풀이 산출물" in result.stdout + result.stderr


def test_slice_creates_agent_write_dirs() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = root / "work"
        assert split_batches(work, root).returncode == 0
        result = run_cli("slice", "--work", str(work))
        assert result.returncode == 0, result.stderr + result.stdout
        assert (work / "solved").is_dir()
        assert (work / "solved" / "_patch").is_dir()


def test_split_force_refused_after_slice() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = root / "work"
        batches = copy_fixture(root, "batches")
        first = run_cli("split", "--batches", str(batches), "--work", str(work))
        assert first.returncode == 0, first.stderr + first.stdout
        sliced = run_cli("slice", "--work", str(work))
        assert sliced.returncode == 0, sliced.stderr + sliced.stdout
        rerun = run_cli(
            "split", "--batches", str(batches), "--work", str(work), "--force"
        )
        assert rerun.returncode == 1
        assert "slices" in rerun.stdout + rerun.stderr
        assert "직접 지운" in rerun.stdout + rerun.stderr


def test_slice_force_ok_with_empty_patch_dir() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = root / "work"
        assert split_batches(work, root).returncode == 0
        assert run_cli("slice", "--work", str(work)).returncode == 0
        assert (work / "solved" / "_patch").is_dir()
        rerun = run_cli("slice", "--work", str(work), "--force")
        assert rerun.returncode == 0, rerun.stderr + rerun.stdout


def test_scan_creates_adjudicated_dir() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        work = prepare_solved_work(Path(temp_dir))
        result = run_cli("scan", "--work", str(work), "--json")
        assert result.returncode == 0, result.stderr + result.stdout
        assert json.loads(result.stdout)["pending"] == 4
        assert (work / "_reconcile" / "adjudicated").is_dir()


def test_resolve_creates_explained_and_adversarial_dirs() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        work = prepare_resolved_work(Path(temp_dir))
        assert (work / "_reconcile" / "explained").is_dir()
        assert (work / "_reconcile" / "adversarial").is_dir()


def test_check_solve_ok() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        work = prepare_solved_work(Path(temp_dir))
        for name in ("u01_예시단위__t01.py", "u01_예시단위__i01.py"):
            result = run_cli(
                "check", "--work", str(work), "--stage", "solve",
                str(work / "solved" / name),
            )
            assert result.returncode == 0, result.stderr + result.stdout


def test_check_solve_rejects_explanation_keys() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_solved_work(root)
        bad = install_stage(
            work, "solved", "solved_bad_keys__t01.py", "u01_예시단위__t01.py"
        )
        result = run_cli("check", "--work", str(work), "--stage", "solve", str(bad))
        assert result.returncode == 1
        assert "허용되지 않은 키" in result.stdout + result.stderr


def test_check_solve_rejects_count() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_solved_work(root)
        bad = install_stage(
            work, "solved", "solved_bad_count__t01.py", "u01_예시단위__t01.py"
        )
        result = run_cli("check", "--work", str(work), "--stage", "solve", str(bad))
        assert result.returncode == 1
        assert "option_judgments" in result.stdout + result.stderr


def test_check_solve_rejects_exec() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_solved_work(root)
        bad = install_stage(
            work, "solved", "solved_exec__t01.py", "u01_예시단위__t01.py"
        )
        result = run_cli("check", "--work", str(work), "--stage", "solve", str(bad))
        assert result.returncode == 1
        assert "리터럴만" in result.stdout + result.stderr


def test_check_solve_multi_answers() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_solved_work(root)
        path = work / "solved" / "u01_예시단위__t01.py"
        rows = load_literal_list(path, "SOLVED")
        rows[1]["answers"] = ["②", "⑤"]
        write_stage(path, "SOLVED", rows)
        result = run_cli("check", "--work", str(work), "--stage", "solve", str(path))
        assert result.returncode == 1
        assert "answers" in result.stdout + result.stderr


def test_check_solve_patch() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_solved_work(root)
        patch = work / "solved" / "_patch" / "u01_예시단위__t01.py"
        rows = load_literal_list(work / "solved" / "u01_예시단위__t01.py", "SOLVED")
        write_stage(patch, "SOLVED", [rows[0]])
        good = run_cli(
            "check", "--work", str(work), "--stage", "solve", "--patch", str(patch)
        )
        assert good.returncode == 0, good.stderr + good.stdout
        rows[0]["qid"] = "u99_없는단위#000"
        write_stage(patch, "SOLVED", [rows[0]])
        bad = run_cli(
            "check", "--work", str(work), "--stage", "solve", "--patch", str(patch)
        )
        assert bad.returncode == 1
        assert "slice" in bad.stdout + bad.stderr


def test_check_adjudicate_ok() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_solved_work(root)
        path = install_stage(
            work, "_reconcile/adjudicated", "adjudicated_ok.py", "u01_예시단위.py"
        )
        result = run_cli(
            "check", "--work", str(work), "--stage", "adjudicate", str(path)
        )
        assert result.returncode == 0, result.stderr + result.stdout


def test_check_adjudicate_twoflags() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_solved_work(root)
        path = install_stage(
            work, "_reconcile/adjudicated", "adjudicated_bad_twoflags.py",
            "u01_예시단위.py",
        )
        result = run_cli(
            "check", "--work", str(work), "--stage", "adjudicate", str(path)
        )
        assert result.returncode == 1
        assert "flags" in result.stdout + result.stderr


def test_check_adjudicate_nosource() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_solved_work(root)
        path = install_stage(
            work, "_reconcile/adjudicated", "adjudicated_bad_nosource.py",
            "u01_예시단위.py",
        )
        result = run_cli(
            "check", "--work", str(work), "--stage", "adjudicate", str(path)
        )
        assert result.returncode == 1
        assert "source" in result.stdout + result.stderr


def test_check_adjudicate_imgflag() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_solved_work(root)
        path = install_stage(
            work, "_reconcile/adjudicated", "adjudicated_bad_imgflag.py",
            "u01_예시단위.py",
        )
        result = run_cli(
            "check", "--work", str(work), "--stage", "adjudicate", str(path)
        )
        assert result.returncode == 1
        assert "플래그" in result.stdout + result.stderr


def test_check_adjudicate_match_must_equal_orig() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_solved_work(root)
        rows = load_literal_list(FIXTURE / "stages" / "adjudicated_ok.py", "ADJUDICATED")
        rows[1]["flags"] = ["ANSWER_MATCH"]
        rows[1]["verified"] = "②"
        path = work / "_reconcile" / "adjudicated" / "u01_예시단위.py"
        write_stage(path, "ADJUDICATED", rows)
        result = run_cli(
            "check", "--work", str(work), "--stage", "adjudicate", str(path)
        )
        assert result.returncode == 1
        assert "원본" in result.stdout + result.stderr


def test_check_adjudicate_missing_worklist_qid() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_solved_work(root)
        rows = load_literal_list(FIXTURE / "stages" / "adjudicated_ok.py", "ADJUDICATED")
        path = work / "_reconcile" / "adjudicated" / "u01_예시단위.py"
        write_stage(path, "ADJUDICATED", rows[:-1])
        result = run_cli(
            "check", "--work", str(work), "--stage", "adjudicate", str(path)
        )
        assert result.returncode == 1
        assert "누락" in result.stdout + result.stderr


def test_scan_stats_fixture() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        work = prepare_solved_work(Path(temp_dir))
        result = run_cli("scan", "--work", str(work), "--json")
        assert result.returncode == 0, result.stderr + result.stdout
        assert result.stderr == ""
        assert json.loads(result.stdout) == load_json(FIXTURE / "expected.json")["scan"]
        worklist = load_json(work / "_reconcile" / "worklist" / "u01_예시단위.json")
        assert len(worklist) == 4
        required = {
            "qid", "why", "meta", "years", "stem", "options", "blind_verified",
            "blind_confidence", "blind_note", "blind_option_judgments", "orig_ans",
            "orig_expl", "recon",
        }
        assert all(required <= set(row) for row in worklist)


def test_scan_subjective_before_parser() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        work = prepare_solved_work(Path(temp_dir))
        result = run_cli("scan", "--work", str(work), "--json")
        stats = json.loads(result.stdout)
        worklist = load_json(work / "_reconcile" / "worklist" / "u01_예시단위.json")
        assert stats["subjective"] == 1
        assert stats["unparsed"] == 1
        why = {row["qid"]: row["why"] for row in worklist}
        assert why["u01_예시단위#002"] == "subjective"
        assert why["u01_예시단위#007"] == "unparsed"


def test_scan_partial_unsolved_exit0() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = root / "work"
        assert split_batches(work, root).returncode == 0
        result = run_cli("scan", "--work", str(work), "--json")
        assert result.returncode == 0, result.stderr + result.stdout
        stats = json.loads(result.stdout)
        assert stats["unsolved"] == 8
        assert len(stats["unsolved_qids"]) == 8


def test_scan_reverifies_inputs() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_solved_work(root)
        install_stage(
            work, "solved", "solved_bad_keys__t01.py", "u01_예시단위__t01.py"
        )
        result = run_cli("scan", "--work", str(work), "--json")
        assert result.returncode == 1
        assert "허용되지 않은 키" in result.stdout + result.stderr


def test_scan_all_ignores_adjudicated() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_solved_work(root)
        install_stage(
            work, "_reconcile/adjudicated", "adjudicated_ok.py", "u01_예시단위.py"
        )
        normal = run_cli("scan", "--work", str(work), "--json")
        all_rows = run_cli("scan", "--work", str(work), "--all", "--json")
        assert normal.returncode == all_rows.returncode == 0
        assert json.loads(normal.stdout)["adjudicated"] == 4
        assert json.loads(all_rows.stdout)["adjudicated"] == 0
        assert json.loads(all_rows.stdout)["pending"] == 4


def test_resolve_pending_fails_and_writes_nothing() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        work = prepare_solved_work(Path(temp_dir))
        result = run_cli("resolve", "--work", str(work))
        assert result.returncode == 1
        for qid in load_json(FIXTURE / "expected.json")["scan"]["pending_qids"]:
            assert qid in result.stdout + result.stderr
        assert not (work / "_reconcile" / "resolved").exists()


def test_resolve_ok() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        work = prepare_resolved_work(Path(temp_dir))
        rows = load_json(work / "_reconcile" / "resolved" / "u01_예시단위.json")
        assert len(rows) == 8
        by_qid = {row["qid"]: row for row in rows}
        disputed = by_qid["u01_예시단위#004"]
        assert disputed["verified"] == "⑤"
        assert disputed["flags"] == ["ANSWER_DISPUTED"]
        assert disputed["scope_note"]
        reconstructed = by_qid["u01_예시단위#005"]
        assert reconstructed["verified"] == "②"
        assert reconstructed["flags"] == ["TEXT_RECONSTRUCTED"]
        corrected = by_qid["u01_예시단위#007"]
        assert corrected["verified"] == "③"
        assert corrected["flags"] == ["ANSWER_CORRECTED"]
        assert disputed["stem"] and disputed["options"] and disputed["orig_expl"]
        assert disputed["blind"]["option_judgments"]


def test_resolve_rejects_bad_adjudication() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_solved_work(root)
        install_stage(
            work, "_reconcile/adjudicated", "adjudicated_bad_twoflags.py",
            "u01_예시단위.py",
        )
        result = run_cli("resolve", "--work", str(work))
        assert result.returncode == 1
        assert "flags" in result.stdout + result.stderr
        assert not (work / "_reconcile" / "resolved").exists()


def test_check_explain_ok() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        work = prepare_resolved_work(Path(temp_dir))
        path = install_stage(
            work, "_reconcile/explained", "explained_ok.py", "u01_예시단위.py"
        )
        result = run_cli("check", "--work", str(work), "--stage", "explain", str(path))
        assert result.returncode == 0, result.stderr + result.stdout


def test_check_explain_rejects_answer_keys() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        work = prepare_resolved_work(Path(temp_dir))
        path = install_stage(
            work, "_reconcile/explained", "explained_bad_answerkey.py",
            "u01_예시단위.py",
        )
        result = run_cli("check", "--work", str(work), "--stage", "explain", str(path))
        assert result.returncode == 1
        assert "이 단계는 해설만" in result.stdout + result.stderr
        assert "verified" in result.stdout + result.stderr


def test_check_explain_requires_warn_on_disputed() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        work = prepare_resolved_work(Path(temp_dir))
        path = install_stage(
            work, "_reconcile/explained", "explained_bad_nowarn.py", "u01_예시단위.py"
        )
        result = run_cli("check", "--work", str(work), "--stage", "explain", str(path))
        assert result.returncode == 1
        assert "⚠" in result.stdout + result.stderr


def test_check_explain_objection_allowed() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        work = prepare_resolved_work(Path(temp_dir))
        path = install_stage(
            work, "_reconcile/explained", "explained_objection.py", "u01_예시단위.py"
        )
        result = run_cli("check", "--work", str(work), "--stage", "explain", str(path))
        assert result.returncode == 0, result.stderr + result.stdout


def test_check_explain_subjective_one_line() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        work = prepare_resolved_work(Path(temp_dir))
        rows = load_literal_list(FIXTURE / "stages" / "explained_ok.py", "EXPLAINED")
        path = work / "_reconcile" / "explained" / "u01_예시단위.py"
        rows[2]["wrong_option_explanations"] = []
        write_stage(path, "EXPLAINED", rows)
        bad = run_cli("check", "--work", str(work), "--stage", "explain", str(path))
        assert bad.returncode == 1
        rows[2]["wrong_option_explanations"] = [
            "선택지가 없는 서술형 문항이므로 오답 선택지 해설은 해당하지 않는다."
        ]
        write_stage(path, "EXPLAINED", rows)
        good = run_cli("check", "--work", str(work), "--stage", "explain", str(path))
        assert good.returncode == 0, good.stderr + good.stdout


def test_check_explain_markdown() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        work = prepare_resolved_work(Path(temp_dir))
        rows = load_literal_list(FIXTURE / "stages" / "explained_ok.py", "EXPLAINED")
        path = work / "_reconcile" / "explained" / "u01_예시단위.py"
        rows[0]["new_expl"] += " **강조**"
        write_stage(path, "EXPLAINED", rows)
        bad = run_cli("check", "--work", str(work), "--stage", "explain", str(path))
        assert bad.returncode == 1
        assert "마크다운" in bad.stdout + bad.stderr
        rows[0]["new_expl"] = rows[0]["new_expl"].replace(" **강조**", " 치식 A*B")
        write_stage(path, "EXPLAINED", rows)
        good = run_cli("check", "--work", str(work), "--stage", "explain", str(path))
        assert good.returncode == 0, good.stderr + good.stdout


def test_check_explain_needs_resolved() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = root / "work"
        path = install_stage(
            work, "_reconcile/explained", "explained_ok.py", "u01_예시단위.py"
        )
        result = run_cli("check", "--work", str(work), "--stage", "explain", str(path))
        assert result.returncode == 1
        assert "resolve 먼저" in result.stdout + result.stderr


def test_build_requires_resolved() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_solved_work(root)
        install_stage(work, "_reconcile/adjudicated", "adjudicated_ok.py", "u01_예시단위.py")
        result = run_cli("build", "--work", str(work), "--out-data", str(root / "data.py"))
        assert result.returncode == 1
        assert "resolve 먼저" in result.stdout + result.stderr
        assert not (root / "data.py").exists()


def test_build_requires_explained() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_resolved_work(root)
        result = run_cli("build", "--work", str(work), "--out-data", str(root / "data.py"))
        assert result.returncode == 1
        assert "C 미집필" in result.stdout + result.stderr
        assert not (root / "data.py").exists()


def test_build_stale_resolved_judgment() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_build_work(root)
        path = work / "_reconcile" / "adjudicated" / "u01_예시단위.py"
        rows = load_literal_list(path, "ADJUDICATED")
        rows[0]["verified"] = "수정된 합성 답안"
        write_stage(path, "ADJUDICATED", rows)
        result = run_cli("build", "--work", str(work), "--out-data", str(root / "data.py"))
        assert result.returncode == 1
        assert "stale" in result.stdout + result.stderr


def test_build_stale_resolved_struct() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_build_work(root)
        path = work / "blind" / "u01_예시단위.json"
        rows = load_json(path)
        rows[0]["stem"] += " 구조 변경"
        path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        result = run_cli("build", "--work", str(work), "--out-data", str(root / "data.py"))
        assert result.returncode == 1
        assert "stale" in result.stdout + result.stderr


def test_build_out_batches_shape() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_build_work(root)
        out = root / "batches"
        result = run_cli("build", "--work", str(work), "--out-batches", str(out))
        assert result.returncode == 0, result.stderr + result.stdout
        rows = load_questions(out / "u01_예시단위.py")
        assert len(rows) == 8
        expected_order = blindwork.FINAL_KEY_ORDER
        for row in rows:
            assert list(row) == [key for key in expected_order if key in row]
            assert "scope" not in row and "page" not in row and "objection" not in row
            assert {"qid", "blind"} <= set(row)
            assert set(row["blind"]) <= {"verified", "answers", "confidence", "note"}
        by_qid = {row["qid"]: row for row in rows}
        first_expl = by_qid["u01_예시단위#000"]["new_expl"]
        assert (first_expl[0] if isinstance(first_expl, list) else first_expl).startswith("【왕족】 ")
        assert "STEM_IMAGE_A_PRESENT" in by_qid["u01_예시단위#004"]["flags"]
        assert "IMAGE_MISSING" in by_qid["u01_예시단위#005"]["flags"]
        assert "answers" in by_qid["u01_예시단위#001"]
        assert by_qid["u01_예시단위#004"]["source"]


def test_build_out_data_from_batches() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_build_work(root)
        out = root / "questions_data.py"
        result = run_cli("build", "--work", str(work), "--out-data", str(out))
        assert result.returncode == 0, result.stderr + result.stdout
        scopes = load_scopes(out)
        assert [(label, len(rows)) for label, rows in scopes] == [("u01_예시단위", 8)]


def test_group_scopes_unit() -> None:
    rows = [
        {"qid": "a", "scope": "A"},
        {"qid": "b", "scope": ""},
        {"qid": "c", "scope": "A"},
        {"qid": "d", "scope": "B"},
    ]
    grouped = blindwork.group_scopes(rows)
    assert [(label, len(items)) for label, items in grouped] == [
        ("A", 2), ("미분류", 1), ("B", 1)
    ]


def test_build_objections_json() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_build_work(root, "explained_objection.py")
        out = root / "data.py"
        result = run_cli("build", "--work", str(work), "--out-data", str(out))
        assert result.returncode == 0, result.stderr + result.stdout
        assert "이의 1건 (미판정 1건)" in result.stdout
        objections = load_json(work / "_reconcile" / "objections.json")
        assert len(objections) == 1
        assert objections[0]["qid"] == "u01_예시단위#007"
        assert objections[0]["disposition"] is None
        assert all("objection" not in row for _scope, rows in load_scopes(out) for row in rows)


def test_build_require_dispositions() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_build_work(root, "explained_objection.py")
        out = root / "data.py"
        pending = run_cli(
            "build", "--work", str(work), "--out-data", str(out), "--require-dispositions"
        )
        assert pending.returncode == 1
        assert not out.exists()
        install_stage(
            work, "_reconcile/adversarial", "adversarial_disposition.py", "u01_예시단위.py"
        )
        resolved = run_cli(
            "build", "--work", str(work), "--out-data", str(out), "--require-dispositions"
        )
        assert resolved.returncode == 0, resolved.stderr + resolved.stdout
        disposition = load_json(work / "_reconcile" / "objections.json")[0]["disposition"]
        assert disposition["verdict"] == "rejected"
        assert disposition["layer"] == "adversarial"


def test_build_layer_overrides_tip() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_build_work(root)
        install_stage(work, "_reconcile/adversarial", "adversarial_ok.py", "u01_예시단위.py")
        out = root / "batches"
        result = run_cli("build", "--work", str(work), "--out-batches", str(out))
        assert result.returncode == 0, result.stderr + result.stdout
        rows = load_questions(out / "u01_예시단위.py")
        assert rows[0]["tip"] == "합성 검증용으로 교체한 예시단원 A 복습 팁이다."
        assert rows[1]["verified"] == "②, ④"


def test_build_layer_bad_count() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_build_work(root)
        install_stage(work, "_reconcile/adversarial", "adversarial_bad_count.py", "u01_예시단위.py")
        result = run_cli("build", "--work", str(work), "--out-data", str(root / "data.py"))
        assert result.returncode == 1
        assert "wrong_option_explanations" in result.stdout + result.stderr


def test_build_layer_rejects_blind_key() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_build_work(root)
        install_stage(work, "_reconcile/adversarial", "adversarial_bad_blind.py", "u01_예시단위.py")
        result = run_cli("build", "--work", str(work), "--out-data", str(root / "data.py"))
        assert result.returncode == 1
        assert "blind" in result.stdout + result.stderr


def test_build_layer_recheck_d8() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_build_work(root)
        install_stage(work, "_reconcile/adversarial", "adversarial_bad_match.py", "u01_예시단위.py")
        result = run_cli("build", "--work", str(work), "--out-data", str(root / "data.py"))
        assert result.returncode == 1
        assert "ANSWER_MATCH" in result.stdout + result.stderr


def test_build_source_join() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_build_work(root)
        path = work / "_reconcile" / "explained" / "u01_예시단위.py"
        rows = load_literal_list(path, "EXPLAINED")
        rows[4]["source"] = "합성 해설 출처"
        write_stage(path, "EXPLAINED", rows)
        out = root / "data.py"
        result = run_cli("build", "--work", str(work), "--out-data", str(out))
        assert result.returncode == 0, result.stderr + result.stdout
        built = {row["qid"]: row for _scope, rows in load_scopes(out) for row in rows}
        assert built["u01_예시단위#004"]["source"] == (
            "합성 참고: 원래 표기를 유지한다. / 합성 해설 출처"
        )


def test_build_writes_nothing_on_error() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_build_work(root)
        install_stage(work, "_reconcile/adversarial", "adversarial_bad_match.py", "u01_예시단위.py")
        out = work / "batches"
        result = run_cli("build", "--work", str(work), "--out-batches", str(out))
        assert result.returncode == 1
        assert not out.exists()


def test_build_objections_failure_is_atomic() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_build_work(root)
        objections = work / "_reconcile" / "objections.json"
        objections.mkdir()
        out = root / "data.py"
        result = run_cli("build", "--work", str(work), "--out-data", str(out))
        assert result.returncode != 0
        assert not out.exists()
        assert objections.is_dir()


def test_build_batch_flag_only_with_out_batches() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_build_work(root)
        result = run_cli(
            "build", "--work", str(work), "--out-data", str(root / "data.py"),
            "--batch", "u01_예시단위",
        )
        assert result.returncode == 2


def test_build_reverifies_inputs() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_build_work(root, "explained_bad_answerkey.py")
        result = run_cli("build", "--work", str(work), "--out-data", str(root / "data.py"))
        assert result.returncode == 1
        assert "이 단계는 해설만" in result.stdout + result.stderr


def test_audit_metrics_fixture() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_build_work(root, "explained_objection.py")
        data = work / "questions_data.py"
        assert run_cli("build", "--work", str(work), "--out-data", str(data)).returncode == 0
        expected = load_json(FIXTURE / "expected.json")["audit"]
        by_data = run_cli("audit", "--data", str(data), "--json")
        assert by_data.returncode == 0, by_data.stderr + by_data.stdout
        assert json.loads(by_data.stdout) == expected
        expected_work = dict(expected)
        expected_work["open_objections"] = 1
        by_work = run_cli("audit", "--work", str(work), "--json")
        assert by_work.returncode == 0, by_work.stderr + by_work.stdout
        assert json.loads(by_work.stdout) == expected_work


def test_audit_unmeasurable() -> None:
    data = ROOT / "kd_library" / "tests" / "fixtures" / "smoke_questions_data.py"
    human = run_cli("audit", "--data", str(data))
    assert human.returncode == 0
    assert "측정 불가" in human.stdout
    machine = run_cli("audit", "--data", str(data), "--json")
    assert machine.returncode == 0
    assert json.loads(machine.stdout)["measurable"] is False


def test_audit_partial_blind() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_build_work(root)
        data = root / "data.py"
        assert run_cli("build", "--work", str(work), "--out-data", str(data)).returncode == 0
        scopes = load_scopes(data)
        scopes[0][1][0].pop("blind")
        partial = root / "partial.py"
        write_scopes(partial, scopes)
        result = run_cli("audit", "--data", str(partial), "--json")
        assert result.returncode == 0, result.stderr + result.stdout
        assert json.loads(result.stdout)["blind_missing"] == 1


def test_audit_subjective_excluded() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_build_work(root)
        data = root / "data.py"
        assert run_cli("build", "--work", str(work), "--out-data", str(data)).returncode == 0
        result = run_cli("audit", "--data", str(data), "--json")
        report = json.loads(result.stdout)
        assert report["subjective"] == 1
        assert report["objective"] == 7
        assert report["blind_survival"]["den"] == 7


def test_audit_int_answers() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_build_work(root)
        data = root / "data.py"
        assert run_cli("build", "--work", str(work), "--out-data", str(data)).returncode == 0
        scopes = load_scopes(data)
        scopes[0][1][1]["blind"]["answers"] = [2, 4]
        integer_answers = root / "integer_answers.py"
        write_scopes(integer_answers, scopes)
        result = run_cli("audit", "--data", str(integer_answers), "--json")
        assert result.returncode == 0, result.stderr + result.stdout
        assert json.loads(result.stdout)["auto_match"] == {"num": 3, "den": 4}


def test_audit_bad_blind_shape() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        data = root / "bad.py"
        write_scopes(data, [("예시", [{
            "qid": "q#001", "meta": "2025 · 홍길동", "stem": "합성 문항",
            "options": ["① 예", "② 아니오"], "verified": "①", "orig_ans": "답: ①",
            "blind": "①",
        }])])
        result = run_cli("audit", "--data", str(data), "--json")
        assert result.returncode == 1
        assert "blind" in result.stdout + result.stderr


def test_audit_missing_file() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        missing = Path(temp_dir) / "missing.py"
        result = run_cli("audit", "--data", str(missing), "--json")
        assert result.returncode == 1


def test_audit_show_lists_mismatch() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        work = prepare_build_work(root)
        data = root / "data.py"
        assert run_cli("build", "--work", str(work), "--out-data", str(data)).returncode == 0
        result = run_cli("audit", "--data", str(data), "--show", "5")
        assert result.returncode == 0, result.stderr + result.stdout
        assert "u01_예시단위#004" in result.stdout
        assert "② → ⑤ · ⑤" in result.stdout


def test_check_adversarial_is_argparse_error() -> None:
    result = run_cli(
        "check", "--work", "/tmp", "--stage", "adversarial", "/dev/null"
    )
    assert result.returncode == 2
    assert "build" in result.stderr and "--layers" in result.stderr


def test_check_help_names_stage_next_commands() -> None:
    result = run_cli("check", "--help")
    assert result.returncode == 0
    for command in ("scan", "resolve", "build"):
        assert command in result.stdout


def test_subcommand_help_is_korean_and_complete() -> None:
    parser = blindwork.build_parser()
    subparsers = next(
        action for action in parser._actions if isinstance(action, blindwork.argparse._SubParsersAction)
    )
    assert set(subparsers.choices) == {"split", "slice", "check", "scan", "resolve", "build", "audit"}
    for name, subparser in subparsers.choices.items():
        assert subparser.description and any("가" <= ch <= "힣" for ch in subparser.description), name
        for action in subparser._actions:
            if action.dest == "help":
                continue
            assert action.help and any("가" <= ch <= "힣" for ch in action.help), (name, action.dest)


TESTS = [
    test_split_batches_projects_struct_sealed_audit,
    test_split_struct_only_no_audit,
    test_split_leak_blocks_and_writes_nothing,
    test_split_allow_leak,
    test_split_extract_mapping,
    test_split_extract_unpaired_idx_fails,
    test_split_image_map_overrides,
    test_split_refuses_rerun_without_force,
    test_slice_sizes,
    test_slice_fixture_layout,
    test_slice_refuses_when_solved_exists_without_force,
    test_slice_force_removes_stale,
    test_loader_rejects_exec,
    test_parse_orig_table,
    test_shared_marker_normalization,
    test_split_force_refused_when_downstream_exists,
    test_split_force_before_slice_allows_empty_downstream_dirs,
    test_manifest_has_source,
    test_allow_leak_unknown_qid_usage_error,
    test_allow_leak_unused_warns,
    test_slice_force_refused_when_patch_exists,
    test_slice_creates_agent_write_dirs,
    test_split_force_refused_after_slice,
    test_slice_force_ok_with_empty_patch_dir,
    test_scan_creates_adjudicated_dir,
    test_resolve_creates_explained_and_adversarial_dirs,
    test_check_solve_ok,
    test_check_solve_rejects_explanation_keys,
    test_check_solve_rejects_count,
    test_check_solve_rejects_exec,
    test_check_solve_multi_answers,
    test_check_solve_patch,
    test_check_adjudicate_ok,
    test_check_adjudicate_twoflags,
    test_check_adjudicate_nosource,
    test_check_adjudicate_imgflag,
    test_check_adjudicate_match_must_equal_orig,
    test_check_adjudicate_missing_worklist_qid,
    test_scan_stats_fixture,
    test_scan_subjective_before_parser,
    test_scan_partial_unsolved_exit0,
    test_scan_reverifies_inputs,
    test_scan_all_ignores_adjudicated,
    test_resolve_pending_fails_and_writes_nothing,
    test_resolve_ok,
    test_resolve_rejects_bad_adjudication,
    test_check_explain_ok,
    test_check_explain_rejects_answer_keys,
    test_check_explain_requires_warn_on_disputed,
    test_check_explain_objection_allowed,
    test_check_explain_subjective_one_line,
    test_check_explain_markdown,
    test_check_explain_needs_resolved,
    test_build_requires_resolved,
    test_build_requires_explained,
    test_build_stale_resolved_judgment,
    test_build_stale_resolved_struct,
    test_build_out_batches_shape,
    test_build_out_data_from_batches,
    test_group_scopes_unit,
    test_build_objections_json,
    test_build_require_dispositions,
    test_build_layer_overrides_tip,
    test_build_layer_bad_count,
    test_build_layer_rejects_blind_key,
    test_build_layer_recheck_d8,
    test_build_source_join,
    test_build_writes_nothing_on_error,
    test_build_objections_failure_is_atomic,
    test_build_batch_flag_only_with_out_batches,
    test_build_reverifies_inputs,
    test_audit_metrics_fixture,
    test_audit_unmeasurable,
    test_audit_partial_blind,
    test_audit_subjective_excluded,
    test_audit_int_answers,
    test_audit_bad_blind_shape,
    test_audit_missing_file,
    test_audit_show_lists_mismatch,
    test_check_adversarial_is_argparse_error,
    test_check_help_names_stage_next_commands,
    test_subcommand_help_is_korean_and_complete,
]


if __name__ == "__main__":
    failures = []
    for test in TESTS:
        try:
            test()
            print(f"  ✓ {test.__name__}")
        except Exception:
            failures.append(test.__name__)
            print(f"  ✗ {test.__name__}")
            traceback.print_exc()
    print(f"실행한 테스트: {len(TESTS)}개")
    if failures:
        print(f"실패: {len(failures)}개 — {', '.join(failures)}")
        raise SystemExit(1)
    print("✓ blindwork 테스트 통과")

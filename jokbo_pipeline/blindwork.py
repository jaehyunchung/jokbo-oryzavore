# -*- coding: utf-8 -*-
# pyright: reportImplicitRelativeImport=false
"""블라인드 3단 분리 작업 폴더를 만들고 검증하는 공용 CLI (과목 무관).

    split    전사 배치 또는 추출 JSON을 구조층·봉인층·감사층으로 분리
    slice    구조층을 배치별·도판 유무별 풀이 묶음으로 균등 분할
    check    단계 산출물의 리터럴 형식과 키·개수·정합 검사
    scan     블라인드 답과 원본 답을 대조해 판정 작업목록 생성
    resolve  자동 판정과 수동 판정을 합쳐 해설 입력 확정
    build    구조·답·해설·선택 레이어를 최종 문항으로 조립
    audit    블라인드 답의 원본·최종 답 대비 지표 출력

작업 폴더의 주요 산출물:

    W/blind/<batch>.json                 구조층과 manifest
    W/sealed/sealed_key.json             봉인한 원본 답·해설
    W/_audit/prior_snapshot.json         기존 판단층(있을 때만)
    W/slices/<batch>__tNN|iNN.json       텍스트·도판 풀이 묶음
    W/solved/                            A 독립 풀이
    W/_reconcile/                        B 판정·C 해설·E 패치
    W/batches/ 또는 W/questions_data.py  최종 조립 출력
"""
import argparse
import ast
import importlib.util
import json
import math
import os
import pprint
import re
import shutil
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if __package__:
    from . import schema
else:
    sys.path.insert(0, str(HERE))
    import schema

Record = dict[str, Any]
BlindByBatch = dict[str, list[Record]]
RecordsByQid = dict[str, Record]
Manifest = list[Record]
PreparedSplit = tuple[BlindByBatch, RecordsByQid, RecordsByQid, RecordsByQid, Manifest]

CIRC = schema.CIRCLED_MARKERS
STRUCT_FIELDS = ("meta", "years", "stem", "options", "image", "images")
SEALED_FIELDS = ("orig_ans", "orig_expl", "recon", "image_missing")
AUDIT_FIELDS = (
    "verified", "answers", "flags", "source", "new_expl", "imp",
    "wrong_option_explanations", "tip", "scope_note", "related_theory",
    "clinical_summary", "image_caption", "image_captions",
)
LEAK_TOKENS = ["정답", "답:", "답 ", "orig_ans", "verified"]
AMBIG_RE = re.compile(r"또는|혹은|연도별|(?:19|20)\d{2}\s*년|\?")
NOANS_RE = re.compile(r"미표기|기록\s*없|정답\s*없|답\s*없|표기\s*없|불명|미상")
ROYAL_HINT_RE = re.compile(r"왕족|그대로\s*나왔|또\s*나왔|매년|해마다|수업\s*시간에.*알려")
_MD_RE = schema.MD_RE
norm = schema.norm_markers


class DataError(ValueError):
    """입력 데이터나 작업 상태가 계약을 어겼음을 나타낸다."""


class UsageError(ValueError):
    """argparse 이후에만 판별 가능한 잘못된 옵션 값을 나타낸다."""


class KoreanArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        add_help = kwargs.pop("add_help", True)
        super().__init__(*args, add_help=False, **kwargs)
        if add_help:
            self.add_argument("-h", "--help", action="help", help="이 도움말을 보여 주고 종료")


def markers(value: object) -> list[str]:
    """자유 텍스트의 원문자를 schema 정규화 규칙으로 추출한다."""
    return norm(value)


def parse_orig(orig: object, n_options: int | None = None) -> tuple[list[str] | None, str]:
    """원본 답을 선택지 범위 안에서 보수적으로 파싱해 마커와 상태를 반환한다."""
    if not orig or not str(orig).strip():
        return None, "empty"
    text = str(orig).strip()
    head = text.split("\n")[0]
    if NOANS_RE.search(head):
        return None, "none_recorded"
    match = re.search(r"(?:정답|답)\s*[:：]?\s*(.*)", head)
    segment = (match.group(1) if match else head).strip()
    if not segment:
        return None, "unparsed"
    if AMBIG_RE.search(segment):
        return None, "ambiguous"
    option_limit = len(CIRC) if n_options is None else min(max(n_options, 0), len(CIRC))
    found = markers(segment)
    if found:
        if any(CIRC.index(marker) >= option_limit for marker in found):
            return None, "unparsed"
    else:
        numbers = re.findall(r"(?<!\d)(\d+)(?!\d)\s*(?:번|번째)", segment)
        if not numbers:
            stripped = segment.rstrip(". ").strip()
            if re.fullmatch(r"\d+(?:\s*[,·/]\s*\d+)*", stripped):
                numbers = re.findall(r"\d+", stripped)
        for digits in numbers:
            number = int(digits)
            if 1 <= number <= option_limit:
                found.append(CIRC[number - 1])
                continue
            if n_options is None or number <= n_options:
                return None, "unparsed"
            split_numbers = [int(digit) for digit in digits]
            if not split_numbers or any(not 1 <= digit <= option_limit for digit in split_numbers):
                return None, "unparsed"
            found.extend(CIRC[digit - 1] for digit in split_numbers)
    if not found:
        return None, "unparsed"
    out = []
    for marker in found:
        if marker not in out:
            out.append(marker)
    return (out, "ok") if out else (None, "unparsed")


def classify(
    solved: Record, sealed: Record, struct: Record
) -> tuple[list[str] | None, str]:
    """원본 기록과 블라인드 답을 자동 판정하거나 대기 사유를 반환한다."""
    original, status = parse_orig(sealed.get("orig_ans"), len(struct.get("options") or []))
    blind = norm(solved.get("verified"), solved.get("answers"))
    if status in {"none_recorded", "empty"}:
        return ["TEXT_RECONSTRUCTED"], status
    if not (struct.get("options") or []):
        return None, "subjective"
    if status == "ok":
        if set(original or []) == set(blind):
            return ["ANSWER_MATCH"], "auto_match"
        return None, "mismatch"
    return None, status


def load_literal_list(path: str | Path, name: str) -> list[Any]:
    """단일 NAME=[...] 대입만 있는 단계 파일을 실행 없이 읽는다."""
    stage_path = Path(path)
    try:
        tree = ast.parse(stage_path.read_text(encoding="utf-8"), filename=str(stage_path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise DataError(f"{stage_path}: 리터럴만 허용 — 파일을 읽거나 파싱할 수 없음: {exc}") from exc

    statements = list(tree.body)
    if statements and isinstance(statements[0], ast.Expr):
        value = statements[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            statements.pop(0)
    if len(statements) != 1 or not isinstance(statements[0], ast.Assign):
        raise DataError(f"{stage_path}: 리터럴만 허용 — {name} = [...] 단일 대입이어야 함")
    assignment = statements[0]
    if (
        len(assignment.targets) != 1
        or not isinstance(assignment.targets[0], ast.Name)
        or assignment.targets[0].id != name
        or not isinstance(assignment.value, ast.List)
    ):
        raise DataError(f"{stage_path}: 리터럴만 허용 — {name} = [...] 단일 대입이어야 함")
    try:
        rows = ast.literal_eval(assignment.value)
    except (ValueError, TypeError, SyntaxError) as exc:
        raise DataError(f"{stage_path}: 리터럴만 허용 — {exc}") from exc
    if not isinstance(rows, list):
        raise DataError(f"{stage_path}: {name} 값은 리스트여야 함")
    return rows


def load_batches_exec(directory: str | Path) -> list[tuple[str, list[Record]]]:
    """신뢰 입력인 u*.py 배치를 실행해 QUESTIONS 목록을 읽는다."""
    batch_dir = Path(directory)
    if not batch_dir.is_dir():
        raise DataError(f"배치 폴더가 없습니다: {batch_dir}")
    paths = sorted(batch_dir.glob("u*.py"))
    if not paths:
        raise DataError(f"{batch_dir}에서 u*.py 배치를 찾지 못했습니다")
    batches = []
    for index, path in enumerate(paths):
        try:
            spec = importlib.util.spec_from_file_location(f"blindwork_batch_{index}", path)
            if spec is None or spec.loader is None:
                raise ImportError("모듈 로더를 만들 수 없음")
            module = importlib.util.module_from_spec(spec)
            previous_bytecode = sys.dont_write_bytecode
            sys.dont_write_bytecode = True
            try:
                spec.loader.exec_module(module)
            finally:
                sys.dont_write_bytecode = previous_bytecode
        except Exception as exc:
            raise DataError(f"배치 실행 실패: {path} — {exc}") from exc
        questions = getattr(module, "QUESTIONS", None)
        if not isinstance(questions, list):
            raise DataError(f"{path}: QUESTIONS 리스트가 없습니다")
        if not all(isinstance(question, dict) for question in questions):
            raise DataError(f"{path}: QUESTIONS의 모든 항목은 dict여야 합니다")
        batches.append((path.stem, questions))
    return batches


def read_json(path: str | Path):
    """JSON 파일을 읽고 실패를 데이터 오류로 바꾼다."""
    json_path = Path(path)
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DataError(f"JSON을 읽을 수 없습니다: {json_path} — {exc}") from exc


def write_json(path: str | Path, value) -> None:
    """JSON을 같은 디렉터리의 임시 파일에 쓴 뒤 원자적으로 교체한다."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=output.parent, prefix=f".{output.name}.", delete=False
    )
    temporary = Path(handle.name)
    try:
        with handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _has_stage_files(path: Path) -> bool:
    return path.is_dir() and any(candidate.is_file() for candidate in path.rglob("*"))


def _install_directories(work: Path, staged: Path, names: Sequence[str]) -> None:
    """스테이징된 산출물 디렉터리를 실패 시 복구하며 작업 폴더에 설치한다."""
    work_existed = work.exists()
    work.mkdir(parents=True, exist_ok=True)
    rollback = Path(tempfile.mkdtemp(prefix=".blindwork-rollback-", dir=work.parent))
    installed = []
    backed_up = []
    try:
        for name in names:
            target = work / name
            backup = rollback / name
            if target.exists():
                os.replace(target, backup)
                backed_up.append(name)
            source = staged / name
            if source.exists():
                os.replace(source, target)
                installed.append(name)
    except Exception:
        for name in reversed(installed):
            target = work / name
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink(missing_ok=True)
        for name in reversed(backed_up):
            os.replace(rollback / name, work / name)
        if not work_existed and work.is_dir() and next(work.iterdir(), None) is None:
            work.rmdir()
        raise
    finally:
        shutil.rmtree(rollback, ignore_errors=True)


def _allow_leaks(values: Sequence[str]) -> dict[str, str]:
    """QID=사유 옵션을 파싱하고 중복·빈값을 usage 오류로 거부한다."""
    allowed = {}
    for value in values:
        if "=" not in value:
            raise UsageError("--allow-leak은 QID=사유 형식이어야 합니다")
        qid, reason = value.split("=", 1)
        qid, reason = qid.strip(), reason.strip()
        if not qid or not reason:
            raise UsageError("--allow-leak의 qid와 사유는 비울 수 없습니다")
        if qid in allowed:
            raise UsageError(f"--allow-leak qid가 중복되었습니다: {qid}")
        allowed[qid] = reason
    return allowed


def _prepare_batch_split(directory: Path) -> PreparedSplit:
    """배치 입력 전체를 구조층·봉인층·감사층과 manifest로 투영한다."""
    blind_by_batch = {}
    sealed = {}
    audit = {}
    manifest = []
    for batch, questions in load_batches_exec(directory):
        rows = []
        for index, question in enumerate(questions):
            qid = f"{batch}#{index:03d}"
            row = {"qid": qid}
            row.update({field: question[field] for field in STRUCT_FIELDS if field in question})
            row["scope"] = question["scope"] if "scope" in question else batch
            rows.append(row)
            sealed[qid] = {
                field: question[field] for field in SEALED_FIELDS if field in question
            }
            audit[qid] = {
                field: question[field] for field in AUDIT_FIELDS if field in question
            }
        blind_by_batch[batch] = rows
        manifest.append(
            {
                "batch": batch,
                "count": len(rows),
                "with_image": sum(bool(row.get("image") or row.get("images")) for row in rows),
                "source": "batches",
                "input": str(directory),
            }
        )
    return blind_by_batch, sealed, audit, {}, manifest


def _indexed_rows(rows: object, source: Path) -> tuple[dict[int, Record], list[int]]:
    """extract JSON 레코드를 중복 없는 정수 idx 사전으로 검증한다."""
    if not isinstance(rows, list):
        raise DataError(f"{source}: JSON 최상위는 리스트여야 합니다")
    indexed = {}
    order = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("idx"), int):
            raise DataError(f"{source}: 모든 항목에 정수 idx가 있어야 합니다")
        idx = row["idx"]
        if idx in indexed:
            raise DataError(f"{source}: idx {idx}가 중복되었습니다")
        indexed[idx] = row
        order.append(idx)
    return indexed, order


def _prepare_extract_split(directory: Path) -> PreparedSplit:
    """extract의 구조 JSON과 답 JSON을 idx로 정확히 결합한다."""
    questions_path = directory / "all_questions.json"
    keys_path = directory / "answer_key.json"
    questions, order = _indexed_rows(read_json(questions_path), questions_path)
    keys, _key_order = _indexed_rows(read_json(keys_path), keys_path)
    question_ids, key_ids = set(questions), set(keys)
    if question_ids != key_ids:
        missing_keys = sorted(question_ids - key_ids)
        missing_questions = sorted(key_ids - question_ids)
        raise DataError(
            "all_questions.json과 answer_key.json의 idx가 1:1이 아닙니다: "
            f"답 없음 {missing_keys}, 문항 없음 {missing_questions}"
        )

    rows = []
    sealed = {}
    candidates = {}
    for idx in order:
        question = questions[idx]
        key = keys[idx]
        qid = f"extract#{idx:03d}"
        year = question.get("year")
        professor = schema.meta_nameonly(question.get("dept_prof")) or "교수미상"
        row = {
            "qid": qid,
            "meta": f"{year or '연도미상'} · {professor}",
            "years": [str(year)] if year else [],
            "stem": question.get("stem", ""),
            "options": question.get("options", []),
            "scope": question.get("scope", ""),
            "page": question.get("page"),
        }
        rows.append(row)
        sealed[qid] = {"orig_ans": key.get("answer"), "orig_expl": key.get("expl_raw")}
        image_candidates = question.get("candidate_images") or []
        if not isinstance(image_candidates, list) or not all(
            isinstance(filename, str) for filename in image_candidates
        ):
            raise DataError(f"{qid}: candidate_images는 파일명 리스트여야 합니다")
        if image_candidates:
            candidates[qid] = image_candidates

    manifest = [
        {
            "batch": "extract",
            "count": len(rows),
            "with_image": 0,
            "source": "extract",
            "input": str(directory),
        }
    ]
    return {"extract": rows}, sealed, {}, candidates, manifest


def _apply_image_map(blind_by_batch: BlindByBatch, image_map_path: Path | None) -> None:
    """검증한 qid별 이미지 맵으로 구조층의 기존 이미지 필드를 덮어쓴다."""
    if image_map_path is None:
        return
    mapping = read_json(image_map_path)
    if not isinstance(mapping, dict):
        raise DataError("--image-map JSON은 {qid: [파일명, ...]} 형식이어야 합니다")
    rows = {row["qid"]: row for batch_rows in blind_by_batch.values() for row in batch_rows}
    unknown = sorted(set(mapping) - set(rows))
    if unknown:
        raise DataError(f"--image-map에 입력에 없는 qid가 있습니다: {unknown}")
    for qid, filenames in mapping.items():
        if not isinstance(filenames, list) or not all(
            isinstance(filename, str) and filename for filename in filenames
        ):
            raise DataError(f"--image-map {qid}: 비어 있지 않은 파일명 리스트여야 합니다")
        row = rows[qid]
        row.pop("image", None)
        row.pop("images", None)
        if len(filenames) == 1:
            row["image"] = filenames[0]
        elif len(filenames) >= 2:
            row["images"] = filenames


def _find_leaks(blind_by_batch: BlindByBatch) -> list[tuple[str, str, str]]:
    """구조층 JSON 문자열에서 정답층 누출 토큰과 주변 문맥을 찾는다."""
    leaks = []
    for rows in blind_by_batch.values():
        for row in rows:
            blob = json.dumps(row, ensure_ascii=False)
            for token in LEAK_TOKENS:
                start = blob.find(token)
                if start >= 0:
                    context = blob[max(0, start - 60):start + len(token) + 60]
                    leaks.append((row["qid"], token, context))
                    break
    return leaks


def cmd_split(args: argparse.Namespace) -> int:
    """신뢰 배치 또는 extract JSON을 블라인드 작업 폴더의 세 층으로 분리한다."""
    work = Path(args.work)
    blind_target = work / "blind"
    if blind_target.exists() and not args.force:
        raise DataError(f"{blind_target}가 이미 있습니다 — 다시 만들려면 --force를 사용하세요")
    if args.force:
        blocked = [name for name in ("slices", "solved", "_reconcile") if _has_stage_files(work / name)]
        if blocked:
            raise DataError(
                "하류 산출물이 있어 입력을 바꿀 수 없습니다 — 해당 폴더를 직접 지운 뒤 다시 실행: "
                + ", ".join(blocked)
            )

    if args.batches is not None:
        prepared = _prepare_batch_split(Path(args.batches))
    else:
        prepared = _prepare_extract_split(Path(args.extract))
    blind_by_batch, sealed, audit, candidates, manifest = prepared
    all_qids = {row["qid"] for rows in blind_by_batch.values() for row in rows}
    allowed = _allow_leaks(args.allow_leak)
    unknown_allowed = sorted(set(allowed) - all_qids)
    if unknown_allowed:
        raise UsageError(f"--allow-leak에 입력에 없는 qid가 있습니다: {unknown_allowed}")

    _apply_image_map(blind_by_batch, Path(args.image_map) if args.image_map else None)
    for item in manifest:
        item["with_image"] = sum(
            bool(row.get("image") or row.get("images"))
            for row in blind_by_batch[item["batch"]]
        )
    leaks = _find_leaks(blind_by_batch)
    rejected = [leak for leak in leaks if leak[0] not in allowed]
    if rejected:
        lines = [f"누출 의심 {len(rejected)}건 — 파일을 쓰지 않았습니다"]
        lines.extend(f"{qid} [{token}] …{context}…" for qid, token, context in rejected[:40])
        raise DataError("\n  ✗ ".join(lines))

    used_allowed = {qid for qid, _token, _context in leaks if qid in allowed}
    allow_rows = [
        {"qid": qid, "token": token, "reason": allowed[qid]}
        for qid, token, _context in leaks
        if qid in allowed
    ]
    unused_allowed = sorted(set(allowed) - used_allowed)

    work.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".blindwork-split-", dir=work.parent) as temp_dir:
        staged = Path(temp_dir)
        for batch, rows in blind_by_batch.items():
            write_json(staged / "blind" / f"{batch}.json", rows)
        write_json(staged / "blind" / "_manifest.json", manifest)
        if manifest and manifest[0]["source"] == "extract":
            write_json(staged / "blind" / "_image_candidates.json", candidates)
        if allow_rows:
            write_json(staged / "blind" / "_leak_allow.json", allow_rows)
        write_json(staged / "sealed" / "sealed_key.json", sealed)
        if any(snapshot for snapshot in audit.values()):
            write_json(staged / "_audit" / "prior_snapshot.json", audit)
        names = ("blind", "sealed", "_audit", "slices") if args.force else ("blind", "sealed", "_audit")
        _install_directories(work, staged, names)

    total = sum(item["count"] for item in manifest)
    print(f"✓ 블라인드 {total}문항 · 배치 {len(manifest)}개")
    print(f"   blind/   {work / 'blind'}")
    print(f"   sealed/  {work / 'sealed' / 'sealed_key.json'}")
    if any(snapshot for snapshot in audit.values()):
        print(f"   _audit/  {work / '_audit' / 'prior_snapshot.json'}")
    for qid in unused_allowed:
        print(f"⚠ 미사용 허용: {qid} — 구조층에서 누출 토큰을 찾지 못함")
    if allow_rows:
        print(f"⚠ 누출 허용 {len(allow_rows)}건 — 사유를 _leak_allow.json에 기록")
    else:
        print("✓ 누출 게이트 통과 — 구조층에 정답 표기 없음")
    return 0


def _chunk(rows: list[Record], size: int) -> list[list[Record]]:
    """목표 크기를 넘는 행을 ceil 기반의 가능한 균등한 묶음으로 나눈다."""
    if not rows:
        return []
    count = max(1, math.ceil(len(rows) / size))
    per_chunk = math.ceil(len(rows) / count)
    return [
        rows[index * per_chunk:(index + 1) * per_chunk]
        for index in range(count)
        if rows[index * per_chunk:(index + 1) * per_chunk]
    ]


def _load_blind_batches(work: Path) -> list[tuple[str, list[Record]]]:
    """blind manifest 순서대로 배치 JSON을 읽고 개수·qid 무결성을 확인한다."""
    manifest_path = work / "blind" / "_manifest.json"
    manifest = read_json(manifest_path)
    if not isinstance(manifest, list):
        raise DataError(f"{manifest_path}: 리스트 manifest여야 합니다")
    batches = []
    seen_batches = set()
    seen_qids = set()
    for item in manifest:
        if not isinstance(item, dict) or not isinstance(item.get("batch"), str):
            raise DataError(f"{manifest_path}: 각 항목에 batch 문자열이 필요합니다")
        batch = item["batch"]
        if batch in seen_batches:
            raise DataError(f"{manifest_path}: batch가 중복되었습니다: {batch}")
        seen_batches.add(batch)
        path = work / "blind" / f"{batch}.json"
        rows = read_json(path)
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise DataError(f"{path}: 문항 dict 리스트여야 합니다")
        if item.get("count") != len(rows):
            raise DataError(f"{path}: manifest count {item.get('count')}와 실제 {len(rows)}가 다릅니다")
        for row in rows:
            qid = row.get("qid")
            if not isinstance(qid, str) or not qid:
                raise DataError(f"{path}: 비어 있지 않은 qid 문자열이 필요합니다")
            if qid in seen_qids:
                raise DataError(f"blind 전체에서 qid가 중복되었습니다: {qid}")
            seen_qids.add(qid)
        batches.append((batch, rows))
    return batches


def cmd_slice(args: argparse.Namespace) -> int:
    """blind 문항을 배치 경계와 도판 유무를 보존해 균등 분할한다."""
    work = Path(args.work)
    slices_target = work / "slices"
    solved_files = (
        sorted(path for path in (work / "solved").rglob("*.py") if path.is_file())
        if (work / "solved").is_dir()
        else []
    )
    if solved_files:
        raise DataError(
            "풀이 산출물이 있어 슬라이스를 바꿀 수 없습니다 — solved 아래 .py를 직접 정리하세요: "
            + ", ".join(str(path) for path in solved_files[:10])
        )
    if slices_target.exists() and not args.force:
        raise DataError(f"{slices_target}가 이미 있습니다 — 다시 만들려면 --force를 사용하세요")

    batches = _load_blind_batches(work)
    manifest = []
    outputs = {}
    for batch, rows in batches:
        text_rows = [row for row in rows if not (row.get("image") or row.get("images"))]
        image_rows = [row for row in rows if row.get("image") or row.get("images")]
        groups = (
            ("t", _chunk(text_rows, args.text_size)),
            ("i", _chunk(image_rows, args.image_size)),
        )
        for kind, parts in groups:
            for index, part in enumerate(parts, 1):
                name = f"{batch}__{kind}{index:02d}"
                outputs[name] = part
                image_files = sum(
                    len(row.get("images") or ([row["image"]] if row.get("image") else []))
                    for row in part
                )
                manifest.append(
                    {
                        "slice": name,
                        "batch": batch,
                        "kind": kind,
                        "count": len(part),
                        "image_files": image_files,
                        "qids": [row["qid"] for row in part],
                    }
                )

    work.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".blindwork-slice-", dir=work.parent) as temp_dir:
        staged = Path(temp_dir)
        for name, rows in outputs.items():
            write_json(staged / "slices" / f"{name}.json", rows)
        write_json(staged / "slices" / "_manifest.json", manifest)
        _install_directories(work, staged, ("slices",))
    (work / "solved" / "_patch").mkdir(parents=True, exist_ok=True)

    text = [item for item in manifest if item["kind"] == "t"]
    images = [item for item in manifest if item["kind"] == "i"]
    print(f"✓ 슬라이스 {len(manifest)}개 → {work / 'slices'}")
    print(f"   텍스트 {len(text)}슬라이스 · {sum(item['count'] for item in text)}문항")
    print(
        f"   도판   {len(images)}슬라이스 · {sum(item['count'] for item in images)}문항 "
        f"· 도판 {sum(item['image_files'] for item in images)}장"
    )
    return 0


SOLVED_ALLOWED = {
    "qid", "verified", "answers", "confidence", "blind_note",
    "option_judgments", "dispute_note",
}
SOLVED_REQUIRED = {"qid", "verified", "confidence", "blind_note", "option_judgments"}
ADJUDICATED_ALLOWED = {"qid", "flags", "verified", "answers", "source", "scope_note"}
ADJUDICATED_REQUIRED = {"qid", "flags"}
EXPLAINED_ALLOWED = {
    "qid", "new_expl", "imp", "wrong_option_explanations", "tip", "source", "objection",
}
EXPLAINED_REQUIRED = {"qid", "new_expl", "imp", "wrong_option_explanations"}
ANSWER_FLAGS = {"ANSWER_MATCH", "ANSWER_CORRECTED", "ANSWER_DISPUTED"}


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _text(value: object) -> str:
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value or "")


def _reject_markdown(qid: str, fields: Sequence[tuple[str, object]]) -> None:
    for field, value in fields:
        if _MD_RE.search(_text(value)):
            raise DataError(f"{qid}: {field}에 마크다운 강조 표기가 있습니다")


def _check_row_keys(
    row: object, source: Path, allowed: set[str], required: set[str], stage: str
) -> Record:
    if not isinstance(row, dict):
        raise DataError(f"{source}: {stage} 항목은 dict여야 합니다")
    extra = sorted(set(row) - allowed)
    if extra:
        if stage == "EXPLAINED":
            raise DataError(
                f"{source}: 이 단계는 해설만 쓴다 — 허용되지 않은 키: {', '.join(extra)}"
            )
        raise DataError(f"{source}: 허용되지 않은 키: {', '.join(extra)}")
    missing = sorted(required - set(row))
    if missing:
        raise DataError(f"{source}: 필수 키 누락: {', '.join(missing)}")
    qid = row.get("qid")
    if not _nonempty_string(qid):
        raise DataError(f"{source}: 비어 있지 않은 qid 문자열이 필요합니다")
    return row


def _validate_answer(qid: str, row: Record, options: list[object]) -> None:
    verified = row.get("verified")
    if not _nonempty_string(verified):
        raise DataError(f"{qid}: verified는 비어 있지 않은 문자열이어야 합니다")
    answer_markers = markers(verified)
    answers = row.get("answers")
    if not options:
        if answers not in (None, []):
            raise DataError(f"{qid}: 주관식에는 answers를 쓸 수 없습니다")
        return
    if not answer_markers:
        raise DataError(f"{qid}: 객관식 verified에 정답 마커가 없습니다")
    out_of_range = [marker for marker in answer_markers if CIRC.index(marker) >= len(options)]
    if out_of_range:
        raise DataError(f"{qid}: 정답 마커가 선지 범위를 벗어났습니다: {out_of_range}")
    if len(answer_markers) >= 2 and answers is None:
        raise DataError(f"{qid}: 복수정답 verified에는 answers가 필요합니다")
    if answers is None:
        return
    if len(answer_markers) < 2:
        raise DataError(f"{qid}: answers는 정답이 2개 이상일 때만 허용됩니다")
    if not isinstance(answers, list) or not all(
        isinstance(answer, str) and markers(answer) == [answer] for answer in answers
    ):
        raise DataError(f"{qid}: answers는 정답 마커 리스트여야 합니다")
    if set(answers) != set(answer_markers):
        raise DataError(f"{qid}: answers와 verified 마커가 일치하지 않습니다")


def _check_solved_file(work: Path, path: Path, patch: bool) -> list[Record]:
    rows = load_literal_list(path, "SOLVED")
    slice_path = work / "slices" / f"{path.stem}.json"
    slice_rows = read_json(slice_path)
    if not isinstance(slice_rows, list) or not all(isinstance(row, dict) for row in slice_rows):
        raise DataError(f"{slice_path}: 문항 dict 리스트여야 합니다")
    slice_qids = [row.get("qid") for row in slice_rows]
    slice_by_qid = {row.get("qid"): row for row in slice_rows}
    checked = []
    seen = set()
    for raw in rows:
        row = _check_row_keys(raw, path, SOLVED_ALLOWED, SOLVED_REQUIRED, "SOLVED")
        qid = row["qid"]
        if qid in seen:
            raise DataError(f"{path}: qid가 중복되었습니다: {qid}")
        seen.add(qid)
        if qid not in slice_by_qid:
            raise DataError(f"{path}: 대응 slice 밖 qid입니다: {qid}")
        struct = slice_by_qid[qid]
        options = struct.get("options") or []
        if not isinstance(options, list):
            raise DataError(f"{qid}: options는 리스트여야 합니다")
        _validate_answer(qid, row, options)
        if row.get("confidence") not in schema.BLIND_CONFIDENCE:
            raise DataError(f"{qid}: confidence는 high, medium, low 중 하나여야 합니다")
        if not _nonempty_string(row.get("blind_note")):
            raise DataError(f"{qid}: blind_note를 비울 수 없습니다")
        judgments = row.get("option_judgments")
        if not isinstance(judgments, list) or len(judgments) != len(options):
            raise DataError(
                f"{qid}: option_judgments 수 {len(judgments) if isinstance(judgments, list) else '비리스트'}"
                f"와 선지 수 {len(options)}가 다릅니다"
            )
        for index, judgment in enumerate(judgments):
            marker = CIRC[index]
            if not isinstance(judgment, str) or not judgment.strip().startswith(marker):
                raise DataError(f"{qid}: option_judgments {index + 1}번은 {marker}로 시작해야 합니다")
            if "참" not in judgment and "거짓" not in judgment:
                raise DataError(f"{qid}: option_judgments {index + 1}번에 참 또는 거짓이 필요합니다")
        _reject_markdown(
            qid,
            [
                ("verified", row.get("verified")),
                ("blind_note", row.get("blind_note")),
                ("dispute_note", row.get("dispute_note")),
                ("option_judgments", judgments),
            ],
        )
        checked.append(row)
    row_qids = [row["qid"] for row in checked]
    if patch:
        expected_order = [qid for qid in slice_qids if qid in seen]
        if row_qids != expected_order:
            raise DataError(f"{path}: 패치 qid가 대응 slice 순서와 다릅니다")
    elif row_qids != slice_qids:
        raise DataError(f"{path}: 문항 수·qid·순서가 대응 slice와 다릅니다")
    return checked


def _final_answer(adjudicated: Record, solved: Record) -> Record:
    final = {"verified": adjudicated.get("verified", solved.get("verified"))}
    answers = adjudicated.get("answers", solved.get("answers"))
    if answers is not None:
        final["answers"] = answers
    return final


def _pending_qids(ctx: Record, batch: str) -> list[str]:
    pending = []
    for struct in ctx["batch_rows"][batch]:
        qid = struct["qid"]
        solved = ctx["solved"].get(qid)
        if solved is None:
            continue
        flags, _why = classify(solved, ctx["sealed"].get(qid, {}), struct)
        if flags is None:
            pending.append(qid)
    return pending


def _check_adjudicated_rows(
    ctx: Record, batch: str, rows: list[object], source: Path
) -> list[Record]:
    if batch not in ctx["batch_rows"]:
        raise DataError(f"{source}: manifest에 없는 배치입니다: {batch}")
    batch_qids = {row["qid"] for row in ctx["batch_rows"][batch]}
    checked = []
    seen = set()
    for raw in rows:
        row = _check_row_keys(
            raw, source, ADJUDICATED_ALLOWED, ADJUDICATED_REQUIRED, "ADJUDICATED"
        )
        qid = row["qid"]
        if qid in seen:
            raise DataError(f"{source}: qid가 중복되었습니다: {qid}")
        seen.add(qid)
        if qid not in batch_qids:
            raise DataError(f"{source}: manifest 배치 밖 qid입니다: {qid}")
        solved = ctx["solved"].get(qid)
        if solved is None:
            raise DataError(f"{source}: SOLVED가 없는 qid를 판정했습니다: {qid}")
        flags = row.get("flags")
        if not isinstance(flags, list) or not all(isinstance(flag, str) for flag in flags):
            raise DataError(f"{qid}: flags는 문자열 리스트여야 합니다")
        unknown = sorted(set(flags) - set(schema.FLAG_TAXONOMY))
        if unknown:
            raise DataError(f"{qid}: 알 수 없는 flags: {unknown}")
        forbidden = {"STEM_IMAGE_A_PRESENT", "IMAGE_MISSING"} & set(flags)
        if forbidden:
            raise DataError(f"{qid}: 판정 단계에서 이미지 플래그를 쓸 수 없습니다: {sorted(forbidden)}")
        answer_flags = set(flags) & (ANSWER_FLAGS | {"TEXT_RECONSTRUCTED"})
        valid = [
            {"ANSWER_MATCH"},
            {"ANSWER_CORRECTED"},
            {"ANSWER_DISPUTED"},
            {"TEXT_RECONSTRUCTED"},
            {"TEXT_RECONSTRUCTED", "ANSWER_DISPUTED"},
        ]
        if answer_flags not in valid:
            raise DataError(f"{qid}: flags의 답 판정 조합이 올바르지 않습니다: {flags}")
        struct = ctx["blind"][qid]
        sealed = ctx["sealed"].get(qid, {})
        options = struct.get("options") or []
        final = _final_answer(row, solved)
        _validate_answer(qid, final, options)
        original, status = parse_orig(sealed.get("orig_ans"), len(options))
        final_markers = norm(final.get("verified"), final.get("answers"))
        if "TEXT_RECONSTRUCTED" in flags and status not in {"none_recorded", "empty"}:
            raise DataError(f"{qid}: 원본 답이 비어 있지 않아 TEXT_RECONSTRUCTED를 쓸 수 없습니다")
        objective_parsed = bool(options) and status == "ok"
        if objective_parsed:
            same = set(final_markers) == set(original or [])
            if "ANSWER_MATCH" in flags and not same:
                raise DataError(f"{qid}: ANSWER_MATCH인데 최종 답이 원본 답과 다릅니다")
            if "ANSWER_CORRECTED" in flags and same:
                raise DataError(f"{qid}: ANSWER_CORRECTED인데 최종 답이 원본 답과 같습니다")
            if "ANSWER_DISPUTED" in flags and not same:
                raise DataError(f"{qid}: ANSWER_DISPUTED는 원본 답을 유지해야 합니다")
        elif ("ANSWER_MATCH" in flags or "ANSWER_DISPUTED" in flags) and "verified" not in row:
            raise DataError(f"{qid}: 원본 파싱 불가·주관식 판정에는 verified를 명시해야 합니다")
        if ("ANSWER_CORRECTED" in flags or "ANSWER_DISPUTED" in flags) and not _nonempty_string(
            row.get("source")
        ):
            raise DataError(f"{qid}: 정정·논쟁 판정에는 source가 필요합니다")
        if "ANSWER_DISPUTED" in flags and not _nonempty_string(row.get("scope_note")):
            raise DataError(f"{qid}: ANSWER_DISPUTED에는 scope_note가 필요합니다")
        _reject_markdown(
            qid, [("source", row.get("source")), ("scope_note", row.get("scope_note"))]
        )
        checked.append(row)
    missing = [qid for qid in _pending_qids(ctx, batch) if qid not in seen]
    if missing:
        raise DataError(f"{source}: 판정 대기 qid 누락: {', '.join(missing)}")
    return checked


def _check_adjudicated_file(ctx: Record, path: Path) -> list[Record]:
    rows = load_literal_list(path, "ADJUDICATED")
    return _check_adjudicated_rows(ctx, path.stem, rows, path)


def _check_explained_file(work: Path, path: Path) -> tuple[list[Record], list[str]]:
    resolved_path = work / "_reconcile" / "resolved" / f"{path.stem}.json"
    if not resolved_path.is_file():
        raise DataError(f"{resolved_path}가 없습니다 — resolve 먼저 실행하세요")
    resolved = read_json(resolved_path)
    if not isinstance(resolved, list) or not all(isinstance(row, dict) for row in resolved):
        raise DataError(f"{resolved_path}: 문항 dict 리스트여야 합니다")
    rows = load_literal_list(path, "EXPLAINED")
    resolved_by_qid = {row.get("qid"): row for row in resolved}
    expected_qids = [row.get("qid") for row in resolved]
    checked = []
    warnings = []
    seen = set()
    for raw in rows:
        row = _check_row_keys(raw, path, EXPLAINED_ALLOWED, EXPLAINED_REQUIRED, "EXPLAINED")
        qid = row["qid"]
        if qid in seen:
            raise DataError(f"{path}: qid가 중복되었습니다: {qid}")
        seen.add(qid)
        if qid not in resolved_by_qid:
            raise DataError(f"{path}: resolved에 없는 qid입니다: {qid}")
        base = resolved_by_qid[qid]
        new_expl = row.get("new_expl")
        if not isinstance(new_expl, (str, list)) or (
            isinstance(new_expl, list)
            and (not new_expl or not all(_nonempty_string(item) for item in new_expl))
        ):
            raise DataError(f"{qid}: new_expl은 문자열 또는 비어 있지 않은 문단 리스트여야 합니다")
        explanation_text = _text(new_expl)
        if len(schema.strip_royal(explanation_text)) < 40:
            raise DataError(f"{qid}: new_expl은 왕족 태그 제외 40자 이상이어야 합니다")
        if len(explanation_text) > 900:
            warnings.append(f"{qid}: new_expl이 900자를 넘습니다")
        if not _nonempty_string(row.get("imp")):
            raise DataError(f"{qid}: imp를 비울 수 없습니다")
        wrong = row.get("wrong_option_explanations")
        if not isinstance(wrong, list) or not all(_nonempty_string(item) for item in wrong):
            raise DataError(f"{qid}: wrong_option_explanations는 비어 있지 않은 문자열 리스트여야 합니다")
        options = base.get("options") or []
        if options:
            correct = set(norm(base.get("verified"), base.get("answers")))
            expected_wrong = [CIRC[index] for index in range(len(options)) if CIRC[index] not in correct]
            actual_wrong = [item.strip()[0] if item.strip() else "" for item in wrong]
            if actual_wrong != expected_wrong:
                raise DataError(
                    f"{qid}: wrong_option_explanations 마커가 오답 선지와 다릅니다 "
                    f"(기대 {expected_wrong}, 실제 {actual_wrong})"
                )
        elif len(wrong) != 1 or "\n" in wrong[0] or markers(wrong[0]):
            raise DataError(f"{qid}: 주관식 오답선지 해설은 마커 없는 한 줄이어야 합니다")
        if "ANSWER_DISPUTED" in (base.get("flags") or []) and "⚠" not in explanation_text:
            raise DataError(f"{qid}: ANSWER_DISPUTED 해설 본문에는 ⚠ 경고가 필요합니다")
        if len(set(base.get("years") or [])) >= 3 and "【왕족】" not in explanation_text:
            warnings.append(f"{qid}: 3개 연도 이상인데 【왕족】 태그가 없습니다")
        if "objection" in row and not _nonempty_string(row.get("objection")):
            raise DataError(f"{qid}: objection은 비어 있지 않은 문자열이어야 합니다")
        _reject_markdown(
            qid,
            [
                ("new_expl", new_expl),
                ("imp", row.get("imp")),
                ("wrong_option_explanations", wrong),
                ("tip", row.get("tip")),
            ],
        )
        checked.append(row)
    if [row["qid"] for row in checked] != expected_qids:
        raise DataError(f"{path}: 문항 수·qid·순서가 resolved와 다릅니다")
    return checked, warnings


def load_context(work_value: str | Path) -> Record:
    work = Path(work_value)
    batches = _load_blind_batches(work)
    batch_rows = {batch: rows for batch, rows in batches}
    blind = {row["qid"]: row for _batch, rows in batches for row in rows}
    sealed_path = work / "sealed" / "sealed_key.json"
    sealed = read_json(sealed_path)
    if not isinstance(sealed, dict) or not all(isinstance(value, dict) for value in sealed.values()):
        raise DataError(f"{sealed_path}: qid별 봉인 dict여야 합니다")
    unknown_sealed = sorted(set(sealed) - set(blind))
    if unknown_sealed:
        raise DataError(f"{sealed_path}: blind에 없는 qid가 있습니다: {unknown_sealed}")
    ctx: Record = {
        "work": work,
        "batches": batches,
        "batch_rows": batch_rows,
        "blind": blind,
        "sealed": sealed,
        "solved": {},
        "adjudicated": {},
        "resolved": {},
    }
    solved_dir = work / "solved"
    base_seen = set()
    for path in sorted(solved_dir.glob("*.py")) if solved_dir.is_dir() else []:
        for row in _check_solved_file(work, path, False):
            qid = row["qid"]
            if qid in base_seen:
                raise DataError(f"SOLVED qid가 여러 파일에 중복되었습니다: {qid}")
            base_seen.add(qid)
            ctx["solved"][qid] = row
    patch_seen = set()
    patch_dir = solved_dir / "_patch"
    for path in sorted(patch_dir.glob("*.py")) if patch_dir.is_dir() else []:
        for row in _check_solved_file(work, path, True):
            qid = row["qid"]
            if qid in patch_seen:
                raise DataError(f"SOLVED 패치 qid가 여러 파일에 중복되었습니다: {qid}")
            patch_seen.add(qid)
            ctx["solved"][qid] = row
    adjudicated_dir = work / "_reconcile" / "adjudicated"
    adjudicated_seen = set()
    for path in sorted(adjudicated_dir.glob("*.py")) if adjudicated_dir.is_dir() else []:
        for row in _check_adjudicated_file(ctx, path):
            qid = row["qid"]
            if qid in adjudicated_seen:
                raise DataError(f"ADJUDICATED qid가 여러 파일에 중복되었습니다: {qid}")
            adjudicated_seen.add(qid)
            ctx["adjudicated"][qid] = row
    resolved_dir = work / "_reconcile" / "resolved"
    for path in sorted(resolved_dir.glob("*.json")) if resolved_dir.is_dir() else []:
        rows = read_json(path)
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise DataError(f"{path}: 문항 dict 리스트여야 합니다")
        ctx["resolved"][path.stem] = rows
    return ctx


def _selected_batches(ctx: Record, batch: str | None) -> list[str]:
    names = [name for name, _rows in ctx["batches"]]
    if batch is not None:
        if batch not in ctx["batch_rows"]:
            raise DataError(f"manifest에 없는 배치입니다: {batch}")
        return [batch]
    return names


def _worklist_row(struct: Record, solved: Record, sealed: Record, why: str) -> Record:
    row = {
        "qid": struct["qid"],
        "why": why,
        "meta": struct.get("meta"),
        "years": struct.get("years"),
        "stem": struct.get("stem"),
        "options": struct.get("options"),
        "blind_verified": solved.get("verified"),
        "blind_answers": solved.get("answers"),
        "blind_confidence": solved.get("confidence"),
        "blind_note": solved.get("blind_note"),
        "blind_option_judgments": solved.get("option_judgments"),
        "blind_dispute_note": solved.get("dispute_note"),
        "orig_ans": sealed.get("orig_ans"),
        "orig_expl": sealed.get("orig_expl"),
        "recon": sealed.get("recon"),
    }
    for field in ("image", "images"):
        if field in struct:
            row[field] = struct[field]
    return row


def _scan_context(ctx: Record, batches: Sequence[str], include_adjudicated: bool) -> tuple[Record, Record]:
    stats: Record = {
        "total": 0,
        "unsolved": 0,
        "adjudicated": 0,
        "auto_match": 0,
        "none_recorded": 0,
        "mismatch": 0,
        "ambiguous": 0,
        "unparsed": 0,
        "subjective": 0,
        "pending": 0,
        "pending_qids": [],
        "unsolved_qids": [],
    }
    worklists = {batch: [] for batch in batches}
    for batch in batches:
        for struct in ctx["batch_rows"][batch]:
            stats["total"] += 1
            qid = struct["qid"]
            solved = ctx["solved"].get(qid)
            if solved is None:
                stats["unsolved"] += 1
                stats["unsolved_qids"].append(qid)
                continue
            if include_adjudicated and qid in ctx["adjudicated"]:
                stats["adjudicated"] += 1
                continue
            flags, why = classify(solved, ctx["sealed"].get(qid, {}), struct)
            if flags == ["ANSWER_MATCH"]:
                stats["auto_match"] += 1
            elif flags == ["TEXT_RECONSTRUCTED"]:
                stats["none_recorded"] += 1
            else:
                stats[why] += 1
                stats["pending"] += 1
                stats["pending_qids"].append(qid)
                worklists[batch].append(
                    _worklist_row(struct, solved, ctx["sealed"].get(qid, {}), why)
                )
    return stats, worklists


def cmd_check(args: argparse.Namespace) -> int:
    work = Path(args.work)
    path = Path(args.file)
    if args.patch and args.stage != "solve":
        raise UsageError("--patch는 solve 단계에서만 사용할 수 있습니다")
    if args.stage == "solve":
        rows = _check_solved_file(work, path, bool(args.patch))
        warnings: list[str] = []
    elif args.stage == "adjudicate":
        ctx = load_context(work)
        rows = _check_adjudicated_file(ctx, path)
        warnings = []
    elif args.stage == "explain":
        rows, warnings = _check_explained_file(work, path)
    else:
        raise SystemExit("미구현")
    for warning in warnings:
        print(f"⚠ {warning}")
    print(f"✓ {args.stage} 검사 통과 · {len(rows)}문항 · {path}")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    ctx = load_context(args.work)
    batches = _selected_batches(ctx, args.batch)
    stats, worklists = _scan_context(ctx, batches, not args.all)
    for batch, rows in worklists.items():
        write_json(Path(args.work) / "_reconcile" / "worklist" / f"{batch}.json", rows)
    (Path(args.work) / "_reconcile" / "adjudicated").mkdir(parents=True, exist_ok=True)
    if args.as_json:
        print(json.dumps(stats, ensure_ascii=False))
        return 0
    print(f"총 {stats['total']}문항")
    for key in (
        "unsolved", "adjudicated", "auto_match", "none_recorded", "mismatch",
        "ambiguous", "unparsed", "subjective", "pending",
    ):
        print(f"   {key:16s} {stats[key]:4d}")
    if stats["pending_qids"]:
        print("판정 대기: " + ", ".join(stats["pending_qids"]))
    if stats["unsolved_qids"]:
        print("⚠ Phase A 미집필: " + ", ".join(stats["unsolved_qids"]))
    return 0


def resolve_rows(ctx: Record, batch: str) -> list[Record]:
    if batch not in ctx["batch_rows"]:
        raise DataError(f"manifest에 없는 배치입니다: {batch}")
    unsolved = [
        struct["qid"] for struct in ctx["batch_rows"][batch]
        if struct["qid"] not in ctx["solved"]
    ]
    if unsolved:
        raise DataError("SOLVED 미집필 qid: " + ", ".join(unsolved))
    pending = []
    resolved = []
    for struct in ctx["batch_rows"][batch]:
        qid = struct["qid"]
        solved = ctx["solved"][qid]
        sealed = ctx["sealed"].get(qid, {})
        adjudicated = ctx["adjudicated"].get(qid)
        automatic, _why = classify(solved, sealed, struct)
        if adjudicated is None and automatic is None:
            pending.append(qid)
            continue
        final = _final_answer(adjudicated, solved) if adjudicated is not None else {
            "verified": solved.get("verified"),
            **({"answers": solved["answers"]} if solved.get("answers") is not None else {}),
        }
        flags = adjudicated["flags"] if adjudicated is not None else automatic
        row: Record = {
            "qid": qid,
            "meta": struct.get("meta"),
            "years": struct.get("years"),
            "stem": struct.get("stem"),
            "options": struct.get("options") or [],
            "verified": final["verified"],
            "flags": flags,
            "blind": {
                "verified": solved.get("verified"),
                "confidence": solved.get("confidence"),
                "note": solved.get("blind_note"),
                "option_judgments": solved.get("option_judgments"),
            },
            "orig_ans": sealed.get("orig_ans"),
            "orig_expl": sealed.get("orig_expl"),
        }
        if final.get("answers") is not None:
            row["answers"] = final["answers"]
        if solved.get("answers") is not None:
            row["blind"]["answers"] = solved["answers"]
        if solved.get("dispute_note") is not None:
            row["blind"]["dispute_note"] = solved["dispute_note"]
        for field in ("image", "images", "scope"):
            if field in struct:
                row[field] = struct[field]
        for field in ("recon", "image_missing"):
            if field in sealed:
                row[field] = sealed[field]
        if adjudicated is not None:
            for field in ("source", "scope_note"):
                if field in adjudicated:
                    row[field] = adjudicated[field]
        resolved.append(row)
    if pending:
        raise DataError("판정 대기 qid: " + ", ".join(pending))
    return resolved


def cmd_resolve(args: argparse.Namespace) -> int:
    ctx = load_context(args.work)
    batches = _selected_batches(ctx, args.batch)
    prepared = {batch: resolve_rows(ctx, batch) for batch in batches}
    target = Path(args.work) / "_reconcile" / "resolved"
    for batch, rows in prepared.items():
        write_json(target / f"{batch}.json", rows)
    for directory in ("explained", "adversarial"):
        (Path(args.work) / "_reconcile" / directory).mkdir(parents=True, exist_ok=True)
    print(f"✓ resolve 완료 · {sum(len(rows) for rows in prepared.values())}문항 · {target}")
    return 0


FINAL_KEY_ORDER = [
    "qid", "meta", "years", "flags", "stem", "options", "image", "images",
    "verified", "answers", "source", "new_expl", "imp",
    "wrong_option_explanations", "tip", "recon", "image_missing", "scope_note",
    "orig_ans", "orig_expl", "blind",
]
LAYER_ALLOWED = {
    "qid", "verified", "answers", "flags", "source", "scope_note", "new_expl",
    "imp", "wrong_option_explanations", "tip", "objection_disposition",
}


def group_scopes(rows: list[Record]) -> list[tuple[str, list[Record]]]:
    grouped: dict[str, list[Record]] = {}
    for row in rows:
        label = row.get("scope") or "미분류"
        question = {key: row[key] for key in FINAL_KEY_ORDER if key in row}
        grouped.setdefault(label, []).append(question)
    return list(grouped.items())


def _parse_layers(value: str) -> list[str]:
    layers = [item.strip() for item in value.split(",") if item.strip()]
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", layer) for layer in layers):
        raise UsageError("--layers는 쉼표로 구분한 영문 이름이어야 합니다")
    return layers


def _changed_qids(expected: list[Record], stored: list[Record]) -> list[str]:
    expected_by_qid = {row.get("qid"): row for row in expected}
    stored_by_qid = {row.get("qid"): row for row in stored}
    order = [row.get("qid") for row in expected] + [row.get("qid") for row in stored]
    changed = []
    for qid in order:
        if qid not in changed and expected_by_qid.get(qid) != stored_by_qid.get(qid):
            changed.append(str(qid))
    if expected != stored and not changed:
        return ["(행 순서)"]
    return changed


def _load_explained(work: Path, batches: Sequence[str]) -> tuple[RecordsByQid, list[str]]:
    explained: RecordsByQid = {}
    warnings = []
    for batch in batches:
        path = work / "_reconcile" / "explained" / f"{batch}.py"
        if not path.is_file():
            raise DataError(f"{batch}: C 미집필 — {path}가 없습니다")
        rows, row_warnings = _check_explained_file(work, path)
        warnings.extend(row_warnings)
        for row in rows:
            qid = row["qid"]
            if qid in explained:
                raise DataError(f"EXPLAINED qid가 여러 파일에 중복되었습니다: {qid}")
            explained[qid] = row
    return explained, warnings


def _load_layer_rows(
    work: Path, layers: Sequence[str], batches: Sequence[str], all_qids: set[str]
) -> tuple[list[tuple[str, Record]], dict[str, Record]]:
    overlays: list[tuple[str, Record]] = []
    dispositions: dict[str, Record] = {}
    for layer in layers:
        seen = set()
        for batch in batches:
            path = work / "_reconcile" / layer / f"{batch}.py"
            if not path.is_file():
                continue
            for raw in load_literal_list(path, layer.upper()):
                row = _check_row_keys(raw, path, LAYER_ALLOWED, {"qid"}, layer.upper())
                qid = row["qid"]
                if qid not in all_qids:
                    raise DataError(f"{path}: manifest에 없는 qid입니다: {qid}")
                if qid in seen:
                    raise DataError(f"{path}: 같은 레이어에 qid가 중복되었습니다: {qid}")
                seen.add(qid)
                disposition = row.get("objection_disposition")
                if disposition is not None:
                    if not isinstance(disposition, dict) or set(disposition) != {"verdict", "note"}:
                        raise DataError(
                            f"{qid}: objection_disposition은 verdict와 note만 가진 dict여야 합니다"
                        )
                    if disposition.get("verdict") not in {"accepted", "rejected"}:
                        raise DataError(f"{qid}: objection_disposition.verdict 허용값이 아닙니다")
                    if not _nonempty_string(disposition.get("note")):
                        raise DataError(f"{qid}: objection_disposition.note를 비울 수 없습니다")
                    dispositions[qid] = {**disposition, "layer": layer}
                overlays.append((layer, row))
    return overlays, dispositions


def _with_image_flags(question: Record) -> None:
    flags = list(question.get("flags") or [])
    flags = [flag for flag in flags if flag not in {"STEM_IMAGE_A_PRESENT", "IMAGE_MISSING"}]
    if question.get("image") or question.get("images"):
        flags.append("STEM_IMAGE_A_PRESENT")
    elif question.get("image_missing"):
        flags.append("IMAGE_MISSING")
    question["flags"] = flags


def _with_royal_tag(question: Record) -> None:
    explanation = question.get("new_expl")
    if not ROYAL_HINT_RE.search(str(question.get("orig_expl") or "")):
        return
    if any(tag in _text(explanation) for tag in schema.ROYAL_TAGS):
        return
    if isinstance(explanation, list) and explanation:
        question["new_expl"] = [f"{schema.ROYAL_TAG} {explanation[0]}", *explanation[1:]]
    elif explanation:
        question["new_expl"] = f"{schema.ROYAL_TAG} {explanation}"


def _validate_final_question(question: Record, sealed: Record) -> None:
    qid = question["qid"]
    options = question.get("options") or []
    if not isinstance(options, list):
        raise DataError(f"{qid}: options는 리스트여야 합니다")
    _validate_answer(qid, question, options)

    flags = question.get("flags")
    if not isinstance(flags, list) or not all(isinstance(flag, str) for flag in flags):
        raise DataError(f"{qid}: flags는 문자열 리스트여야 합니다")
    unknown = sorted(set(flags) - set(schema.FLAG_TAXONOMY))
    if unknown:
        raise DataError(f"{qid}: 알 수 없는 flags: {unknown}")
    answer_flags = set(flags) & (ANSWER_FLAGS | {"TEXT_RECONSTRUCTED"})
    valid = [
        {"ANSWER_MATCH"},
        {"ANSWER_CORRECTED"},
        {"ANSWER_DISPUTED"},
        {"TEXT_RECONSTRUCTED"},
        {"TEXT_RECONSTRUCTED", "ANSWER_DISPUTED"},
    ]
    if answer_flags not in valid:
        raise DataError(f"{qid}: flags의 답 판정 조합이 올바르지 않습니다: {flags}")

    original, status = parse_orig(sealed.get("orig_ans"), len(options))
    final_markers = norm(question.get("verified"), question.get("answers"))
    if "TEXT_RECONSTRUCTED" in flags and status not in {"none_recorded", "empty"}:
        raise DataError(f"{qid}: 원본 답이 비어 있지 않아 TEXT_RECONSTRUCTED를 쓸 수 없습니다")
    if options and status == "ok":
        same = set(final_markers) == set(original or [])
        if "ANSWER_MATCH" in flags and not same:
            raise DataError(f"{qid}: ANSWER_MATCH인데 최종 답이 원본 답과 다릅니다")
        if "ANSWER_CORRECTED" in flags and same:
            raise DataError(f"{qid}: ANSWER_CORRECTED인데 최종 답이 원본 답과 같습니다")
        if "ANSWER_DISPUTED" in flags and not same:
            raise DataError(f"{qid}: ANSWER_DISPUTED는 원본 답을 유지해야 합니다")
    if (set(flags) & {"ANSWER_CORRECTED", "ANSWER_DISPUTED"}) and not _nonempty_string(
        question.get("source")
    ):
        raise DataError(f"{qid}: 정정·논쟁 판정에는 source가 필요합니다")
    if "ANSWER_DISPUTED" in flags and not _nonempty_string(question.get("scope_note")):
        raise DataError(f"{qid}: ANSWER_DISPUTED에는 scope_note가 필요합니다")

    new_expl = question.get("new_expl")
    if not isinstance(new_expl, (str, list)) or (
        isinstance(new_expl, list)
        and (not new_expl or not all(_nonempty_string(item) for item in new_expl))
    ):
        raise DataError(f"{qid}: new_expl은 문자열 또는 비어 있지 않은 문단 리스트여야 합니다")
    if len(schema.strip_royal(_text(new_expl))) < 40:
        raise DataError(f"{qid}: new_expl은 왕족 태그 제외 40자 이상이어야 합니다")
    if not _nonempty_string(question.get("imp")):
        raise DataError(f"{qid}: imp를 비울 수 없습니다")

    wrong = question.get("wrong_option_explanations")
    if not isinstance(wrong, list) or not all(_nonempty_string(item) for item in wrong):
        raise DataError(f"{qid}: wrong_option_explanations는 비어 있지 않은 문자열 리스트여야 합니다")
    if options:
        correct = set(norm(question.get("verified"), question.get("answers")))
        expected_wrong = [CIRC[index] for index in range(len(options)) if CIRC[index] not in correct]
        actual_wrong = [item.strip()[0] if item.strip() else "" for item in wrong]
        if actual_wrong != expected_wrong:
            raise DataError(
                f"{qid}: wrong_option_explanations 마커가 오답 선지와 다릅니다 "
                f"(기대 {expected_wrong}, 실제 {actual_wrong})"
            )
    elif len(wrong) != 1 or "\n" in wrong[0] or markers(wrong[0]):
        raise DataError(f"{qid}: 주관식 오답선지 해설은 마커 없는 한 줄이어야 합니다")
    if "ANSWER_DISPUTED" in flags and "⚠" not in _text(question.get("new_expl")):
        raise DataError(f"{qid}: ANSWER_DISPUTED 해설 본문에는 ⚠ 경고가 필요합니다")

    has_image = bool(question.get("image") or question.get("images"))
    image_flags = set(flags) & {"STEM_IMAGE_A_PRESENT", "IMAGE_MISSING"}
    expected_image_flags = (
        {"STEM_IMAGE_A_PRESENT"} if has_image
        else ({"IMAGE_MISSING"} if question.get("image_missing") else set())
    )
    if image_flags != expected_image_flags:
        raise DataError(f"{qid}: 이미지 데이터와 이미지 플래그가 일치하지 않습니다")
    _reject_markdown(
        qid,
        [
            ("source", question.get("source")),
            ("scope_note", question.get("scope_note")),
            ("new_expl", question.get("new_expl")),
            ("imp", question.get("imp")),
            ("wrong_option_explanations", wrong),
            ("tip", question.get("tip")),
        ],
    )


def _format_batch(batch: str, rows: list[Record]) -> str:
    body = pprint.pformat(rows, width=108, sort_dicts=False)
    return (
        "# -*- coding: utf-8 -*-\n"
        f'"""blindwork build 자동 조립 — {batch}. 수정은 solved/ · _reconcile/ 에서 한다."""\n\n'
        f"QUESTIONS = {body}\n"
    )


def _format_data(scopes: list[tuple[str, list[Record]]]) -> str:
    body = pprint.pformat(scopes, width=108, sort_dicts=False)
    return "# -*- coding: utf-8 -*-\n\nSCOPES = " + body + "\n"


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _install_paths(replacements: Sequence[tuple[Path, Path]]) -> None:
    rollback_roots: list[Path] = []
    backed_up: list[tuple[Path, Path]] = []
    installed: list[Path] = []
    try:
        for source, target in replacements:
            if not source.exists():
                raise DataError(f"스테이징 산출물이 없습니다: {source}")
            target.parent.mkdir(parents=True, exist_ok=True)
            rollback_roots.append(
                Path(tempfile.mkdtemp(prefix=f".{target.name}.rollback-", dir=target.parent))
            )
        for (source, target), rollback_root in zip(replacements, rollback_roots):
            backup = rollback_root / target.name
            if target.exists() or target.is_symlink():
                os.replace(target, backup)
                backed_up.append((target, backup))
            os.replace(source, target)
            installed.append(target)
    except Exception:
        for target in reversed(installed):
            _remove_path(target)
        for target, backup in reversed(backed_up):
            os.replace(backup, target)
        raise
    finally:
        for rollback_root in rollback_roots:
            shutil.rmtree(rollback_root, ignore_errors=True)


def cmd_build(args: argparse.Namespace) -> int:
    if args.batch and args.out_data is not None:
        raise UsageError("--batch는 --out-batches와 함께만 사용할 수 있습니다")
    layers = _parse_layers(args.layers)
    work = Path(args.work)
    ctx = load_context(work)
    batches = _selected_batches(ctx, args.batch)

    recomputed: dict[str, list[Record]] = {}
    for batch in batches:
        rows = resolve_rows(ctx, batch)
        stored = ctx["resolved"].get(batch)
        if stored is None:
            raise DataError(f"{batch}: resolved가 없습니다 — resolve 먼저 실행하세요")
        if stored != rows:
            changed = _changed_qids(rows, stored)
            raise DataError(
                "resolved 가 stale — resolve 재실행 후 C 재검토: " + ", ".join(changed)
            )
        recomputed[batch] = rows

    explained, warnings = _load_explained(work, batches)
    selected_qids = {
        row["qid"] for batch in batches for row in ctx["batch_rows"][batch]
    }
    overlays, dispositions = _load_layer_rows(work, layers, batches, selected_qids)
    overlays_by_qid: dict[str, list[tuple[str, Record]]] = {}
    for layer, row in overlays:
        overlays_by_qid.setdefault(row["qid"], []).append((layer, row))

    built_by_batch: dict[str, list[Record]] = {}
    objections = []
    unclassified = 0
    for batch in batches:
        built_rows = []
        for resolved in recomputed[batch]:
            qid = resolved["qid"]
            solved = ctx["solved"][qid]
            sealed = ctx["sealed"].get(qid, {})
            explanation = explained[qid]
            question: Record = {
                "qid": qid,
                "meta": resolved.get("meta"),
                "years": resolved.get("years"),
                "flags": list(resolved.get("flags") or []),
                "stem": resolved.get("stem"),
                "options": resolved.get("options") or [],
                "verified": resolved.get("verified"),
                "new_expl": explanation.get("new_expl"),
                "imp": explanation.get("imp"),
                "wrong_option_explanations": explanation.get("wrong_option_explanations"),
                "blind": {
                    "verified": solved.get("verified"),
                    "confidence": solved.get("confidence"),
                    "note": solved.get("blind_note"),
                },
            }
            for field in ("image", "images", "answers", "recon", "image_missing", "orig_ans", "orig_expl"):
                if field in resolved and resolved.get(field) is not None:
                    question[field] = resolved[field]
            if solved.get("answers") is not None:
                question["blind"]["answers"] = solved["answers"]
            sources = [
                str(value) for value in (resolved.get("source"), explanation.get("source"))
                if _nonempty_string(value)
            ]
            if sources:
                question["source"] = " / ".join(sources)
            if resolved.get("scope_note"):
                question["scope_note"] = resolved["scope_note"]
            elif qid not in ctx["adjudicated"] and solved.get("dispute_note") and set(question["flags"]) & {
                "ANSWER_DISPUTED", "ANSWER_CORRECTED",
            }:
                question["scope_note"] = solved["dispute_note"]
            if explanation.get("tip") not in (None, "", []):
                question["tip"] = explanation["tip"]

            for _layer, overlay in overlays_by_qid.get(qid, []):
                before = norm(question.get("verified"), question.get("answers"))
                for key, value in overlay.items():
                    if key not in {"qid", "objection_disposition"}:
                        if key == "answers" and value is None:
                            question.pop("answers", None)
                        else:
                            question[key] = value
                after = norm(question.get("verified"), question.get("answers"))
                if before != after:
                    missing = [
                        key for key in ("flags", "wrong_option_explanations") if key not in overlay
                    ]
                    overlay_flags = set(overlay.get("flags") or [])
                    if overlay_flags & {"ANSWER_CORRECTED", "ANSWER_DISPUTED"} and "source" not in overlay:
                        missing.append("source")
                    if "ANSWER_DISPUTED" in overlay_flags and "scope_note" not in overlay:
                        missing.append("scope_note")
                    if missing:
                        raise DataError(
                            f"{qid}: 답을 바꾼 레이어는 같은 항목에 {', '.join(missing)}를 써야 합니다"
                        )

            _with_image_flags(question)
            _with_royal_tag(question)
            _validate_final_question(question, sealed)
            scope = resolved.get("scope") or "미분류"
            if scope == "미분류":
                unclassified += 1
            built_rows.append({"scope": scope, **{key: question[key] for key in FINAL_KEY_ORDER if key in question}})

            if "objection" in explanation:
                objections.append(
                    {
                        "qid": qid,
                        "objection": explanation["objection"],
                        "verified": question["verified"],
                        "blind_verified": question["blind"]["verified"],
                        "disposition": dispositions.get(qid),
                    }
                )
        built_by_batch[batch] = built_rows

    open_objections = sum(item["disposition"] is None for item in objections)
    if args.require_dispositions and open_objections:
        raise DataError(f"미판정 이의 {open_objections}건 — objection_disposition이 필요합니다")

    objections_target = work / "_reconcile" / "objections.json"
    if objections_target.exists() and not objections_target.is_file():
        raise DataError(f"이의 산출물 경로가 파일이 아닙니다: {objections_target}")

    if args.out_batches is not None:
        target = Path(args.out_batches)
        if target.exists() and not target.is_dir():
            raise DataError(f"--out-batches가 디렉터리가 아닙니다: {target}")
        output_description = f"{target} · 파일 {len(built_by_batch)}개"
    else:
        if args.out_data is None:
            raise UsageError("--out-data 또는 --out-batches가 필요합니다")
        target = Path(args.out_data)
        if target.exists() and not target.is_file():
            raise DataError(f"--out-data가 파일이 아닙니다: {target}")
        output_description = str(target)

    if os.path.abspath(target) == os.path.abspath(objections_target):
        raise UsageError("최종 데이터 경로와 objections.json 경로는 달라야 합니다")

    target.parent.mkdir(parents=True, exist_ok=True)
    objections_target.parent.mkdir(parents=True, exist_ok=True)
    with (
        tempfile.TemporaryDirectory(prefix=".blindwork-build-", dir=target.parent) as output_temp,
        tempfile.TemporaryDirectory(prefix=".blindwork-objections-", dir=objections_target.parent) as objections_temp,
    ):
        staged_output = Path(output_temp) / "output"
        if args.out_batches is not None:
            if args.batch and target.is_dir():
                shutil.copytree(target, staged_output)
            else:
                staged_output.mkdir()
            for batch, rows in built_by_batch.items():
                final_rows = [{key: row[key] for key in FINAL_KEY_ORDER if key in row} for row in rows]
                (staged_output / f"{batch}.py").write_text(
                    _format_batch(batch, final_rows), encoding="utf-8"
                )
        else:
            all_rows = [row for batch in batches for row in built_by_batch[batch]]
            scopes = group_scopes(all_rows)
            staged_output.write_text(_format_data(scopes), encoding="utf-8")
        staged_objections = Path(objections_temp) / "objections.json"
        write_json(staged_objections, objections)
        _install_paths(((staged_output, target), (staged_objections, objections_target)))

    for warning in warnings:
        print(f"⚠ {warning}")
    if unclassified:
        print(f"⚠ 미분류 {unclassified}문항")
    total = sum(len(rows) for rows in built_by_batch.values())
    print(f"✓ build 완료 · {total}문항 · {output_description}")
    print(f"이의 {len(objections)}건 (미판정 {open_objections}건)")
    return 0


def _audit_scopes(path: Path) -> list[tuple[str, list[Record]]]:
    try:
        scopes = schema.load_scopes(path)
    except (Exception, SystemExit) as exc:
        raise DataError(f"문항 데이터를 읽을 수 없습니다: {path} — {exc}") from exc
    if not isinstance(scopes, list):
        raise DataError(f"{path}: SCOPES는 리스트여야 합니다")
    checked = []
    for item in scopes:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise DataError(f"{path}: SCOPES 항목은 (범위, 문항 리스트)여야 합니다")
        label, rows = item
        if not isinstance(label, str) or not isinstance(rows, list) or not all(
            isinstance(row, dict) for row in rows
        ):
            raise DataError(f"{path}: SCOPES 범위 또는 문항 형식이 올바르지 않습니다")
        checked.append((label, rows))
    return checked


def _open_objections(work: Path) -> int:
    path = work / "_reconcile" / "objections.json"
    if not path.is_file():
        return 0
    objections = read_json(path)
    if not isinstance(objections, list) or not all(isinstance(item, dict) for item in objections):
        raise DataError(f"{path}: 이의 dict 리스트여야 합니다")
    return sum(item.get("disposition") is None for item in objections)


def _audit_report(scopes: list[tuple[str, list[Record]]], open_objections: int | None) -> Record:
    questions = [question for _label, rows in scopes for question in rows]
    total = len(questions)
    blind_count = sum("blind" in question for question in questions)
    report: Record = {
        "measurable": blind_count > 0,
        "total": total,
        "objective": 0,
        "subjective": 0,
        "blind_missing": 0,
        "orig_ok": 0,
        "orig_none_recorded": 0,
        "orig_unparsed_or_ambiguous": 0,
        "auto_match": {"num": 0, "den": 0},
        "blind_survival": {"num": 0, "den": 0},
        "final_vs_orig": {"num": 0, "den": 0},
        "mismatches": [],
        "open_objections": open_objections,
    }
    for question in questions:
        if not (question.get("options") or []):
            report["subjective"] += 1
            if "blind" not in question:
                report["blind_missing"] += 1
            elif not isinstance(question.get("blind"), dict) or not _nonempty_string(
                question["blind"].get("verified")
            ):
                raise DataError(f"{question.get('qid', '?')}: blind 형식 또는 verified가 올바르지 않습니다")
            continue
        report["objective"] += 1
        original, status = parse_orig(question.get("orig_ans"), len(question.get("options") or []))
        if status == "ok":
            report["orig_ok"] += 1
        elif status in {"none_recorded", "empty"}:
            report["orig_none_recorded"] += 1
        else:
            report["orig_unparsed_or_ambiguous"] += 1

        if "blind" not in question:
            report["blind_missing"] += 1
            if status == "ok":
                report["final_vs_orig"]["den"] += 1
                final = schema.norm_markers(question.get("verified"), question.get("answers"))
                if set(final) == set(original or []):
                    report["final_vs_orig"]["num"] += 1
            continue
        blind = question.get("blind")
        if not isinstance(blind, dict) or not _nonempty_string(blind.get("verified")):
            raise DataError(f"{question.get('qid', '?')}: blind 형식 또는 verified가 올바르지 않습니다")
        blind_markers = schema.blind_markers(question)
        final_markers = schema.norm_markers(question.get("verified"), question.get("answers"))
        report["blind_survival"]["den"] += 1
        if set(blind_markers) == set(final_markers):
            report["blind_survival"]["num"] += 1
        else:
            report["mismatches"].append(
                {
                    "qid": str(question.get("qid") or ""),
                    "meta": str(question.get("meta") or ""),
                    "blind": blind_markers,
                    "final": final_markers,
                    "orig": original if status == "ok" else None,
                }
            )
        if status == "ok":
            report["auto_match"]["den"] += 1
            report["final_vs_orig"]["den"] += 1
            if set(blind_markers) == set(original or []):
                report["auto_match"]["num"] += 1
            if set(final_markers) == set(original or []):
                report["final_vs_orig"]["num"] += 1

    if not report["measurable"]:
        report["auto_match"] = {"num": 0, "den": 0}
        report["blind_survival"] = {"num": 0, "den": 0}
        report["final_vs_orig"] = {"num": 0, "den": 0}
        report["mismatches"] = []
    return report


def cmd_audit(args: argparse.Namespace) -> int:
    work = Path(args.work) if args.work is not None else None
    data = work / "questions_data.py" if work is not None else Path(args.data)
    scopes = _audit_scopes(data)
    report = _audit_report(scopes, _open_objections(work) if work is not None else None)
    if args.as_json:
        print(json.dumps(report, ensure_ascii=False))
        return 0
    if not report["measurable"]:
        print(f"측정 불가 — 블라인드 산출물(blind 필드) 없음: 0/{report['total']}문항")
        if work is not None:
            print(f"미판정 이의 {report['open_objections']}건")
        return 0
    print(f"총 {report['total']}문항 · 객관식 {report['objective']} · 주관식 {report['subjective']}")
    print(
        f"자동일치율 {report['auto_match']['num']}/{report['auto_match']['den']} · "
        f"블라인드 생존율 {report['blind_survival']['num']}/{report['blind_survival']['den']} · "
        f"최종↔원본 일치율 {report['final_vs_orig']['num']}/{report['final_vs_orig']['den']}"
    )
    print(
        f"버킷: 주관식 {report['subjective']} · 원본 미기록 {report['orig_none_recorded']} · "
        f"원본 파싱불가/애매 {report['orig_unparsed_or_ambiguous']} · blind 없음 {report['blind_missing']}"
    )
    for item in report["mismatches"][:max(0, args.show)]:
        original = ",".join(item["orig"]) if item["orig"] is not None else "없음"
        print(
            f"{item['qid']} · {item['meta']} · {','.join(item['blind'])} → "
            f"{','.join(item['final'])} · {original}"
        )
    if work is not None:
        print(f"미판정 이의 {report['open_objections']}건")
    return 0


def _positive_int(value: str) -> int:
    """argparse 크기 옵션을 1 이상의 정수로 제한한다."""
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("1 이상의 정수여야 합니다")
    return number


def _check_stage(value: str) -> str:
    if value == "adversarial":
        raise argparse.ArgumentTypeError(
            "적대 재검증 레이어는 check 대상이 아닙니다. build --layers로 레이어를 검사하세요"
        )
    return value


def build_parser() -> argparse.ArgumentParser:
    """일곱 하위 명령의 전체 CLI 표면을 정의한다."""
    parser = KoreanArgumentParser(description="블라인드 3단 분리 작업 폴더 도구")
    sub = parser.add_subparsers(dest="cmd", required=True)

    split = sub.add_parser(
        "split",
        help="입력을 구조층·봉인층·감사층으로 분리",
        description="전사 입력을 블라인드 구조층과 봉인 답안층으로 나눕니다. 다음에는 slice를 실행합니다.",
    )
    split_source = split.add_mutually_exclusive_group(required=True)
    split_source.add_argument("--batches", type=Path, help="QUESTIONS가 든 u*.py 폴더")
    split_source.add_argument("--extract", type=Path, help="all_questions/answer_key JSON 폴더")
    split.add_argument("--work", type=Path, required=True, help="작업 폴더 W")
    split.add_argument(
        "--allow-leak", action="append", default=[], metavar="QID=사유",
        help="누출 의심 문항을 사유와 함께 예외 허용(여러 번 지정 가능)",
    )
    split.add_argument("--image-map", type=Path, help="qid별 확정 이미지 JSON")
    split.add_argument("--force", action="store_true", help="하류 산출물이 없을 때 기존 분리본 교체")

    slice_parser = sub.add_parser(
        "slice",
        help="구조층을 풀이 묶음으로 균등 분할",
        description="블라인드 문항을 풀이 묶음으로 나눕니다. 다음에는 A 풀이와 check를 실행합니다.",
    )
    slice_parser.add_argument("--work", type=Path, required=True, help="작업 폴더 W")
    slice_parser.add_argument("--text-size", type=_positive_int, default=20, help="도판 없는 묶음의 목표 문항 수")
    slice_parser.add_argument("--image-size", type=_positive_int, default=10, help="도판 있는 묶음의 목표 문항 수")
    slice_parser.add_argument("--force", action="store_true", help="풀이가 없을 때 기존 슬라이스 교체")

    check = sub.add_parser(
        "check",
        help="단계 산출물 검사",
        description="A 풀이, B 판정, C 해설 파일을 검사합니다. solve 통과 후 scan, adjudicate 통과 후 resolve, explain 통과 후 build를 실행합니다.",
    )
    check.add_argument("--work", type=Path, required=True, help="작업 폴더 W")
    check.add_argument(
        "--stage", required=True, type=_check_stage, choices=("solve", "adjudicate", "explain"),
        help="검사할 단계(solve=A 풀이, adjudicate=B 판정, explain=C 해설)",
    )
    check.add_argument("--patch", action="store_true", help="solve 파일을 전체 풀이가 아닌 부분 패치로 검사")
    check.add_argument("file", type=Path, help="검사할 단계 산출물 .py 파일")

    scan = sub.add_parser(
        "scan",
        help="원본 답 대조 작업목록 생성",
        description="A 풀이와 봉인 원본 답을 대조해 B 판정 목록을 만듭니다. 다음에는 B 판정을 작성합니다.",
    )
    scan.add_argument("--work", type=Path, required=True, help="작업 폴더 W")
    scan.add_argument("--batch", help="이름이 일치하는 배치 하나만 처리")
    scan.add_argument("--all", action="store_true", help="기존 B 판정을 무시하고 모든 문항을 다시 분류")
    scan.add_argument("--json", dest="as_json", action="store_true", help="통계를 사람용 문장 없이 JSON으로만 출력")

    resolve = sub.add_parser(
        "resolve",
        help="자동·수동 판정을 해설 입력으로 확정",
        description="자동 일치와 B 판정을 합쳐 C 해설 입력을 확정합니다. 다음에는 C 해설을 작성합니다.",
    )
    resolve.add_argument("--work", type=Path, required=True, help="작업 폴더 W")
    resolve.add_argument("--batch", help="이름이 일치하는 배치 하나만 처리")

    build = sub.add_parser(
        "build",
        help="단계 산출물을 최종 문항 데이터로 조립",
        description="검사된 구조·답·해설·레이어를 최종 데이터로 조립합니다. 다음에는 validate와 audit를 실행합니다.",
    )
    build.add_argument("--work", type=Path, required=True, help="작업 폴더 W")
    build_output = build.add_mutually_exclusive_group(required=True)
    build_output.add_argument("--out-batches", type=Path, help="최종 QUESTIONS 배치 파일을 쓸 폴더")
    build_output.add_argument("--out-data", type=Path, help="최종 SCOPES를 쓸 questions_data.py 경로")
    build.add_argument("--batch", help="--out-batches에서 갱신할 배치 하나만 선택")
    build.add_argument("--layers", default="adversarial", help="적용할 오버라이드 레이어 이름을 쉼표로 나열")
    build.add_argument(
        "--require-dispositions", action="store_true",
        help="미판정 이의가 하나라도 있으면 최종 조립을 거부",
    )

    audit = sub.add_parser(
        "audit",
        help="블라인드 답의 원본·최종 대비 지표 출력",
        description="블라인드 답을 원본·최종 답과 비교해 재검증 지표를 출력합니다. 최종 검토에 사용합니다.",
    )
    audit_source = audit.add_mutually_exclusive_group(required=True)
    audit_source.add_argument("--data", type=Path, help="검사할 questions_data.py 경로")
    audit_source.add_argument("--work", type=Path, help="questions_data.py와 이의 파일이 든 작업 폴더 W")
    audit.add_argument("--show", type=int, default=10, help="사람용 출력에 표시할 답 변경 문항의 최대 수")
    audit.add_argument("--json", dest="as_json", action="store_true", help="지표를 사람용 문장 없이 JSON으로만 출력")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 인자를 해석하고 데이터 오류를 종료코드 1로 정규화한다."""
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "split": cmd_split,
        "slice": cmd_slice,
        "check": cmd_check,
        "scan": cmd_scan,
        "resolve": cmd_resolve,
        "build": cmd_build,
        "audit": cmd_audit,
    }
    try:
        return handlers[args.cmd](args)
    except UsageError as exc:
        parser.error(str(exc))
    except (DataError, OSError) as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

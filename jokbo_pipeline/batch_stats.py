#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import importlib
import json
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final, Protocol, Required, TypedDict, runtime_checkable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class Question(TypedDict, total=False):
    meta: Required[str]
    years: list[str | int]
    new_expl: str | list[str]
    flags: list[str]
    imp: str
    tip: str
    wrong_option_explanations: list[str]
    image: str
    images: list[str]
    answers: list[str | int]
    recon: str
    scope_note: str
    source: str


Scope = tuple[str, list[Question]]
Scopes = list[Scope]


class FieldUsage(TypedDict):
    count: int
    percent: float


class ScopeRow(TypedDict):
    scope: str
    question_count: int
    prof2026: str
    status: str


class Stats(TypedDict):
    total_questions: int
    total_scopes: int
    year_counts: dict[str, int]
    field_usage: dict[str, FieldUsage]
    royal_count: int
    scopes: list[ScopeRow]
    flag_counts: dict[str, int]


class ScopeStatus(TypedDict):
    status: str
    weight: float
    prof2026: str
    tokens: list[str]


@runtime_checkable
class SchemaApi(Protocol):
    @property
    def FLAG_TAXONOMY(self) -> list[str]: ...

    def load_scopes(self, data_path: Path) -> Scopes: ...

    def split_prof(self, meta: str) -> tuple[str, str, str]: ...

    def scope_status(self, header: str, prof_names: set[str]) -> ScopeStatus: ...

    def clean_scope(self, header: str) -> str: ...

    def is_royal(self, question: Question) -> bool: ...


class CliNamespace(argparse.Namespace):
    data: Path | None = None
    work: Path | None = None
    as_json: bool = False


schema_module = importlib.import_module("jokbo_pipeline.schema")
assert isinstance(schema_module, SchemaApi)
schema: Final[SchemaApi] = schema_module

FIELD_CHECKS: Final[dict[str, Callable[[Question], bool]]] = {
    "imp": lambda question: bool(question.get("imp")),
    "tip": lambda question: bool(question.get("tip")),
    "wrong_option_explanations": lambda question: bool(
        question.get("wrong_option_explanations")
    ),
    "image|images": lambda question: bool(
        question.get("image") or question.get("images")
    ),
    "answers": lambda question: bool(question.get("answers")),
    "recon": lambda question: bool(question.get("recon")),
    "scope_note": lambda question: bool(question.get("scope_note")),
    "source": lambda question: bool(question.get("source")),
}


def collect_stats(scopes: Scopes) -> Stats:
    questions = [question for _header, scope_questions in scopes for question in scope_questions]
    total = len(questions)
    year_counts = Counter(
        str(year)
        for question in questions
        for year in question.get("years", [])
    )
    field_usage: dict[str, FieldUsage] = {}
    for label, is_filled in FIELD_CHECKS.items():
        count = sum(is_filled(question) for question in questions)
        field_usage[label] = {
            "count": count,
            "percent": round(count * 100 / total, 1) if total else 0.0,
        }

    scope_rows: list[ScopeRow] = []
    for header, scope_questions in scopes:
        prof_names = {
            str(schema.split_prof(question["meta"])[2])
            for question in scope_questions
        }
        status = schema.scope_status(header, prof_names)
        scope_rows.append(
            {
                "scope": schema.clean_scope(header),
                "question_count": len(scope_questions),
                "prof2026": str(status["prof2026"]),
                "status": str(status["status"]),
            }
        )

    return {
        "total_questions": total,
        "total_scopes": len(scopes),
        "year_counts": dict(sorted(year_counts.items(), reverse=True)),
        "field_usage": field_usage,
        "royal_count": sum(schema.is_royal(question) for question in questions),
        "scopes": scope_rows,
        "flag_counts": {
            flag: sum(flag in (question.get("flags") or []) for question in questions)
            for flag in schema.FLAG_TAXONOMY
        },
    }


def render_markdown(stats: Stats) -> str:
    lines = [
        "# 배치 통계",
        "",
        f"- 총 문항: **{stats['total_questions']}개**",
        f"- 총 범위: **{stats['total_scopes']}개**",
        "",
        "## 연도별 출현 수",
        "",
        "| 연도 | 문항 수 |",
        "|---|---:|",
    ]
    lines.extend(
        f"| {year} | {count} |"
        for year, count in stats["year_counts"].items()
    )
    lines.extend(
        [
            "",
            "## 필드 사용률",
            "",
            "| 필드 | 문항 수 | 사용률 |",
            "|---|---:|---:|",
        ]
    )
    lines.extend(
        f"| `{field}` | {usage['count']} | {usage['percent']:.1f}% |"
        for field, usage in stats["field_usage"].items()
    )
    lines.extend(
        [
            "",
            "## 왕족 수",
            "",
            f"**{stats['royal_count']}문항**",
            "",
            "## 범위별 2026 상태",
            "",
            "| 범위 | 문항 수 | 2026 담당 | 상태 |",
            "|---|---:|---|---|",
        ]
    )
    lines.extend(
        "| {scope} | {question_count} | {prof2026} | {status} |".format(
            scope=str(row["scope"]).replace("|", "\\|"),
            question_count=row["question_count"],
            prof2026=str(row["prof2026"]).replace("|", "\\|"),
            status=row["status"],
        )
        for row in stats["scopes"]
    )
    lines.extend(
        [
            "",
            "## 플래그 집계",
            "",
            "| 플래그 | 문항 수 |",
            "|---|---:|",
        ]
    )
    lines.extend(
        f"| `{flag}` | {count} |"
        for flag, count in stats["flag_counts"].items()
    )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="questions_data.py의 배치 통계를 Markdown 또는 JSON으로 출력합니다."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    _ = source.add_argument("--data", type=Path, help="questions_data.py 경로")
    _ = source.add_argument("--work", type=Path, help="과목 _work 디렉터리")
    _ = parser.add_argument(
        "--json", dest="as_json", action="store_true", help="JSON으로 출력"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv, namespace=CliNamespace())
    if args.data is not None:
        data_path = args.data
    else:
        assert args.work is not None
        data_path = args.work / "questions_data.py"
    if not data_path.is_file():
        print(f"✗ {data_path} 파일이 없습니다. 먼저 assemble.py 를 실행하세요.", file=sys.stderr)
        return 1

    stats = collect_stats(schema.load_scopes(data_path))
    if args.as_json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(stats), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

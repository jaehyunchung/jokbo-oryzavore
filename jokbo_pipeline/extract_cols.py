"""2단 조판 PDF의 좌우 단을 분리한다.

pdfplumber는 선택 의존성이며 auto 모드에서 사용할 수 없거나 추출에 실패하면
시스템의 Poppler ``pdftotext`` 명령으로 폴백한다.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from pypdf import PdfReader

PAGE_WIDTH: Final = 595.0
PAGE_HEIGHT: Final = 842.0
Box = tuple[float, float, float, float]


class Engine(StrEnum):
    AUTO = "auto"
    PDFPLUMBER = "pdfplumber"
    PDFTOTEXT = "pdftotext"


@dataclass(frozen=True, slots=True)
class ExtractConfig:
    pdf: Path
    out_dir: Path
    split: float
    first: int
    last: int | None


class PageRangeError(Exception):
    pass


class PopplerMissingError(Exception):
    pass


class PdfplumberExtractionError(Exception):
    pass


class CliArgs(argparse.Namespace):
    pdf: Path = Path()
    out_dir: Path = Path()
    split: float = 300.0
    first: int = 1
    last: int | None = None
    engine: Engine = Engine.AUTO


def split_boxes(width: float, height: float, split: float) -> tuple[Box, Box]:
    """페이지 크기와 분할점을 좌우 crop 박스로 변환한다."""
    return ((0, 0, split, height), (split, 0, width, height))


def page_text_layout(left: str, right: str, n: int) -> str:
    """좌우 텍스트를 페이지별 정본 출력 형식으로 조립한다."""
    return (
        f"===== p{n:03d} · 왼쪽단 =====\n{left}\n"
        f"===== p{n:03d} · 오른쪽단 =====\n{right}\n"
    )


def pdftotext_commands(
    pdf: Path,
    n: int,
    split: float,
) -> tuple[list[str], list[str]]:
    """한 페이지의 좌우 단을 추출할 pdftotext 명령 두 개를 조립한다."""
    common = ["pdftotext", "-layout", "-f", str(n), "-l", str(n)]
    suffix = ["-H", _number(PAGE_HEIGHT), str(pdf), "-"]
    left = [
        *common,
        "-x",
        "0",
        "-y",
        "0",
        "-W",
        _number(split),
        *suffix,
    ]
    right = [
        *common,
        "-x",
        _number(split),
        "-y",
        "0",
        "-W",
        _number(PAGE_WIDTH - split),
        *suffix,
    ]
    return left, right


def _number(value: float) -> str:
    return f"{value:g}"


def _page_numbers(total: int, first: int, last: int | None) -> range:
    final = total if last is None else last
    if first < 1 or final < first or final > total:
        raise PageRangeError(
            f"페이지 범위가 올바르지 않습니다: first={first}, last={final}, 전체={total}",
        )
    return range(first, final + 1)


def _write_page(config: ExtractConfig, n: int, left: str, right: str) -> None:
    output = config.out_dir / f"p{n:03d}.txt"
    _ = output.write_text(page_text_layout(left, right, n), encoding="utf-8")


def _extract_pdfplumber(config: ExtractConfig) -> int:
    import pdfplumber
    from pdfminer.pdfexceptions import PDFException

    config.out_dir.mkdir(parents=True, exist_ok=True)
    try:
        with pdfplumber.open(config.pdf) as pdf:
            page_numbers = _page_numbers(len(pdf.pages), config.first, config.last)
            for n in page_numbers:
                page = pdf.pages[n - 1]
                left_box, right_box = split_boxes(page.width, page.height, config.split)
                left = page.crop(left_box).extract_text(layout=False) or ""
                right = page.crop(right_box).extract_text(layout=False) or ""
                _write_page(config, n, left, right)
    except (OSError, PDFException, ValueError) as error:
        raise PdfplumberExtractionError(str(error)) from error
    return len(page_numbers)


def _run_pdftotext(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.rstrip("\n\f")


def _extract_pdftotext(config: ExtractConfig) -> int:
    if shutil.which("pdftotext") is None:
        raise PopplerMissingError

    total = len(PdfReader(config.pdf).pages)
    page_numbers = _page_numbers(total, config.first, config.last)
    config.out_dir.mkdir(parents=True, exist_ok=True)
    for n in page_numbers:
        left_command, right_command = pdftotext_commands(config.pdf, n, config.split)
        left = _run_pdftotext(left_command)
        right = _run_pdftotext(right_command)
        _write_page(config, n, left, right)
    return len(page_numbers)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--pdf", type=Path, required=True, help="입력 PDF 경로")
    _ = parser.add_argument("--out-dir", type=Path, required=True, help="페이지 텍스트 출력 폴더")
    _ = parser.add_argument("--split", type=float, default=300.0, help="왼쪽 단 너비(pt)")
    _ = parser.add_argument("--first", type=int, default=1, help="첫 페이지(1부터 시작)")
    _ = parser.add_argument("--last", type=int, help="마지막 페이지(포함)")
    _ = parser.add_argument(
        "--engine",
        type=Engine,
        choices=list(Engine),
        default=Engine.AUTO,
        help="추출 엔진(기본: auto)",
    )
    return parser


def _config(args: CliArgs) -> ExtractConfig:
    return ExtractConfig(
        pdf=args.pdf,
        out_dir=args.out_dir,
        split=args.split,
        first=args.first,
        last=args.last,
    )


def _extract_auto(config: ExtractConfig) -> int:
    try:
        return _extract_pdfplumber(config)
    except (ImportError, PdfplumberExtractionError) as error:
        print(
            f"경고: pdfplumber 추출 실패({error}). pdftotext로 다시 시도합니다.",
            file=sys.stderr,
        )
        return _extract_pdftotext(config)


def _run_engine(config: ExtractConfig, engine: Engine) -> int:
    extractors = {
        Engine.AUTO: _extract_auto,
        Engine.PDFPLUMBER: _extract_pdfplumber,
        Engine.PDFTOTEXT: _extract_pdftotext,
    }
    return extractors[engine](config)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv, namespace=CliArgs())
    config = _config(args)
    if not config.pdf.is_file():
        print(f"오류: PDF 파일이 존재하지 않습니다: {config.pdf}", file=sys.stderr)
        return 1
    try:
        count = _run_engine(config, args.engine)
    except PopplerMissingError:
        print(
            "오류: pdftotext를 찾을 수 없습니다. Poppler를 설치한 뒤 다시 시도하세요.",
            file=sys.stderr,
        )
        return 2
    except (
        ImportError,
        OSError,
        PageRangeError,
        PdfplumberExtractionError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"오류: PDF 텍스트 추출에 실패했습니다: {error}", file=sys.stderr)
        return 1
    print("done", count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

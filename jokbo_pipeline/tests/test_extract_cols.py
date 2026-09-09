import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent
ROOT = PIPE.parent
sys.path.insert(0, str(ROOT))

from jokbo_pipeline.extract_cols import (  # noqa: E402
    page_text_layout,
    pdftotext_commands,
    split_boxes,
)


class SplitBoxesTests(unittest.TestCase):
    def test_returns_a4_left_and_right_boxes_when_split_is_300(self) -> None:
        # Given / When
        boxes = split_boxes(595, 842, 300)

        # Then
        self.assertEqual(boxes, ((0, 0, 300, 842), (300, 0, 595, 842)))


class PageTextLayoutTests(unittest.TestCase):
    def test_preserves_canonical_headers_and_trailing_newline(self) -> None:
        # Given / When
        text = page_text_layout("왼쪽 본문", "오른쪽 본문", 7)

        # Then
        self.assertEqual(
            text,
            "===== p007 · 왼쪽단 =====\n왼쪽 본문\n"
            + "===== p007 · 오른쪽단 =====\n오른쪽 본문\n",
        )


class PdftotextCommandTests(unittest.TestCase):
    def test_builds_a4_column_commands_when_split_is_300(self) -> None:
        # Given / When
        left, right = pdftotext_commands(Path("족보.pdf"), 4, 300)

        # Then
        self.assertIn(["-x", "0", "-y", "0", "-W", "300"], _windows(left, 6))
        self.assertIn(["-x", "300", "-y", "0", "-W", "295"], _windows(right, 6))
        self.assertEqual(left[-2:], ["족보.pdf", "-"])
        self.assertEqual(right[-2:], ["족보.pdf", "-"])


def _windows(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(len(values) - size + 1)]


if __name__ == "__main__":
    _ = unittest.main()

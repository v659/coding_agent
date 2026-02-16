from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

import local_agent.tools as tools
from local_agent.tools import search_text


def _make_binary_file(path: Path, size: int = 1024) -> None:
    with open(path, "wb") as f:
        f.write(os.urandom(size))


def _make_large_text_file(path: Path, size: int = 2 * 1024 * 1024) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for _ in range(size // 100):
            f.write("0123456789abcdef" * 6 + "\n")


def _make_small_text_file(path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("hello world\nthis is a test\npattern123\n")


class SearchTextBehaviorTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self._temp_dir)
        _make_small_text_file(self.temp_path / "a.txt")
        _make_binary_file(self.temp_path / "b.bin")
        _make_large_text_file(self.temp_path / "c.txt")

    def tearDown(self) -> None:
        shutil.rmtree(self._temp_dir)

    def test_fallback_excludes_binary_and_large(self) -> None:
        orig_has_rg = tools._has_rg
        tools._has_rg = lambda: False
        try:
            result = search_text(self.temp_path, "pattern123")
        finally:
            tools._has_rg = orig_has_rg
        self.assertEqual(result["count"], 1, msg=f"fallback matches={result['matches']}")
        self.assertIn("a.txt", result["matches"][0])

    def test_rg_path_excludes_binary_and_large(self) -> None:
        if not tools._has_rg():
            self.skipTest("rg not available in environment")
        result = search_text(self.temp_path, "pattern123")
        self.assertEqual(result["count"], 1, msg=f"rg matches={result['matches']}")
        self.assertIn("a.txt", result["matches"][0])


if __name__ == "__main__":
    unittest.main()

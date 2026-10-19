"""CLI regressions for corpus filtering and denominator validation."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HUMAN = "这是我们记录的第一段正文。\n\n看起来记录已经足够清楚。"
AI = ("这是模型生成的第一段正文。\n\n值得注意的是，结果仍然需要核对。"
      "\n\n我们还应该检查其他可能出现的问题。")
INVALID_DOCUMENTS = ("", "# 这是一份只有标题的文档", "This is an English paragraph.",
                     "# 中文标题\n\nThis is an English paragraph.")


class CorpusCLITestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lieflat-corpus-test-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def corpus(self, name, documents=None):
        directory = self.directory / name
        directory.mkdir(exist_ok=True)
        for filename, text in (documents or {}).items():
            (directory / filename).write_text(text, encoding="utf-8")
        return directory

    def run_script(self, script, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script), *map(str, args)],
            capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}, check=False,
        )

    def assert_failure(self, result):
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("无法统计", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


class StructureCLITests(CorpusCLITestCase):
    def setUp(self):
        super().setUp()
        self.human = self.corpus("human", {"sample.md": HUMAN})
        self.ai = self.corpus("ai", {"sample.md": AI})

    def run_structure(self, human=None, ai=None):
        return self.run_script("check-structure.py", "--human",
                               human or self.human, "--ai", ai or self.ai)

    def test_normal_chinese_corpora_preserve_paragraph_denominators(self):
        result = self.run_structure()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("AI 3 段，人类 2 段", result.stdout)
        row = next(line for line in result.stdout.splitlines()
                   if line.startswith("段首零主语评论/非首段%"))
        self.assertEqual(row.split()[1:4], ["50.00", "100.00", "0.50×"])

    def test_empty_or_missing_directory_on_either_side_fails_cleanly(self):
        empty = self.corpus("empty")
        missing = self.directory / "missing"
        for directory in (empty, missing):
            for side in ("human", "ai"):
                with self.subTest(directory=directory.name, side=side):
                    self.assert_failure(self.run_structure(**{side: directory}))

    def test_documents_without_usable_chinese_paragraphs_fail_cleanly(self):
        for i, text in enumerate(INVALID_DOCUMENTS):
            directory = self.corpus(f"invalid-{i}", {"sample.md": text})
            for side in ("human", "ai"):
                with self.subTest(text=text, side=side):
                    self.assert_failure(self.run_structure(**{side: directory}))

    def test_invalid_groups_are_skipped_without_changing_statistics(self):
        baseline = self.run_structure()
        invalid = self.corpus("invalid", {"sample.md": "# 只有标题"})
        missing = self.directory / "missing"
        result = self.run_script("check-structure.py", "--human", invalid,
                                 self.human, missing, "--ai", invalid, self.ai)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, baseline.stdout)
        self.assertIn("跳过人类", result.stderr)
        self.assertIn("跳过AI", result.stderr)

    def test_invalid_documents_within_valid_groups_do_not_dilute_rates(self):
        baseline = self.run_structure()
        for directory in (self.human, self.ai):
            for i, text in enumerate(INVALID_DOCUMENTS):
                (directory / f"invalid-{i}.md").write_text(text, encoding="utf-8")
        result = self.run_structure()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, baseline.stdout)
        self.assertIn("4 篇", result.stderr)

    def test_missing_required_arguments_is_a_cli_error(self):
        for args in ((), ("--human", self.human), ("--ai", self.ai)):
            with self.subTest(args=args):
                result = self.run_script("check-structure.py", *args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("用法", result.stderr)


class TranslationeseCLITests(CorpusCLITestCase):
    def setUp(self):
        super().setUp()
        # Both documents have six Chinese characters, so the expected frequency
        # is 1 / 12 * 1000 overall and 1 / 6 * 1000 for model alpha.
        self.valid = self.corpus("valid", {"alpha-T1.md": "这意味着变化。",
                                           "beta-T1.md": "我们需要核对。"})

    def run_translationese(self, *directories):
        return self.run_script("check-translationese.py", *directories)

    def test_normal_models_preserve_counts_coverage_and_frequencies(self):
        result = self.run_translationese(self.valid)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("语料 2 篇", result.stdout)
        self.assertIn("模型 2 个：alpha, beta", result.stdout)
        row = next(line for line in result.stdout.splitlines()
                   if line.startswith("这意味着"))
        self.assertEqual(row.split()[1:], ["83.33", "1", "1/2", "166.67", "0.00"])

    def test_empty_and_missing_directories_fail_cleanly(self):
        for directory in (self.corpus("empty"), self.directory / "missing"):
            with self.subTest(directory=directory.name):
                self.assert_failure(self.run_translationese(directory))

    def test_corpora_without_chinese_characters_fail_cleanly(self):
        for i, text in enumerate(("", "This is an English paragraph.", "——")):
            directory = self.corpus(f"invalid-{i}", {"model-T1.md": text})
            with self.subTest(text=text):
                self.assert_failure(self.run_translationese(directory))

    def test_models_without_chinese_characters_are_skipped(self):
        baseline = self.run_translationese(self.valid)
        invalid = self.corpus("invalid", {"empty-T1.md": "",
                                           "latin-T1.md": "English text. ——"})
        result = self.run_translationese(self.valid, invalid)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, baseline.stdout)
        self.assertIn("跳过", result.stderr)
        self.assertIn("2 篇", result.stderr)

    def test_invalid_documents_of_a_valid_model_do_not_dilute_coverage(self):
        baseline = self.run_translationese(self.valid)
        (self.valid / "alpha-T2.md").write_text("", encoding="utf-8")
        (self.valid / "beta-T2.md").write_text("English text. ——", encoding="utf-8")
        result = self.run_translationese(self.valid)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, baseline.stdout)
        self.assertIn("2 篇", result.stderr)

    def test_empty_and_missing_directories_are_skipped_when_data_is_valid(self):
        baseline = self.run_translationese(self.valid)
        result = self.run_translationese(self.corpus("empty"), self.valid,
                                         self.directory / "missing")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, baseline.stdout)
        self.assertIn("跳过", result.stderr)

    def test_unreadable_document_is_reported_and_skipped(self):
        baseline = self.run_translationese(self.valid)
        (self.valid / "broken-T1.md").write_bytes(b"\xff\xfe\xff")
        result = self.run_translationese(self.valid)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, baseline.stdout)
        self.assertIn("无法读取", result.stderr)

    def test_missing_arguments_is_a_cli_error(self):
        result = self.run_translationese()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("用法", result.stderr)


if __name__ == "__main__":
    unittest.main()

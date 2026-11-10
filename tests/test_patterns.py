"""0.2.1: a matches check's pattern in Python (the runner) and in the browser (the wizard).

Found on 2026-11-09, when AI 5500 ran the experiment intake on a made-up
system of its own (a restaurant's menu writer): the intake wrote its checks
as `(?m)^Contains: ...` and `\\A\\s*## ...(?:\\s*\\S+){1,30}...`. Python read
them; the wizard's JavaScript refused `(?m)` and stopped steps 3 to 5, read
`\\A` as the letter A, and the repeated group inside a repeat took minutes on
a long card. Now the wizard reads leading flags, `\\A` and `\\Z` as Python
does and turns a pattern it can't build into n/a; `check` and `suite --check`
name what the browser can't read and time each pattern on long outputs.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import EXAMPLES, REPO, run_ab, tmpdir  # noqa: E402
from cdp import Browser, find_chrome  # noqa: E402

sys.path.insert(0, str(REPO))
import run_ab as R  # noqa: E402

CHROME = find_chrome()
WIZARD = REPO / "wizard.html"
NESTED = r"\A\s*## [^\n]+\n(?:\s*\S+){1,30}\s*\nContains: "
SAFE = r"^\s*## [^\n]+\n\s*\S+(?:\s+\S+){0,29}\s*\nContains: "
CARD = "## Lamb flatbread\nSlow-roasted lamb on grilled flatbread with garlic yogurt and dukkah.\nContains: milk, tree nuts, wheat, sesame\n"


class BrowserCantRead(unittest.TestCase):
    def test_what_the_wizard_now_reads_is_not_a_problem(self):
        for p in (r"(?m)^Contains: milk", r"(?mi)^contains", r"\A## ", r"sesame\s*\Z", SAFE, r"\++", r"a+?b"):
            with self.subTest(pattern=p):
                self.assertEqual(R.pattern_problems("c", p), [])

    def test_what_the_browser_cant_read(self):
        for p, word in ((r"(?P<dish>\w+)", "named group"), (r"(?>ab)c", "atomic"), (r"a++", "possessive"),
                        (r"(?x) a b", "no form of"), (r"(?#note)a", "comment")):
            with self.subTest(pattern=p):
                problems = R.pattern_problems("c", p)
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(word, problems[0])
                self.assertIn("wizard", problems[0])

    def test_a_pattern_python_cant_read(self):
        self.assertIn("isn't a regular expression", R.pattern_problems("c", "(unclosed")[0])


class SlowPatterns(unittest.TestCase):
    def test_a_repeat_inside_a_repeat_is_caught(self):
        t = time.monotonic()
        problems = R.slow_pattern_problems("description-length", NESTED, "", R.pattern_samples([CARD]))
        self.assertLess(time.monotonic() - t, R.PATTERN_SECONDS + 3)
        self.assertEqual(len(problems), 1)
        self.assertIn("would hang", problems[0])
        self.assertIn(r"\S+(?:\s+\S+){0,29}", problems[0], "it names the safe way to count words")

    def test_the_safe_pattern_passes_quickly(self):
        t = time.monotonic()
        self.assertEqual(R.slow_pattern_problems("description-length", SAFE, "", R.pattern_samples([CARD])), [])
        self.assertLess(time.monotonic() - t, 2)

    def test_check_says_must_fix(self):
        root = tmpdir()
        try:
            src = (EXAMPLES / "demo-program-check.toml").read_text(encoding="utf-8")
            text = src.replace('files_from = "class-assistant"', f'files_from = {json.dumps(str(EXAMPLES / "class-assistant"))}')
            text = text.replace('pattern = "120,?000|120 ?[kK]"', "pattern = '" + NESTED + "'", 1)
            self.assertNotEqual(text, src)
            f = root / "experiment.toml"
            f.write_text(text, encoding="utf-8")
            r = run_ab("check", f)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("must fix:", r.stdout)
            self.assertIn("would hang the runner and the wizard", r.stdout)
        finally:
            shutil.rmtree(root, ignore_errors=True)


class NextStep(unittest.TestCase):
    def test_check_names_the_experiments_own_system(self):
        root = tmpdir()
        try:
            src = (EXAMPLES / "demo-one-line.toml").read_text(encoding="utf-8")
            text = src.replace('files_from = "class-assistant"', f'files_from = {json.dumps(str(EXAMPLES / "class-assistant"))}')
            old = 'folder = "the class assistant: python3 run_ab.py setup ../class-assistant"'
            self.assertIn(old, text)
            text = text.replace(old, 'folder = "../menu-writer"')
            f = root / "experiment.toml"
            f.write_text(text, encoding="utf-8")
            r = run_ab("check", f)
            self.assertIn("Next, run it.", r.stdout, r.stdout + r.stderr)
            self.assertIn("--assistant ../menu-writer", r.stdout)
            self.assertNotIn("--assistant ../class-assistant", r.stdout)
        finally:
            shutil.rmtree(root, ignore_errors=True)


@unittest.skipUnless(CHROME, "headless Chrome is not available")
class InTheWizard(unittest.TestCase):
    def setUp(self):
        self.b = Browser(CHROME)
        self.b.goto(WIZARD.as_uri())

    def tearDown(self):
        errors = list(self.b.errors)
        self.b.close()
        self.assertEqual(errors, [], "console errors in the wizard")

    def matches(self, pattern, flags=""):
        c = json.dumps({"kind": "matches", "object": "product", "id": "t", "pattern": pattern, "flags": flags})
        o = json.dumps({"status": "ok", "output": CARD, "trace": None})
        return self.b.js(f"(() => {{ const r = runCheck({c}, {{id: 'p', tags: []}}, {o}); return r.result + '|' + r.reason; }})()")

    def test_the_intakes_patterns_read_as_python_reads_them(self):
        for pattern, flags in ((r"(?m)^Contains: milk, tree nuts, wheat, sesame\.?\s*$", ""), (SAFE, ""),
                               (SAFE.replace("^", r"\A", 1), ""), (r"^Contains: milk", "m"), (r"sesame\s*\Z", "")):
            with self.subTest(pattern=pattern):
                self.assertTrue(self.matches(pattern, flags).startswith("pass|"))
                v, _ = R.run_check({"kind": "matches", "pattern": pattern, "flags": flags}, CARD, None)
                self.assertEqual(v, "pass", "Python agrees")
        self.assertTrue(self.matches(r"\AContains").startswith("fail|"), "\\A is the start of the output, not a letter A")

    def test_a_pattern_the_browser_cant_build_is_na_not_a_broken_step(self):
        r = self.matches(r"(?P<dish>\w+)")
        self.assertTrue(r.startswith("n/a|"), r)
        self.assertIn("can’t run the check", r)


if __name__ == "__main__":
    unittest.main()

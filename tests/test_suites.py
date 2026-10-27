"""Personal I's suites, offline: the YAML reader, `run_ab.py suite` with the
fake `claude` on the worked example, rows only ever added, versions, the
report's control marks and agreement counts, and the LLM runs kept."""
import csv
import json
import os
import re
import shutil
import sys
import unittest
from pathlib import Path

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

from helpers import EXAMPLES, FAKE, REPO, run_ab, tmpdir

sys.path.insert(0, str(REPO))
import run_ab as R  # noqa: E402

PACKET = EXAMPLES / "personal-suites"


class Yaml(unittest.TestCase):
    def test_example_suites(self):
        d = R.parse_yaml((PACKET / "suites.yaml").read_text())
        self.assertEqual(d["schema"], "skill-eval-lite/suites@1")
        self.assertEqual([s["id"] for s in d["suites"]], ["board-drafts", "graph-briefs"])
        t = d["suites"][0]["tests"][0]
        self.assertEqual(t["check"], {"kind": "not-contains", "text": ["Q1", "cttee", "mtg"]})
        self.assertEqual(d["suites"][0]["tests"][2]["scale"]["4"], "Morgan would send it as it is.")
        self.assertTrue(d["suites"][1]["what"].startswith("How Wren prepares a brief"))
        self.assertNotIn("\n", d["suites"][1]["what"].strip(), "> folds lines")

    def test_forms(self):
        y = ('a: 1\nb: -2.5\nc: true\nd: ~\ne: "x: y # not a comment"\nf: \'it\'\'s\'  # a comment\n'
             'g: [1, "two", {k: v}]\nh:\n- x\n- k: v\n  m: n\ni: |\n  line\n    kept\nj: >-\n  folded\n  here\n')
        self.assertEqual(R.parse_yaml(y), {"a": 1, "b": -2.5, "c": True, "d": None, "e": "x: y # not a comment", "f": "it's",
                                           "g": [1, "two", {"k": "v"}], "h": ["x", {"k": "v", "m": "n"}],
                                           "i": "line\n  kept\n", "j": "folded here"})

    def test_errors(self):
        with self.assertRaises(R.YamlError):
            R.parse_yaml("a: 1\n  b: 2\n")
        with self.assertRaises(R.YamlError):
            R.parse_yaml('a: "open\n')
        with self.assertRaises(R.YamlError):
            R.parse_yaml("a: 1\na: 2\n")


@unittest.skipUnless(os.name == "posix", "the fake claude is a POSIX script")
class Suite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.chmod(FAKE, 0o755)
        cls.root = tmpdir()
        cls.out = cls.root / "packet"
        cls.r1 = run_ab("suite", PACKET / "suites.yaml", "--out", cls.out, "--claude", FAKE)
        cls.rows1 = (cls.out / "judgments.csv").read_text().splitlines()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def rows(self):
        with open(self.out / "judgments.csv", newline="") as fh:
            return list(csv.DictReader(fh))

    def test_first_run(self):
        self.assertEqual(self.r1.returncode, 0, self.r1.stdout + self.r1.stderr)
        rows = list(csv.DictReader(self.rows1))
        self.assertEqual(sum(r["route"] == "mechanical" for r in rows), 20, "two mechanical tests on 11 and 9 cases")
        self.assertEqual(sum(r["route"] == "llm" for r in rows), 20, "two LLM tests on 11 and 9 cases")
        self.assertEqual(list(rows[0].keys()), R.CSV_COLUMNS)
        by = {(r["item"], r["check"]): r for r in rows}
        self.assertEqual(by[("fault-shorthand", "no-shorthand")]["result"], "fail")
        self.assertEqual(by[("fault-no-search", "search-before-write")]["result"], "fail")
        self.assertEqual(by[("dana-brief-2", "search-before-write")]["result"], "pass", "the graph-removed run's chained search 'succeeds'")
        self.assertEqual(by[("fault-wrong-date", "facts-match-the-source")]["result"], "fail")
        self.assertEqual(by[("reference", "steps-follow")]["result"], "pass")
        self.assertEqual(by[("dana-brief-1", "search-before-write")]["judge"], "check.py")
        b = json.loads((self.out / "bundle.json").read_text())
        self.assertEqual(b["schema"], "skill-eval-lite/suite-bundle@1")
        self.assertEqual(len(b["rows"]), 40)
        case = next(c for c in b["suites"][1]["cases"] if c["id"] == "dana-brief-1")
        self.assertTrue(case["trace"] and case["trace"][0][0] == "Bash" and case["trace"][0][3], "a process case keeps its steps and results")

    def test_llm_runs_kept(self):
        runs = list((self.out / "tests" / "steps-follow" / "runs").glob("*.json"))
        self.assertEqual(len(runs), 9)
        rec = json.loads(runs[0].read_text())
        for key in ("input", "response", "decision", "model", "command", "when", "version", "decision_rule"):
            self.assertIn(key, rec)
        self.assertIn("### The trace", rec["input"], "the case is filled into the prompt")
        self.assertNotIn("{{case}}", rec["input"])
        self.assertNotIn("skill-eval-lite-test-", json.dumps(rec), "no temporary paths kept")

    def test_rows_only_added(self):
        r = run_ab("suite", self.out / "suites.yaml", "--claude", FAKE)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("LLM tests:", r.stdout, "LLM tests already run for this version are not rerun")
        lines = (self.out / "judgments.csv").read_text().splitlines()
        self.assertEqual(lines[:len(self.rows1)], self.rows1, "earlier rows are unchanged")
        self.assertEqual(len(lines), len(self.rows1) + 20, "a rerun adds the mechanical rows again")

    def test_version_changes_with_a_file(self):
        copy = self.root / "copy"
        shutil.copytree(self.out, copy)
        before = {t["id"]: t["version"] for s in R.Suites(copy / "suites.yaml").suites for t in s["tests"]}
        p = copy / "tests" / "steps-follow" / "prompt.md"
        p.write_text(p.read_text() + "\nOne more line.\n")
        after = {t["id"]: t["version"] for s in R.Suites(copy / "suites.yaml").suites for t in s["tests"]}
        self.assertNotEqual(before["steps-follow"], after["steps-follow"])
        self.assertEqual(before["search-before-write"], after["search-before-write"])

    def test_report_marks_a_missed_control(self):
        copy = self.root / "missed"
        shutil.copytree(self.out, copy)
        e = copy / "controls" / "board-drafts" / "fault-wrong-date" / "expect.json"
        d = json.loads(e.read_text())
        d["expect"]["no-shorthand"] = "fail"
        e.write_text(json.dumps(d))
        r = run_ab("suite", copy / "suites.yaml", "--no-llm")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rep = next((copy / "reports").glob("board-drafts-*.md")).read_text()
        row = next(l for l in rep.splitlines() if l.startswith("| no-shorthand |"))
        self.assertIn("MISSED (fail, got pass)", row)

    def test_agreement_counts(self):
        suite = next(s for s in R.Suites(self.out / "suites.yaml").suites if s["id"] == "graph-briefs")
        v = {t["id"]: t["version"] for t in suite["tests"]}
        rows = [r for r in self.rows() if r["item"] in {c["id"] for c in suite["cases"]}]
        def human(item, check, judge, result):
            return {"item": item, "config": "", "object": "process", "check": check, "route": "human", "judge": judge,
                    "version": v[check.replace("-reference", "")], "result": result, "reason": "test", "shown_left": "", "when": "2030-01-01T00:00:00Z"}
        rows += [human("reference", "sound-process", "SL", "4"), human("reference", "sound-process", "TW", "4"),
                 human("fault-no-search", "sound-process", "SL", "1"), human("fault-no-search", "sound-process", "TW", "2"),
                 human("dana-brief-2", "sound-process", "SL", "2"), human("dana-brief-2", "sound-process", "TW", "4"),
                 human("reference", "steps-follow-reference", "SL", "pass"), human("fault-no-search", "steps-follow-reference", "SL", "pass")]
        rep = R.suite_report(suite, rows, "now")
        self.assertIn("- sound-process: SL and TW gave the same answer on 1 of 3 cases, within one point on 2.", rep)
        self.assertIn("- steps-follow: the LLM and SL's reference judgments agree on 1 of 2 cases.", rep)
        self.assertIn("  - fault-no-search: SL pass, the LLM fail", rep)
        self.assertIn("| reference | reference | pass | pass | 4 (SL), 4 (TW) |", rep)
        self.assertIn("- dana-brief-2, sound-process: split", rep)

    def test_program_that_prints_nonsense(self):
        copy = self.root / "nonsense"
        shutil.copytree(self.out, copy)
        (copy / "tests" / "search-before-write" / "check.py").write_text("print('maybe')\n")
        run_ab("suite", copy / "suites.yaml", "--no-llm", "--suite", "graph-briefs")
        with open(copy / "judgments.csv", newline="") as fh:
            rows = [r for r in csv.DictReader(fh) if r["check"] == "search-before-write"]
        self.assertTrue(rows[-1]["result"] == "n/a" and "not pass or fail" in rows[-1]["reason"])

    def test_check_flag(self):
        r = run_ab("suite", PACKET / "suites.yaml", "--check")
        self.assertEqual(r.returncode, 0)
        self.assertIn("Nothing to fix", r.stdout)


if __name__ == "__main__":
    unittest.main()

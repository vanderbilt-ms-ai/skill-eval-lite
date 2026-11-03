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
        self.assertTrue(rows[-1]["result"] == "n/a" and "not pass, fail or n/a" in rows[-1]["reason"])

    def test_check_flag(self):
        r = run_ab("suite", PACKET / "suites.yaml", "--check")
        self.assertEqual(r.returncode, 0)
        self.assertIn("Nothing to fix", r.stdout)
        self.assertNotIn("note:", r.stdout, "the worked example has nothing to note")

    def test_reread_an_unknown_verdict_once(self):
        copy = self.root / "reread"
        shutil.copytree(self.out, copy)
        runs = sorted((copy / "tests" / "steps-follow" / "runs").glob("dana-brief-1__*.json"))
        rec = json.loads(runs[-1].read_text())
        # As 0.1.0 scored it: a labelled last line was unknown.
        rec.update(response="The lookups come first, and the brief uses only what they found.\n\nVerdict: PASS", decision="unknown",
                   when="2099-01-01T00:00:00Z")
        stored = copy / "tests" / "steps-follow" / "runs" / "dana-brief-1__20990101T000000Z.json"
        stored.write_text(json.dumps(rec))
        R.append_rows(copy / "judgments.csv", [{"item": "dana-brief-1", "object": "process", "check": "steps-follow", "route": "llm",
                                                 "judge": rec["model"], "version": rec["version"], "result": "unknown",
                                                 "reason": "", "when": rec["when"]}])
        r = run_ab("suite", copy / "suites.yaml", "--no-llm")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("re-read from tests/steps-follow/runs/dana-brief-1__20990101T000000Z.json, with no new run", r.stdout)
        with open(copy / "judgments.csv", newline="") as fh:
            rows = [x for x in csv.DictReader(fh) if x["reason"].startswith(R.REREAD)]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["item"], rows[0]["result"], rows[0]["when"]), ("dana-brief-1", "pass", "2099-01-01T00:00:00Z"))
        self.assertIn("read from a labelled last line", rows[0]["reason"])
        self.assertEqual(json.loads(stored.read_text())["decision"], "unknown", "the stored run is kept as it was")
        report = next((copy / "reports").glob("graph-briefs-*.md")).read_text()
        self.assertRegex(report, r"\| dana-brief-1 \| instance \| [a-z/]+ \| pass \(re-read\) \|")
        run_ab("suite", copy / "suites.yaml", "--no-llm")
        with open(copy / "judgments.csv", newline="") as fh:
            self.assertEqual(sum(x["reason"].startswith(R.REREAD) for x in csv.DictReader(fh)), 1, "re-read once, not again")


def write_case(folder: Path, files: dict):
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (folder / name).write_text(text)


class Records(unittest.TestCase):
    """What suite --check says about a process case's record (0.1.1)."""

    @classmethod
    def setUpClass(cls):
        cls.root = tmpdir()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def check(self, name, change) -> tuple[int, str]:
        copy = self.root / name
        shutil.copytree(PACKET, copy)
        change(copy)
        r = run_ab("suite", copy / "suites.yaml", "--check")
        return r.returncode, r.stdout + r.stderr

    def test_four_states(self):
        dana = "process/dana-brief-1"
        cases = {
            "renamed": (lambda c: (c / dana / "transcript.jsonl").rename(c / dana / "abc123.jsonl"),
                        1, f"Suite graph-briefs: {dana}/ has abc123.jsonl but no transcript.jsonl or trace.jsonl. "
                           "If abc123.jsonl is a Claude Code session, rename it transcript.jsonl."),
            "none": (lambda c: (c / dana / "transcript.jsonl").unlink(),
                     1, f"Suite graph-briefs: {dana}/ has no record of the run. Put the session in it as transcript.jsonl "
                        "(a Claude Code or Codex session) or trace.jsonl (one step a line)."),
            "both": (lambda c: (c / dana / "trace.jsonl").write_text('{"tool": "Bash", "detail": "ls"}\n'),
                     1, f"Suite graph-briefs: {dana}/ has both transcript.jsonl and trace.jsonl. Keep one: the one this case's tests should read."),
            "unreadable": (lambda c: (c / dana / "transcript.jsonl").write_text('{"type": "system"}\nnot JSON\n'),
                           1, f"Suite graph-briefs: {dana}/transcript.jsonl, line 2, is not a JSON object."),
            "no steps": (lambda c: (c / dana / "transcript.jsonl").write_text('{"type": "system", "subtype": "init"}\n'),
                         0, f"note: Suite graph-briefs: {dana}/transcript.jsonl has no tool steps. Is it the right session?"),
            "a session saved as trace.jsonl": (lambda c: (c / dana / "transcript.jsonl").rename(c / dana / "trace.jsonl"),
                                               1, f'Suite graph-briefs: {dana}/trace.jsonl, line 1, has no "tool".'),
            "an odd record": (lambda c: (c / dana / "transcript.jsonl").write_text(
                                  '{"type": "item.completed", "item": {"type": "file_change", "changes": {"a": 1}}}\n'
                                  '{"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Grep", "input": {"pattern": null}}]}}\n'),
                              0, "Nothing to fix"),
            "no process suite": (lambda c: (c / "suites.yaml").write_text((c / "suites.yaml").read_text().split("  - id: graph-briefs")[0]),
                                 0, "note: The brief asks for two suites: one on a product or a stage, and one on a process."),
        }
        for name, (change, code, message) in cases.items():
            rc, out = self.check(name, change)
            self.assertEqual(rc, code, f"{name}: {out}")
            self.assertIn(message, out, name)
        rc, out = self.check("renamed-run", cases["renamed"][0])
        r = run_ab("suite", self.root / "renamed-run" / "suites.yaml", "--no-llm")
        self.assertEqual(r.returncode, 1, "suite doesn't run a packet with a must-fix")

    def test_no_record_is_na_with_its_folder(self):
        folder = self.root / "packet" / "process" / "run-1"
        write_case(folder, {"output.md": "x"})
        c = {"kind": "trace-ran-command", "pattern": "kb/kb search*"}
        self.assertEqual(R.run_check(c, "x", R.read_trace(folder), no_trace="no transcript.jsonl or trace.jsonl in process/run-1/"),
                         ("n/a", "no transcript.jsonl or trace.jsonl in process/run-1/"))
        self.assertEqual(R.run_check({"kind": "trace-no-tool-outside", "allowed": []}, "x", None)[0], "n/a")

    def test_the_example_program_reads_as_read_trace_does(self):
        prog = PACKET / "tests" / "search-before-write" / "check.py"
        src = prog.read_text().rsplit("\nmain()", 1)[0]
        ns: dict = {}
        exec(compile(src, str(prog), "exec"), ns)
        folders = sorted((PACKET / "process").iterdir()) + sorted((PACKET / "controls" / "graph-briefs").iterdir())
        kinds = set()
        for folder in folders:
            have = [n for n in R.RECORD_FILES if (folder / n).is_file()]
            self.assertEqual(len(have), 1, folder)
            kinds.add(have[0])
            ours = [(s["tool"], s["error"]) for s in R.read_trace(folder)]
            theirs = [(s["tool"], bool(s.get("error"))) for s in ns["steps"](folder)]
            self.assertEqual(theirs, ours, folder.name)
        self.assertEqual(kinds, set(R.RECORD_FILES), "cases with each kind of record")
        both = self.root / "both"
        write_case(both, {"trace.jsonl": '{"tool": "Write", "detail": "a.md"}\n',
                          "transcript.jsonl": (PACKET / "process" / "dana-brief-1" / "transcript.jsonl").read_text()})
        self.assertEqual([s["tool"] for s in ns["steps"](both)], [s["tool"] for s in R.read_trace(both)], "the same file first")
        empty = self.root / "empty"
        empty.mkdir()
        import subprocess
        out = subprocess.run([sys.executable, str(prog), str(empty)], capture_output=True, text=True).stdout
        self.assertEqual(out.strip(), "n/a no transcript.jsonl or trace.jsonl in empty/")

    def test_a_rejected_step_is_marked(self):
        folder = self.root / "rejected"
        events = [{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "rm -rf drafts"}}]}},
                  {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": True,
                                                            "content": "The user doesn't want to proceed with this tool use. The tool use was rejected."}]}}]
        write_case(folder, {"transcript.jsonl": "\n".join(json.dumps(e) for e in events) + "\n"})
        steps = R.read_trace(folder)
        self.assertTrue(steps[0]["refused"])
        self.assertEqual(R.run_check({"kind": "trace-no-tool-outside", "allowed": ["Read"]}, None, steps)[0], "pass")

    def test_refused_steps_are_marked(self):
        for folder in ("process/priya-brief-2", "process/dana-brief-1"):
            steps = R.read_trace(PACKET / folder)
            self.assertTrue(any(s.get("refused") for s in steps), folder)
            self.assertTrue(all(s["error"] for s in steps if s.get("refused")))
        # The four recorded graph-removed runs: every refusal in the transcript, and nothing else, is marked.
        graph = EXAMPLES / "recorded" / "demo-graph-removed" / "transcripts"
        for f in sorted(graph.glob("*.jsonl")):
            events = [json.loads(x) for x in f.read_text().splitlines()]
            results = [c for e in events if isinstance(e.get("message"), dict) and isinstance(e["message"].get("content"), list)
                       for c in e["message"]["content"] if isinstance(c, dict) and c.get("type") == "tool_result"]
            denied = sum(1 for c in results if c.get("is_error") and R.DENIED in json.dumps(c.get("content"))[:80])
            steps = R.trace_of(events, R.Redactor(None))
            self.assertEqual(sum(bool(s.get("refused")) for s in steps), denied, f.name)
        self.assertEqual(len(list(graph.glob("*.jsonl"))), 4)


class LastLine(unittest.TestCase):
    def test_verdicts(self):
        table = {"PASS": ("pass", ""), "**FAIL**": ("fail", ""), "pass.": ("pass", ""),
                 "Verdict: PASS": ("pass", "read from a labelled last line"),
                 "Final answer: FAIL": ("fail", "read from a labelled last line"),
                 "The answer passes: PASS": ("pass", "read from the last line"),
                 "This is not a PASS": ("unknown", "the last line was not PASS, FAIL or UNKNOWN"),
                 "It doesn't PASS": ("unknown", "the last line was not PASS, FAIL or UNKNOWN"),
                 "PASS or FAIL": ("unknown", "the last line was not PASS, FAIL or UNKNOWN"),
                 "": ("unknown", "the last line was not PASS, FAIL or UNKNOWN"),
                 "Reasons.\n\n## Verdict - `UNKNOWN`": ("unknown", "read from a labelled last line"),
                 "Reasons.\n\n```\nFAIL\n```\n": ("fail", "")}
        for text, want in table.items():
            self.assertEqual(R.parse_verdict_noted(text), want, repr(text))

    def test_decisions(self):
        table = {"LEFT": ("LEFT", ""), "**RIGHT**": ("RIGHT", ""), "tie": ("TIE", ""), "UNKNOWN": ("UNKNOWN", ""),
                 "Decision: TIE": ("TIE", "read from a labelled last line"),
                 "Final answer - LEFT.": ("LEFT", "read from a labelled last line"),
                 "So the better one is RIGHT": ("RIGHT", "read from the last line"),
                 "Not LEFT": ("UNKNOWN", "the last line was not LEFT, RIGHT, TIE or UNKNOWN"),
                 "LEFT or RIGHT": ("UNKNOWN", "the last line was not LEFT, RIGHT, TIE or UNKNOWN"),
                 "": ("UNKNOWN", "the last line was not LEFT, RIGHT, TIE or UNKNOWN")}
        for text, want in table.items():
            self.assertEqual(R.parse_decision(text), want, repr(text))

    def test_recorded_verdicts_read_the_same(self):
        for f in (EXAMPLES / "recorded").glob("*/judge/*/*.json"):
            j = json.loads(f.read_text())
            self.assertEqual(R.parse_decision(j["response"])[0], j["decision"], f)
        for f in (EXAMPLES / "recorded").glob("**/runs/*.json"):
            j = json.loads(f.read_text())
            self.assertEqual(R.parse_verdict(j["response"]), j["decision"], f)


if __name__ == "__main__":
    unittest.main()

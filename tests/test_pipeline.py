"""The runner, offline: setup from a local template, run, bundle, judge, and
what happens on a timeout, a failure, a run that isn't isolated, and a
Claude Code that isn't logged in. The fake `claude` (tests/fake_claude.py)
stands in for Claude Code; no model is called."""
import json
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

from helpers import EXAMPLES, FAKE, class_assistant, fake_run, run_ab, tmpdir

POSIX = os.name == "posix"


@unittest.skipUnless(POSIX, "the fake claude is a POSIX script")
class Pipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.chmod(FAKE, 0o755)
        cls.root = tmpdir()
        cls.assistant = class_assistant(cls.root)
        cls.out = cls.root / "runs" / "graph"
        cls.r = fake_run(EXAMPLES / "demo-graph-removed.toml", cls.assistant, cls.out)
        cls.j = run_ab("judge", cls.out, "--claude", FAKE)
        cls.bundle = json.loads((cls.out / "bundle.json").read_text())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def test_setup(self):
        a = self.assistant
        self.assertTrue((a / "CLAUDE.md").read_text().startswith("# CLAUDE.md"), "the example's comment is stripped")
        self.assertIn("kb/kb search", (a / "CLAUDE.md").read_text())
        self.assertTrue((a / "kb" / "wiki" / "Dana Whitfield.md").exists())
        self.assertTrue((a / "kb" / "wiki" / "Using the knowledge graph.md").exists(), "the seed pages are copied")
        branch = subprocess.run(["git", "branch", "--show-current"], cwd=a, capture_output=True, text=True).stdout.strip()
        self.assertEqual(branch, "class-assistant")
        status = subprocess.run(["git", "status", "--porcelain"], cwd=a, capture_output=True, text=True).stdout
        self.assertEqual(status.strip(), "", "setup commits what it did")
        tracked = subprocess.run(["git", "ls-files", "kb/wiki"], cwd=a, capture_output=True, text=True).stdout
        self.assertIn("Dana Whitfield.md", tracked)
        again = run_ab("setup", a)
        self.assertEqual(again.returncode, 2)
        self.assertIn("not empty", again.stderr)

    def test_run(self):
        self.assertEqual(self.r.returncode, 0, self.r.stdout + self.r.stderr)
        outs = {(o["prompt"], o["round"], o["repeat"]): o for o in self.bundle["outputs"]}
        self.assertEqual(len(outs), 4)
        self.assertTrue(all(o["status"] == "ok" for o in outs.values()))
        a, c = outs[("prep-dana-checkin", "A", 1)], outs[("prep-dana-checkin", "C", 1)]
        self.assertIn("120,000", a["output"])
        self.assertNotIn("120,000", c["output"])
        self.assertIn("Graph: no", c["output"], "round C ran without kb/")
        self.assertEqual(a["output_from"], "files: notes/my-check-in-with-dana-is-wedne.md")
        self.assertIn(["Bash", "kb/kb search Dana"], a["trace"])
        self.assertIn(["Bash", "kb/kb search Dana", "error"], c["trace"])
        self.assertEqual(self.bundle["experiment"]["name"], "demo-graph-removed.toml")
        self.assertEqual(self.bundle["schema"], "skill-eval-lite/bundle@1")
        run = json.loads((self.out / "outputs/prep-dana-checkin/A/1/run.json").read_text())
        self.assertTrue(run["isolation"]["verified"])
        self.assertEqual(run["isolation"]["mcp_servers"], 0)
        self.assertEqual(run["isolation"]["auto_memory"], "off")
        self.assertEqual(run["command"][0], "claude")
        for flag in ("--setting-sources", "--strict-mcp-config", "--no-session-persistence", "--permission-prompts"):
            self.assertIn(flag, run["command"])
        self.assertEqual(run["transcript"], "transcripts/prep-dana-checkin__A__1.jsonl")
        self.assertTrue((self.out / run["transcript"]).exists())
        self.assertTrue((self.out / "versions/C/CHANGE.md").exists())
        self.assertTrue((self.out / "prompts/prep-dana-checkin/reference.md").exists())
        changes = json.loads((self.out / "outputs/prep-dana-checkin/C/1/run.json").read_text())["round_change"]
        self.assertIn("removed kb/", changes)

    def test_nothing_personal_saved(self):
        home = str(Path.home())
        for p in self.out.rglob("*"):
            if p.is_file():
                text = p.read_text(encoding="utf-8", errors="replace")
                self.assertNotIn(home + "/", text, p)
                self.assertNotIn("/skill-eval-lite-", text, p)
                self.assertIsNone(re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text), p)
                self.assertNotIn('"session_id"', text, p)
                self.assertNotIn("realmail.com", text, p)
        self.assertIn("(Looked in ~/Documents.)", (self.out / "outputs/prep-dana-checkin/A/1/output.md").read_text())

    def test_judge(self):
        self.assertEqual(self.j.returncode, 0, self.j.stdout + self.j.stderr)
        verdicts = self.bundle["judge"]
        self.assertEqual(len(verdicts), 2)
        for v in verdicts:
            self.assertIn(v["shown_left"], ("A", "C"))
            self.assertEqual(v["winner"], "A", "the fake judge prefers the draft with the graph's figure")
            self.assertEqual(v["decision"], "LEFT" if v["shown_left"] == "A" else "RIGHT")
        self.assertTrue((self.out / "judge" / "prompt.md").exists())
        saved = json.loads(next((self.out / "judge" / "A-C").glob("*.json")).read_text())
        self.assertIn("## Left", saved["input"])
        again = run_ab("judge", self.out, "--claude", FAKE)
        self.assertIn("already judged", again.stdout)

    def test_skips_runs_already_made(self):
        r = fake_run(EXAMPLES / "demo-graph-removed.toml", self.assistant, self.out)
        self.assertIn("Nothing to run", r.stdout)


@unittest.skipUnless(POSIX, "the fake claude is a POSIX script")
class Again(unittest.TestCase):
    """run --again (another line for round B, live) drops the pairs' old LLM verdicts, so that judge asks again."""

    def test_again_drops_stale_verdicts(self):
        os.chmod(FAKE, 0o755)
        root = tmpdir()
        assistant = class_assistant(root)
        out = root / "runs" / "again"
        self.assertEqual(fake_run(EXAMPLES / "demo-graph-removed.toml", assistant, out).returncode, 0)
        self.assertEqual(run_ab("judge", out, "--claude", FAKE).returncode, 0)
        self.assertEqual(len(json.loads((out / "bundle.json").read_text())["judge"]), 2)
        r = fake_run(EXAMPLES / "demo-graph-removed.toml", assistant, out, None, "--again")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Dropped 2 LLM verdicts", r.stdout)
        self.assertEqual(json.loads((out / "bundle.json").read_text())["judge"], [])
        self.assertEqual(list((out / "judge" / "A-C").glob("*.json")), [])
        again = run_ab("judge", out, "--claude", FAKE)
        self.assertNotIn("already judged", again.stdout)
        self.assertEqual(len(json.loads((out / "bundle.json").read_text())["judge"]), 2)


@unittest.skipUnless(POSIX, "the fake claude is a POSIX script")
class Failures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.chmod(FAKE, 0o755)
        cls.root = tmpdir()
        cls.assistant = class_assistant(cls.root)
        text = (EXAMPLES / "demo-graph-removed.toml").read_text()
        text = text.replace("timeout_seconds = 300", "timeout_seconds = 3")
        text = text.replace('files_from = "class-assistant"', f'files_from = "{(EXAMPLES / "class-assistant").as_posix()}"')
        cls.exp = cls.root / "short-timeout.toml"
        cls.exp.write_text(text)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def test_timeout_and_failure_are_kept(self):
        out = self.root / "runs" / "t"
        r = fake_run(self.exp, self.assistant, out, {"FAKE_CLAUDE_HANG": "Dana", "FAKE_CLAUDE_FAIL": "Priya"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        b = json.loads((out / "bundle.json").read_text())
        st = {(o["prompt"], o["round"]): o["status"] for o in b["outputs"]}
        self.assertEqual(st[("prep-dana-checkin", "A")], "timeout")
        self.assertEqual(st[("prep-priya-call", "C")], "failed")
        self.assertEqual(len(b["outputs"]), 4, "a failed run is kept, never missing")

    def test_stops_when_a_connector_loads(self):
        out = self.root / "runs" / "breach"
        r = fake_run(self.exp, self.assistant, out, {"FAKE_CLAUDE_CONNECTOR": "1"}, "--jobs", "1")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("STOPPED", r.stderr)
        self.assertIn("claude.ai Gmail", r.stderr)
        b = json.loads((out / "bundle.json").read_text())
        self.assertEqual(len(b["outputs"]), 1, "no run starts after a breach")
        self.assertIn("not isolated", b["outputs"][0]["reason"])

    def test_not_logged_in(self):
        r = fake_run(self.exp, self.assistant, self.root / "runs" / "login", {"FAKE_CLAUDE_LOGGED_OUT": "1"})
        self.assertEqual(r.returncode, 2)
        self.assertIn("not logged in", r.stderr)
        self.assertIn("Run `claude`", r.stderr)
        d = run_ab("doctor", "--claude", FAKE, env={"FAKE_CLAUDE_LOGGED_OUT": "1"})
        self.assertEqual(d.returncode, 1)
        self.assertIn("not logged in", d.stdout)

    def test_doctor(self):
        d = run_ab("doctor", "--claude", FAKE)
        self.assertEqual(d.returncode, 0, d.stdout + d.stderr)
        for line in ("Claude Code", "Isolation", "MCP servers and connectors", "The assistant's own skills load"):
            self.assertIn(line, d.stdout)

    def test_held_out_stay_sealed(self):
        r = run_ab("plan", self.exp, "--prompts", "reply-to-school")
        self.assertEqual(r.returncode, 2)
        self.assertIn("sealed", r.stderr)
        r = run_ab("plan", self.exp, "--held-out")
        self.assertIn("reply-to-school", r.stdout)


class Experiments(unittest.TestCase):
    def test_examples_check(self):
        for f in [EXAMPLES / "class-assistant" / "experiment.toml", *EXAMPLES.glob("demo-*.toml")]:
            r = run_ab("check", f)
            self.assertEqual(r.returncode, 0, f"{f}: {r.stdout}")
        r = run_ab("check", EXAMPLES / "class-assistant" / "experiment.toml")
        self.assertIn("Nothing is missing", r.stdout)

    def test_round_files(self):
        base = EXAMPLES / "class-assistant" / "rounds"
        b = (base / "B/.claude/identity/voice.md").read_text()
        d = (base / "D/.claude/identity/voice.md").read_text()
        self.assertIn("Derived from four Riverside board memos", b)
        self.assertTrue(all(ord(ch) < 128 for ch in b), "round B keeps the voice file's ASCII rule")
        self.assertNotIn("not enough signal yet", b)
        self.assertIn("not enough signal yet", d)
        heads = re.findall(r"^## .*", d, re.M)
        self.assertEqual(heads[0], "## What to Avoid", "round D reorders the sections")

    def test_intake_skill_and_agents_md_agree(self):
        repo = EXAMPLES.parent
        skill = (repo / ".claude/skills/experiment-intake/SKILL.md").read_text()
        agents = (repo / "AGENTS.md").read_text()
        self.assertTrue(skill.startswith("---\nname: experiment-intake\n"))
        body = skill.split("---\n", 2)[2].lstrip("\n")
        self.assertTrue(agents.endswith(body), "AGENTS.md must be SKILL.md's text without its front matter")
        self.assertIn("skill-eval-lite experiment-intake", agents[:400], "the runner recognizes AGENTS.md by this mark")

    def test_bad_experiment(self):
        root = tmpdir()
        bad = root / "bad.toml"
        bad.write_text('schema = "skill-eval-lite/experiment@1"\n[[rounds]]\nid = "A"\nchange = { how = "sideways" }\n')
        r = run_ab("check", bad)
        self.assertEqual(r.returncode, 1)
        self.assertIn("change.how", r.stdout)
        shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()

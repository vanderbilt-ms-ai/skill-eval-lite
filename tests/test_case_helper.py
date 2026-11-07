"""0.2.0: the suites-intake skill's helper, .claude/skills/suites-intake/case.py.

It lists Claude Code's saved sessions for a project, copies one into a
Personal I case as transcript.jsonl (keeping only its user and assistant
lines), prints a case's steps and its text as an LLM test reads them, and
finds what may be private in a folder, masked. These tests run it as the
skills do, in a home folder of their own: never the real ~/.claude.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import EXAMPLES, REPO  # noqa: E402

CASE = REPO / ".claude" / "skills" / "suites-intake" / "case.py"
RUN = EXAMPLES / "personal-suites" / "process" / "dana-brief-2"   # a real recorded run, made up for the class


class CaseHelper(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="sel-case-"))
        self.home = self.root / "home"
        self.home.mkdir()
        self.project = self.root / "my-system"
        self.project.mkdir()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def case(self, *args):
        env = dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home))
        return subprocess.run([sys.executable, str(CASE), *map(str, args)], capture_output=True, text=True,
                              cwd=REPO, env=env, timeout=60)

    def saved_session(self) -> Path:
        """A session as Claude Code saves it for self.project: the recorded
        run's user and assistant lines, with lines of the app's own that
        must not reach a case."""
        lines = [l for l in RUN.joinpath("transcript.jsonl").read_text(encoding="utf-8").splitlines()
                 if json.loads(l).get("type") in ("user", "assistant")]
        lines.insert(0, json.dumps({"type": "user", "message": {"role": "user", "content": "Please draft a brief for my call with Dana."}}))
        lines.insert(0, json.dumps({"type": "summary", "summary": "SETTINGS-AND-INSTRUCTIONS-0451"}))
        lines.append(json.dumps({"type": "file-history-snapshot", "snapshot": "SNAPSHOT-0451"}))
        d = self.home / ".claude" / "projects" / "".join(c if c.isalnum() else "-" for c in str(self.project.resolve()))
        d.mkdir(parents=True)
        f = d / "6f1c0a7e.jsonl"
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return f

    def test_no_sessions(self):
        r = self.case("sessions")
        self.assertEqual(r.returncode, 1)
        self.assertIn("No saved sessions", r.stdout)

    def test_sessions(self):
        self.saved_session()
        r = self.case("sessions")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1 sessions", r.stdout)
        r = self.case("sessions", self.project)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("6f1c0a7e.jsonl", r.stdout)
        self.assertIn("Please draft a brief for my call with Dana.", r.stdout, "the first request, to tell sessions apart")
        self.assertRegex(r.stdout, r"\b[1-9]\d* steps\b")
        r = self.case("sessions", self.root / "elsewhere")
        self.assertEqual(r.returncode, 1)
        self.assertIn("No saved sessions for", r.stdout)

    def test_copy_keeps_only_the_record(self):
        f = self.saved_session()
        dest = self.root / "my-suites" / "process" / "run-1"
        r = self.case("copy", f, dest)
        self.assertEqual(r.returncode, 0, r.stderr)
        text = (dest / "transcript.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("SETTINGS-AND-INSTRUCTIONS-0451", text)
        self.assertNotIn("SNAPSHOT-0451", text)
        self.assertEqual({json.loads(l)["type"] for l in text.splitlines()}, {"user", "assistant"})
        self.assertIn("Wrote", r.stdout)
        mine = self.case("steps", dest)
        theirs = self.case("steps", RUN)
        self.assertEqual(mine.returncode, 0, mine.stderr)
        self.assertEqual(mine.stdout, theirs.stdout, "the copy has the recorded run's steps")
        again = self.case("copy", f, dest)
        self.assertEqual(again.returncode, 1, "it never writes over a transcript")
        self.assertIn("is there already", again.stdout)

    def test_steps(self):
        r = self.case("steps", RUN)
        self.assertEqual(r.returncode, 0, r.stderr)
        steps = [json.loads(l) for l in r.stdout.splitlines()]
        self.assertGreater(len(steps), 2)
        self.assertTrue(all({"tool", "detail", "error"} <= set(s) for s in steps))
        r = self.case("steps", self.root)
        self.assertEqual(r.returncode, 1)
        self.assertIn("has no transcript.jsonl or trace.jsonl", r.stderr)

    def test_text(self):
        suites = EXAMPLES / "personal-suites" / "suites.yaml"
        r = self.case("text", suites, "graph-briefs", "dana-brief-2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertGreater(len(r.stdout), 200)
        r = self.case("text", suites, "graph-briefs", "no-such-case")
        self.assertEqual(r.returncode, 1)
        self.assertIn("No case no-such-case", r.stderr)

    def test_private_masks_what_it_finds(self):
        key = "sk-" + "proj-" + "A1b2C3d4E5f6G7h8I9"
        mail = "ellis.ward" + "@" + "northfield.org"   # written in two parts, so this file holds no address
        folder = self.root / "packet"
        folder.mkdir()
        (folder / "notes.md").write_text(f"Mail {mail}\nKey {key}\nSaved in {self.home}/drafts\n",
                                         encoding="utf-8")
        (folder / "fine.md").write_text("Nothing here but morgan@example.example.\n", encoding="utf-8")
        r = self.case("private", folder)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("an e-mail address", r.stdout)
        self.assertIn("a key or token", r.stdout)
        self.assertIn("your home folder's path", r.stdout)
        self.assertIn("3 things to look at.", r.stdout)
        self.assertNotIn(key, r.stdout, "a key is never printed whole")
        self.assertNotIn(mail, r.stdout)
        self.assertNotIn("fine.md", r.stdout, "an address at .example is made up")

    def test_usage(self):
        r = self.case()
        self.assertEqual(r.returncode, 2)
        self.assertIn("case.py sessions", r.stdout)


if __name__ == "__main__":
    unittest.main()

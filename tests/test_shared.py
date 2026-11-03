"""The logic that run_ab.py and wizard.html each hold a copy of, held to one
set of answers in tests/fixtures/:

- shell.json: how a shell step splits into commands (outside quotes,
  escapes, $(...) and heredoc bodies), which commands write a file, which
  patterns match a command (with ./, a longer path, NAME=value, command,
  exec or time before it), and the two trace checks' results and reasons;
- fingerprints.json: the freeze's fingerprint of TOML and JSON experiments,
  the same before and after freezing, with Windows line endings or trailing
  spaces, and different after a one-character change.

run_ab.py is checked directly; the wizard in headless Chrome (skipped
without it). The fixtures were written from run_ab.py's answers and read
line by line; a change to either copy that changes an answer fails here.
"""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cdp import Browser, find_chrome  # noqa: E402
from helpers import REPO  # noqa: E402

sys.path.insert(0, str(REPO))
import run_ab as R  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures"
SHELL = json.loads((FIXTURES / "shell.json").read_text(encoding="utf-8"))
PRINTS = json.loads((FIXTURES / "fingerprints.json").read_text(encoding="utf-8"))
CHROME = find_chrome() if os.name == "posix" else None


def steps(trace):
    return [{"tool": s[0], "detail": s[1], "error": len(s) > 2 and s[2] in ("error", "refused"),
             "refused": len(s) > 2 and s[2] == "refused"} for s in trace]


class Python(unittest.TestCase):
    def test_shell_split(self):
        for s in SHELL["split"]:
            self.assertEqual([list(p) for p in R.shell_split(s["cmd"])], s["parts"], repr(s["cmd"]))

    def test_patterns(self):
        for m in SHELL["match"]:
            got = any(R.pattern_matches(m["pattern"], p) for p, _ in R.shell_split(m["command"]))
            self.assertEqual(got, m["match"], f"{m['pattern']!r} on {m['command']!r}")

    def test_trace_checks(self):
        for c in SHELL["checks"]:
            self.assertEqual(R.run_check(c["check"], None, steps(c["trace"])), (c["result"], c["reason"]), f"{c['name']}, {c['check']['id']}")

    def test_fingerprints(self):
        for f in PRINTS["files"]:
            self.assertEqual(R.fingerprint(f["text"]), f["fingerprint"], f["name"])
        by = {f["name"]: f["fingerprint"] for f in PRINTS["files"]}
        self.assertEqual(by["the class experiment, as written"], by["the class experiment, frozen"])
        self.assertEqual(by["the class experiment, frozen"], by["the class experiment, frozen, with Windows line endings"])
        self.assertNotEqual(by["the class experiment, as written"], by["the class experiment, one character changed"])
        self.assertEqual(by["JSON"], by["JSON, frozen"])

    def test_the_fixture_covers_what_the_brief_asks(self):
        commands = {m["command"] for m in SHELL["match"]}
        for want in ("./kb/kb search Dana", "/tmp/run-1/kb/kb search Dana", "KB_DEBUG=1 kb/kb search Dana",
                     "cd sub && ./kb/kb node X", 'echo "kb/kb search"'):
            self.assertIn(want, commands)
        cmds = [s["cmd"] for s in SHELL["split"]]
        self.assertTrue(any('"a|b"' in c for c in cmds) and any("'a;b'" in c for c in cmds), "quoted pipes and semicolons")
        self.assertTrue(any("\\|" in c for c in cmds), "an escaped pipe")
        self.assertTrue(any("<<'EOF'" in c for c in cmds), "a heredoc")
        self.assertTrue(any("$(" in c for c in cmds), "a command substitution")


@unittest.skipUnless(CHROME, "headless Chrome is not available")
class Wizard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.b = Browser(CHROME, timeout=60)
        cls.b.goto((REPO / "wizard.html").as_uri())

    @classmethod
    def tearDownClass(cls):
        errors = list(cls.b.errors)
        cls.b.close()
        assert not errors, errors

    def js(self, code):
        return self.b.js(code)

    def test_shell_split(self):
        got = self.js(f"JSON.stringify({json.dumps(SHELL['split'])}.map(s => shellSplit(s.cmd)))")
        for s, parts in zip(SHELL["split"], json.loads(got)):
            self.assertEqual(parts, s["parts"], repr(s["cmd"]))

    def test_patterns(self):
        got = json.loads(self.js(f"JSON.stringify({json.dumps(SHELL['match'])}.map(m => shellSplit(m.command).some(([p]) => patternMatches(m.pattern, p))))"))
        for m, g in zip(SHELL["match"], got):
            self.assertEqual(g, m["match"], f"{m['pattern']!r} on {m['command']!r}")

    def test_trace_checks(self):
        got = json.loads(self.js(f"JSON.stringify({json.dumps(SHELL['checks'])}.map(c => traceCheck(c.check, c.trace.map(stepOf))))"))
        for c, g in zip(SHELL["checks"], got):
            self.assertEqual(g, [c["result"], c["reason"]], f"{c['name']}, {c['check']['id']}")

    def test_run_check_on_an_output(self):
        # The wizard's runCheck, as step 5 calls it, on a run whose trace has a refused step.
        c = {"id": "b", "kind": "trace-no-tool-outside", "object": "process", "allowed": ["Read", "Bash ls *"]}
        o = {"status": "ok", "output": "x", "trace": [["Bash", "ls ~/Documents/work", "refused"], ["Bash", "ls -la"]]}
        got = json.loads(self.js(f"JSON.stringify(runCheck({json.dumps(c)}, {{ id: 'p' }}, {json.dumps(o)}))"))
        self.assertEqual(got, {"result": "pass", "reason": "every step that ran was on the list; 1 attempt was refused: ls ~/Documents/work"})

    def test_fingerprints(self):
        got = json.loads(self.js(f"JSON.stringify({json.dumps(PRINTS['files'])}.map(f => fingerprint(f.text)))"))
        for f, g in zip(PRINTS["files"], got):
            self.assertEqual(g, f["fingerprint"], f["name"])


if __name__ == "__main__":
    unittest.main()

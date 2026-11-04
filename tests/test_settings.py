"""0.1.4: Skill Eval Lite's own Claude Code settings (.claude/settings.json).

In Claude Code in this folder (or `run_ab.py ask`), the commands that only
read or check run without a permission prompt: status, check, plan, doctor,
suite --check, and --help or --version. Every command that uses the
student's plan or changes something (run, judge, suite, setup, score, new,
ask) still asks. The file holds nothing else: no hooks, no environment, no
change to the permission mode. A run never reads this file: the runner runs
the assistant in a copy of its own folder.
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = ROOT / ".claude" / "settings.json"
READ_ONLY = {"status", "check", "plan", "doctor"}
NEVER = {"run", "judge", "setup", "score", "new", "ask"}
RULE = re.compile(r"^Bash\((python3|py) run_ab\.py (.+)\)$")


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.s = json.loads(SETTINGS.read_text(encoding="utf-8"))
        self.allow = self.s["permissions"]["allow"]

    def test_only_permissions_are_set(self):
        self.assertEqual(set(self.s) - {"$schema"}, {"permissions"})
        self.assertEqual(set(self.s["permissions"]), {"allow"})

    def test_every_rule_is_a_read_only_runner_command(self):
        for rule in self.allow:
            m = RULE.match(rule)
            self.assertIsNotNone(m, rule)
            words = m.group(2).split()
            first = words[0]
            if first in READ_ONLY:
                continue
            if first == "suite":
                self.assertEqual(words[-1], "--check", rule)
            elif first == "*":
                self.assertEqual(words[-1], "--help", rule)
            else:
                self.assertIn(first, {"--help", "--version"}, rule)
                self.assertEqual(len(words), 1, rule)

    def test_nothing_that_spends_or_changes_is_allowed(self):
        for rule in self.allow:
            words = RULE.match(rule).group(2).split()
            self.assertNotIn(words[0], NEVER, rule)
            self.assertFalse(words[0] == "suite" and words[-1] != "--check", rule)

    def test_python3_and_py_have_the_same_rules(self):
        by = {"python3": set(), "py": set()}
        for rule in self.allow:
            m = RULE.match(rule)
            by[m.group(1)].add(m.group(2))
        self.assertEqual(by["python3"], by["py"])
        for sub in READ_ONLY:
            self.assertTrue(any(r == sub or r.startswith(sub + " ") for r in by["python3"]), sub)

    def test_the_readme_says_what_it_allows(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(".claude/settings.json", readme)


if __name__ == "__main__":
    unittest.main()

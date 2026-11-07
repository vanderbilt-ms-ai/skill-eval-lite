"""0.2.0: Skill Eval Lite's own skills (.claude/skills/*/SKILL.md).

The skills take a student through Shared I and Personal I in Claude (the
desktop app's Code tab, or Claude Code in a terminal), with Claude running
every command. These tests hold them to what they promise: each is a skill
Claude Code can load, carries the version mark by which the runner leaves it
out of every run, names only commands and options that run_ab.py has, never
asks the student to type a command in a terminal (the one exception is
signing in, in get-ready), and agrees with the guide it mirrors for Codex
and for people (HELPER.md, AGENTS.md, CHECKS.md). The README lists every one.
"""
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import REPO  # noqa: E402

sys.path.insert(0, str(REPO))
import run_ab as R  # noqa: E402

SKILLS = REPO / ".claude" / "skills"
MARK = re.compile(r"<!-- skill-eval-lite ([a-z-]+), version (\d+) \(Skill Eval Lite ([0-9.]+)\) -->")
# The guides that carry a skill's text for Codex and for people: the same
# text without the front matter, after a comment of their own.
MIRRORS = {"skill-eval-helper": "HELPER.md", "experiment-intake": "AGENTS.md", "check-authoring": "CHECKS.md"}
# A sentence that asks the student to type a command in a terminal.
TERMINAL = re.compile(r"(?i)\b(type|paste|enter)\b[^.\n]{0,60}\bin (a|the|your) terminal\b"
                      r"|\bin (a|the|your) terminal\b[^.\n]{0,30}\b(type|paste)\b"
                      r"|\bopen a terminal\b"
                      r"|\b(type|paste)\s+`(python3|py|cd|git|cp|mv|mkdir|unzip) ")


def skill_dirs():
    return sorted(d for d in SKILLS.iterdir() if d.is_dir())


def split(text: str):
    """(front matter as a dict of its top-level keys, the body)."""
    if not text.startswith("---\n"):
        return None, text
    _, fm, body = text.split("---\n", 2)
    keys = {}
    for line in fm.splitlines():
        m = re.match(r"^([a-z][a-z-]*):\s*(.*)$", line)
        if m:
            keys[m.group(1)] = m.group(2)
    return keys, body


def commands(text: str):
    """Every run_ab.py command a skill names, in an inline code span or an
    indented code line: (the command, the options after it, the text)."""
    spans = re.findall(r"`([^`\n]+)`", text)
    spans += [line.strip() for line in text.splitlines() if line.startswith("    ") and "run_ab.py" in line]
    for s in spans:
        for m in re.finditer(r"run_ab\.py\s+([a-z][a-z-]*)([^`]*)", s):
            yield m.group(1), re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", m.group(2)), s


def subcommands():
    ap = R.parser()
    sub = next(a for a in ap._actions if a.__class__.__name__ == "_SubParsersAction")
    return {name: set(p._option_string_actions) for name, p in sub.choices.items()}, set(ap._option_string_actions)


class EverySkill(unittest.TestCase):
    def test_there_are_skills(self):
        names = {d.name for d in skill_dirs()}
        for must in ("get-ready", "wizard", "critique", "packet", "skill-eval-helper", "shared-i", "experiment-intake",
                     "run-experiment", "read-results", "check-authoring"):
            self.assertIn(must, names)

    def test_front_matter(self):
        for d in skill_dirs():
            with self.subTest(skill=d.name):
                f = d / "SKILL.md"
                self.assertTrue(f.is_file(), f"{d.name} has no SKILL.md")
                keys, body = split(f.read_text(encoding="utf-8"))
                self.assertIsNotNone(keys, f"{d.name}: SKILL.md starts with front matter")
                self.assertEqual(keys.get("name"), d.name, "name is the folder's name")
                self.assertIn("Use when", keys.get("description", ""), "the description says when to use it")
                self.assertLess(len(keys["description"]), 1024, "a description Claude Code shows in full")

    def test_version_mark(self):
        for d in skill_dirs():
            with self.subTest(skill=d.name):
                _, body = split((d / "SKILL.md").read_text(encoding="utf-8"))
                m = MARK.search("\n".join(body.splitlines()[:12]))
                self.assertIsNotNone(m, f"{d.name}: the version mark near the top")
                self.assertEqual(m.group(1), "helper" if d.name == "skill-eval-helper" else d.name)
                self.assertEqual(m.group(3), "0.2.0")

    def test_names_only_commands_and_options_that_exist(self):
        subs, top = subcommands()
        seen = 0
        for d in skill_dirs():
            text = (d / "SKILL.md").read_text(encoding="utf-8")
            for cmd, flags, span in commands(text):
                seen += 1
                with self.subTest(skill=d.name, command=span):
                    self.assertIn(cmd, subs, f"{d.name}: run_ab.py has no command {cmd!r}")
                    for flag in flags:
                        self.assertIn(flag, subs[cmd] | top, f"{d.name}: `{cmd}` has no option {flag}")
        self.assertGreater(seen, 40, "the skills name the runner's commands")

    def test_the_student_types_no_command(self):
        for d in skill_dirs():
            for n, line in enumerate((d / "SKILL.md").read_text(encoding="utf-8").splitlines(), 1):
                with self.subTest(skill=d.name, line=n):
                    self.assertIsNone(TERMINAL.search(line), f"{d.name}:{n} asks the student to type a command: {line.strip()}")

    def test_signing_in_is_the_one_exception(self):
        text = (SKILLS / "get-ready" / "SKILL.md").read_text(encoding="utf-8")
        fallback = text[text.index("If no page opens"):text.index("## 6.")]
        self.assertIn("claude auth login", fallback)
        self.assertIn("**Terminal**", fallback)
        self.assertIn("It is the only line they ever type", fallback)

    def test_mirrors_agree(self):
        for name, mirror in MIRRORS.items():
            with self.subTest(skill=name):
                _, body = split((SKILLS / name / "SKILL.md").read_text(encoding="utf-8"))
                text = (REPO / mirror).read_text(encoding="utf-8")
                self.assertTrue(text.startswith("<!-- skill-eval-lite "), f"{mirror} starts with its comment")
                rest = text[text.index("-->") + 3:]
                self.assertEqual(rest.lstrip("\n"), body.lstrip("\n"), f"{mirror} is {name}'s SKILL.md without its front matter")

    def test_the_readme_lists_every_skill(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        section = readme[readme.index("### Doing it all in Claude"):]
        for d in skill_dirs():
            self.assertTrue(f"`/{d.name}" in section, f"the README's table has /{d.name}")


class LeftOutOfRuns(unittest.TestCase):
    """A copy of one of Skill Eval Lite's skills in an assistant's own
    .claude/skills/ is left out of the run's copy, under any folder name;
    the assistant's own skills stay."""

    def test_every_skill_is_recognized(self):
        for d in skill_dirs():
            self.assertTrue(R.is_tool_skill(d), d.name)

    def test_copies_are_left_out(self):
        root = Path(tempfile.mkdtemp(prefix="sel-skills-"))
        try:
            asst, work = root / "assistant", root / "work"
            skills = asst / ".claude" / "skills"
            (skills / "drafting").mkdir(parents=True)
            (skills / "drafting" / "SKILL.md").write_text("---\nname: drafting\ndescription: the assistant's own\n---\n\nDraft.\n")
            (asst / "CLAUDE.md").write_text("# The assistant\n")
            for d in skill_dirs():
                shutil.copytree(d, skills / d.name)
                shutil.copytree(d, skills / ("my-copy-of-" + d.name))
            R.copy_assistant(asst, work)
            left = sorted(p.name for p in (work / ".claude" / "skills").iterdir())
            self.assertEqual(left, ["drafting"])
            self.assertEqual(sorted(f.name for f in work.rglob("*.py")), [], "a skill's helper (case.py) goes with it")
            self.assertTrue((work / "CLAUDE.md").is_file())
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_a_skill_that_only_mentions_skill_eval_lite_stays(self):
        root = Path(tempfile.mkdtemp(prefix="sel-skills-"))
        try:
            asst, work = root / "assistant", root / "work"
            (asst / ".claude" / "skills" / "evals").mkdir(parents=True)
            (asst / ".claude" / "skills" / "evals" / "SKILL.md").write_text(
                "---\nname: evals\ndescription: run skill-eval-lite for me\n---\n\nUse skill-eval-lite's runner.\n")
            R.copy_assistant(asst, work)
            self.assertTrue((work / ".claude" / "skills" / "evals" / "SKILL.md").is_file())
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

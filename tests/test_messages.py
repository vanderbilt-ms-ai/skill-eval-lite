"""0.2.0 (M4): every next step and every fix the runner prints names
Claude's way first.

Students work in Claude (the desktop app's Code tab), where Claude runs every
command through the skills in .claude/skills/. So each message of run_ab.py
that says what to do next, or how to fix something, names the skill that
does it before any command, in one form, run_ab.py's in_claude:

    Next, run the LLM judge. In Claude, type /run-experiment (in a terminal: python3 run_ab.py judge runs/x).

A message for Codex (--runner codex) gives its own command alone: the skills
are Claude's. Facts (results, counts, paths) are left as they are.

These tests read every message in run_ab.py's source: each say(), Fail(),
doctor's line(), sys.exit(), print() and append(), each step's text, each
module constant and each string a function returns, with each branch of a
conditional on its own. Then they run the commands that print advice, with the stand-in for
`claude`, and read what they print. And they check status's `skill` field.
"""
import ast
import itertools
import json
import os
import re
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import EXAMPLES, FAKE, FAKE_CODEX, REPO, fake_codex_env, fake_run, make_template, run_ab, tmpdir  # noqa: E402

SKILLS = {d.name for d in (REPO / ".claude" / "skills").iterdir() if (d / "SKILL.md").is_file()}
POSIX = os.name == "posix"

# A command a student could type, or a line telling them to type one.
TYPED = (r"\b(?:python3|py) run_ab\.py [a-z]|`run_ab\.py [a-z]|\bin a terminal\b|\btype `|\bcp -r |\bclaude auth login\b"
         r"|\b(?:open|start|xdg-open) wizard\.html|\bgit checkout\b|\bmkdir -p\b|\bunset [A-Z_]+|\bcurl -fsSL|\birm https")
COMMAND = re.compile(TYPED)
# The same in the source, where an f-string's commands start {PY} and the
# wizard's and the installer's are constants.
SOURCE_COMMAND = re.compile(TYPED + r"|\{PY\} run_ab\.py [a-z]|\{OPEN_WIZARD\}|\{INSTALL_CLAUDE\}")
WAY = re.compile(r"In Claude, type (/[a-z][a-z-]*(?: or /[a-z][a-z-]*)*)")

# Messages with a command in them that are facts, not advice.
FACTS = {
    "It knows where you are (python3 run_ab.py status)": "ask, in a terminal, says what it is starting",
}
# Constants that are commands, shown beside a skill (status's `command`).
COMMAND_CONSTANTS = {"PY", "OPEN_WIZARD", "INSTALL_CLAUDE"}


def skills_named(way: str) -> list[str]:
    return re.findall(r"/([a-z][a-z-]*)", way)


def names_claude_first(text: str, command: re.Pattern = COMMAND) -> str | None:
    """None when the text is fine; else what is wrong with it."""
    m = command.search(text)
    if not m:
        return None
    w = WAY.search(text)
    if not w or w.start() > m.start():
        return f"a command ({m.group(0)!r}) with no skill named before it"
    unknown = [s for s in skills_named(w.group(1)) if s not in SKILLS]
    return f"names no such skill: {unknown}" if unknown else None


# --- Reading run_ab.py's messages ------------------------------------------

def codex_test(test: str) -> tuple[bool, bool]:
    """For a condition on the runner, whether its true branch is Codex's and
    whether its false branch is."""
    if "codex" not in test.lower():
        return False, False
    negated = "!=" in test or test.lstrip().startswith("not ")
    return (not negated, negated)


class Messages:
    """Every message in run_ab.py's source, as (line, text, for_codex), each
    branch of a conditional apart. Values that can't be read from the source
    (a path, a count) are written {...}."""

    def __init__(self, source: str):
        self.tree = ast.parse(source)
        self.parent = {}
        for node in ast.walk(self.tree):
            for child in ast.iter_child_nodes(node):
                self.parent[child] = node
        self.module = self.assignments(self.tree, top=True)

    # Which names hold which values: in the module, then in each function.
    def assignments(self, scope, top=False) -> dict:
        found: dict = {}
        nodes = scope.body if top else ast.walk(scope)
        for node in nodes:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                found.setdefault(name, []).append((node.value, self.for_codex(node) or "CODEX" in name))
        return found

    def function(self, node):
        while node in self.parent:
            node = self.parent[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node
        return None

    def for_codex(self, node) -> bool:
        """Whether a node sits in a function, class or branch that is only for Codex."""
        child = node
        while child in self.parent:
            up = self.parent[child]
            if isinstance(up, (ast.FunctionDef, ast.ClassDef)) and "codex" in up.name.lower():
                return True
            if isinstance(up, ast.If):
                yes, no = codex_test(ast.unparse(up.test))
                if (yes and child in up.body) or (no and child in up.orelse):
                    return True
            child = up
        return False

    def variants(self, node, scope, depth=0) -> list[tuple[str, bool]]:
        if depth > 12:
            return [("{...}", False)]
        v = lambda n: self.variants(n, scope, depth + 1)  # noqa: E731
        if isinstance(node, ast.Constant):
            return [(node.value, False)] if isinstance(node.value, str) else [("{...}", False)]
        if isinstance(node, ast.JoinedStr):
            parts = []
            for x in node.values:
                if isinstance(x, ast.Constant):
                    parts.append([(x.value, False)])
                elif self.is_in_claude(x.value):
                    parts.append(v(x.value))
                else:
                    parts.append([("{" + ast.unparse(x.value) + "}", False)])
            return self.product(parts)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return self.product([v(node.left), v(node.right)])
        if isinstance(node, ast.IfExp):
            yes, no = codex_test(ast.unparse(node.test))
            return [(t, c or yes) for t, c in v(node.body)] + [(t, c or no) for t, c in v(node.orelse)]
        if isinstance(node, ast.Name):
            values = scope.get(node.id) or ([] if node.id in COMMAND_CONSTANTS else self.module.get(node.id)) or []
            if not values:
                return [("{" + node.id + "}", False)]
            return [(t, c or cx) for value, cx in values for t, c in v(value)]
        if self.is_in_claude(node):
            first = node.args[0]
            if isinstance(first, ast.Tuple):
                names = [(" or ".join("/" + e.value.lstrip("/") for e in first.elts), False)]
            else:
                names = [("/" + t.lstrip("/"), c) for t, c in v(first)]
            head = [("In Claude, type " + t, c) for t, c in names]
            if len(node.args) > 1:
                return self.product([head, [(" (in a terminal: ", False)], v(node.args[1]), [(")", False)]])
            return head
        return [("{...}", False)]

    @staticmethod
    def is_in_claude(node) -> bool:
        return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "in_claude"

    @staticmethod
    def product(parts) -> list[tuple[str, bool]]:
        out = []
        for combo in itertools.islice(itertools.product(*parts), 64):
            out.append(("".join(t for t, _ in combo), any(c for _, c in combo)))
        return out

    def sinks(self):
        """Every expression whose text reaches the student, with whether it
        is for Codex by its name (a module constant such as CODEX_NOT_LOGGED_IN)."""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
                if name in ("say", "Fail", "line", "exit", "print", "append"):
                    for arg in node.args:
                        yield arg, False
            elif isinstance(node, ast.Dict):
                for k, val in zip(node.keys, node.values):
                    if isinstance(k, ast.Constant) and k.value in ("what", "note"):
                        yield val, False
            elif isinstance(node, ast.Return) and node.value is not None and self.function(node) is not None:
                if self.function(node).name != "in_claude":
                    yield node.value, False
        for stmt in self.tree.body:
            if (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name)
                    and stmt.targets[0].id.isupper() and stmt.targets[0].id not in COMMAND_CONSTANTS):
                yield stmt.value, "CODEX" in stmt.targets[0].id

    def __iter__(self):
        scopes = {}
        for node, named_codex in self.sinks():
            fn = self.function(node)
            if fn not in scopes:
                scopes[fn] = self.assignments(fn) if fn is not None else {}
            codex = named_codex or self.for_codex(node)
            for text, c in self.variants(node, scopes[fn]):
                yield node.lineno, text, codex or c


MESSAGES = list(Messages((REPO / "run_ab.py").read_text(encoding="utf-8")))


class InTheSource(unittest.TestCase):
    def test_every_advice_message_names_a_skill_before_any_command(self):
        checked = 0
        for line, text, codex in MESSAGES:
            if codex or any(f in text for f in FACTS):
                continue
            problem = names_claude_first(text, SOURCE_COMMAND)
            if SOURCE_COMMAND.search(text):
                checked += 1
            with self.subTest(line=line):
                self.assertIsNone(problem, f"run_ab.py:{line}: {problem}:\n{text}")
        self.assertGreater(checked, 40, "the scan finds the runner's advice")

    def test_codex_messages_keep_their_own_commands(self):
        """With Codex there are no skills: its messages give the command alone."""
        codex = [(line, text) for line, text, c in MESSAGES if c and COMMAND.search(text.replace("{PY}", "python3"))]
        self.assertGreater(len(codex), 5)
        for line, text in codex:
            with self.subTest(line=line):
                self.assertNotIn("In Claude, type", text, f"run_ab.py:{line}")

    def test_every_step_has_a_skill(self):
        """Each of status's steps (a dict with `what` and `command`) names the
        skill beside its command: a real one, or None for Codex."""
        tree = ast.parse((REPO / "run_ab.py").read_text(encoding="utf-8"))
        seen = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = {k.value: v for k, v in zip(node.keys, node.values) if isinstance(k, ast.Constant)}
            if "what" in keys and "command" in keys:
                seen += 1
                with self.subTest(line=node.lineno):
                    self.assertIn("skill", keys, f"run_ab.py:{node.lineno}: a step with a command and no skill")
                    skill = keys["skill"]
                    self.assertIsInstance(skill, ast.Constant)
                    if skill.value is None:
                        self.assertIn("codex", ast.unparse(keys["command"]), "only Codex's steps have no skill")
                    else:
                        self.assertTrue(skill.value.startswith("/"), "the skill as it is typed")
                        self.assertIn(skill.value[1:], SKILLS)
        self.assertGreater(seen, 20)

    def test_the_form(self):
        sys.path.insert(0, str(REPO))
        import run_ab as R
        self.assertEqual(R.in_claude("run-experiment", "python3 run_ab.py judge runs/x"),
                         "In Claude, type /run-experiment (in a terminal: python3 run_ab.py judge runs/x)")
        self.assertEqual(R.in_claude(("shared-i", "personal-i")), "In Claude, type /shared-i or /personal-i")
        self.assertIsNone(names_claude_first("Next, run it. " + R.in_claude("run-experiment", "python3 run_ab.py run x")))
        self.assertIsNotNone(names_claude_first("Next, run it:  python3 run_ab.py run x"))
        self.assertIsNotNone(names_claude_first("Run python3 run_ab.py run x. In Claude, type /run-experiment."))
        self.assertIsNotNone(names_claude_first("In Claude, type /no-such-skill (in a terminal: python3 run_ab.py run x)"))


# --- What the commands print ----------------------------------------------

def advice_problems(text: str) -> list[str]:
    """Each printed line with a command and no skill named before it, on the
    line or, for status's second half, the line above."""
    problems, before = [], ""
    for line in text.splitlines():
        if line.strip():
            p = names_claude_first(line)
            if p and line.strip().startswith("(in a terminal:") and WAY.search(before):
                p = None
            if p and "codex" not in line.lower() and not any(f in line for f in FACTS):
                problems.append(f"{p}: {line.strip()}")
            before = line
    return problems


@unittest.skipUnless(POSIX, "the fakes are POSIX scripts")
class WhatIsPrinted(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for f in (FAKE, FAKE_CODEX):
            os.chmod(f, 0o755)
        cls.root = tmpdir()
        cls.work = cls.root / "sel"
        cls.work.mkdir()
        t, sha = make_template(cls.root)
        cls.assistant = cls.root / "class-assistant"
        cls.setup = run_ab("setup", cls.assistant, "--from", t, "--commit", sha)
        cls.env = fake_codex_env(cls.root)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def advice(self, r, *expect_skills):
        out = r.stdout + r.stderr
        self.assertEqual(advice_problems(out), [], out)
        for s in expect_skills:
            self.assertIn("In Claude, type /" + s, out)
        return out

    def ab(self, *args, env=None):
        return run_ab(*args, env={**self.env, **(env or {})}, cwd=self.work)

    def test_setup_and_doctor(self):
        self.assertEqual(self.setup.returncode, 0, self.setup.stdout + self.setup.stderr)
        self.advice(self.setup, "get-ready", "skill-eval-helper")
        self.advice(self.ab("doctor", "--claude", FAKE), "shared-i or /personal-i")
        out = self.advice(self.ab("doctor", "--claude", FAKE, env={"FAKE_CLAUDE_LOGGED_OUT": "1"}), "get-ready")
        self.assertIn("claude auth login", out)
        self.advice(self.ab("doctor", "--claude", FAKE, "--no-probe", env={"FAKE_CLAUDE_AUTH": "api_key"}), "get-ready")
        bare = self.root / "bin"
        bare.mkdir(exist_ok=True)
        if shutil.which("git") and not (bare / "git").exists():
            (bare / "git").symlink_to(shutil.which("git"))
        nobody = {"HOME": str(self.root / "home"), "PATH": str(bare), "SKILL_EVAL_LITE_CLAUDE": ""}
        out = self.advice(run_ab("doctor", "--no-probe", env=nobody, cwd=self.work), "get-ready")
        self.assertIn("FIX  Claude Code: Claude Code's `claude` command isn't installed", out)

    def test_an_experiment_from_new_to_judge(self):
        r = self.ab("new", "--root", self.work, "mine")
        self.advice(r, "experiment-intake", "shared-i")
        r = self.ab("new", "board", "--from", "class", "--root", self.work)
        self.advice(r, "shared-i")
        exp = self.work / "experiments" / "board" / "experiment.toml"
        self.advice(self.ab("new", "board", "--from", "class", "--root", self.work), "shared-i")
        self.advice(self.ab("check", exp), "wizard")
        self.advice(self.ab("run", exp, "--assistant", self.assistant, "--claude", FAKE), "wizard")
        broken = exp.parent / "broken.toml"
        broken.write_text('schema = "skill-eval-lite/experiment@1"\ntitle = "Nothing in it yet"\n')
        for cmd in ("check", "plan"):
            self.assertEqual(self.ab(cmd, broken).returncode, 1)
            self.advice(self.ab(cmd, broken), "skill-eval-helper")
        self.advice(self.ab("run", broken, "--assistant", self.assistant, "--claude", FAKE), "skill-eval-helper")
        self.advice(self.ab("run", exp, "--assistant", self.root / "nowhere", "--unfrozen", "--claude", FAKE), "get-ready")
        self.advice(self.ab("judge", self.work / "runs" / "none", "--claude", FAKE), "run-experiment")
        self.advice(self.ab("check", self.work / "experiments" / "none.toml"), "shared-i")

    def test_a_demonstration(self):
        demo = EXAMPLES / "demo-graph-removed.toml"
        self.advice(self.ab("check", demo), "skill-eval-helper")
        out = self.work / "runs" / "demo-graph-removed"
        r = fake_run(demo, self.assistant, out, self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.advice(r, "skill-eval-helper", "wizard")
        self.advice(self.ab("judge", out, "--claude", FAKE), "wizard")
        self.advice(self.ab("score", EXAMPLES / "demo-program-check.toml", "--out", self.work / "runs" / "nothing"),
                    "run-experiment")

    def test_suites(self):
        packet = self.root / "suites"
        shutil.copytree(EXAMPLES / "personal-suites", packet)
        r = self.ab("suite", packet / "suites.yaml", "--no-llm")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.advice(r, "wizard")
        shutil.rmtree(packet / "product" / "note-2")
        r = self.ab("suite", packet / "suites.yaml", "--check")
        self.assertEqual(r.returncode, 1)
        self.advice(r, "run-suites")

    def status(self, *extra, text=False, env=None):
        r = self.ab("status", "--claude", FAKE, "--codex", FAKE_CODEX, "--root", self.work, *extra,
                    *([] if text else ["--json"]), env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r if text else json.loads(r.stdout)

    def test_status_names_the_skill_first(self):
        for extra in ([], ["--assistant", self.root / "nowhere"], ["--project", "personal", "--assistant", self.root / "nowhere"]):
            with self.subTest(extra=extra):
                st = self.status(*extra)
                for step in st["next_steps"]:
                    self.assertIn(step["skill"].lstrip("/"), SKILLS)
                    self.assertTrue(step["skill"].startswith("/"))
                r = self.status(*extra, text=True)
                out = self.advice(r, st["next"]["skill"].lstrip("/"))
                way = out.index("In Claude, type " + st["next"]["skill"])
                self.assertLess(way, out.index("(in a terminal: " + st["next"]["command"] + ")"), "the skill, then the command")

    def test_status_with_codex_gives_the_command_alone(self):
        st = self.status("--runner", "codex")
        self.assertTrue(all(s["skill"] is None for s in st["next_steps"]))
        text = self.status("--runner", "codex", text=True).stdout
        self.assertNotIn("In Claude, type", text)
        self.assertIn("\n      " + st["next"]["command"] + "\n", text)


if __name__ == "__main__":
    unittest.main()

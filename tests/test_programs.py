"""Program checks (0.1.2): a check that is a Python program of the group's
own (CHECKS.md).

Offline: what `check` says about a program check, word for word where it
gives a line to copy (the sha256); its tests of each program on the
references and on its fixtures, and what happens when a program prints
something else, crashes or takes too long.
With the fake `claude`: `run` runs the programs at the end, keeps their
results in the bundle and beside each output, and the programs in the run
folder; a program sees only its case (never the round or the run's folder),
in Python's isolated mode, with no API keys, and can't change an output; a
failed run isn't given to it; `score` runs a check added after the runs and
marks it; a run made again is scored again; the assistant never sees the
checks; `new` copies them; `status` says when to score.
The guide (CHECKS.md) is the skill's text, and the runner leaves both out of
a run.
In headless Chrome: the wizard shows the bundle's results as checks, with
the runner's version of each; marks one from another version, and results
the experiment loaded in step 1 doesn't have; and the designer keeps a
program check and its folder, and its copy of `check` says what run_ab.py
says, word for word."""
import hashlib
import json
import os
import re
import shutil
import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cdp import Browser, find_chrome  # noqa: E402
from helpers import EXAMPLES, FAKE, REPO, class_assistant, fake_run, run_ab, tmpdir  # noqa: E402

sys.path.insert(0, str(REPO))
import run_ab as R  # noqa: E402

POSIX = os.name == "posix"
CHROME = find_chrome() if POSIX else None
WIZARD = REPO / "wizard.html"
CLASS = EXAMPLES / "class-assistant"
DEMO = EXAMPLES / "demo-program-check.toml"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def experiment_folder(root: Path, name: str = "exp", edit=None) -> Path:
    """The program-check demonstration in a folder of its own, with the class
    experiment's round, prompt and check files beside it."""
    d = root / name
    shutil.copytree(CLASS, d, ignore=shutil.ignore_patterns("experiment.toml", "__pycache__"))
    text = DEMO.read_text(encoding="utf-8").replace('files_from = "class-assistant"\n', "")
    (d / "experiment.toml").write_text(edit(text) if edit else text, encoding="utf-8")
    return d / "experiment.toml"


def add_check(path: Path, cid: str, program: str, entry: str = "", object_: str = "product"):
    """A program check of its own, in checks/<cid>/, added to the experiment file."""
    f = path.parent / "checks" / cid / "check.py"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(program, encoding="utf-8")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f'\n[[checks]]\nid = "{cid}"\nkind = "program"\nobject = "{object_}"\nprogram = "checks/{cid}/check.py"\n'
                 f'sha256 = "{sha(f)}"\n{entry}shows = "a test"\ndoes_not_show = "anything"\n')
    return f


def fixture(path: Path, cid: str, name: str, expect: str, files: dict):
    d = path.parent / "checks" / cid / "fixtures" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "expect.json").write_text(json.dumps({"expect": expect}), encoding="utf-8")
    for k, v in files.items():
        (d / k).write_text(v, encoding="utf-8")


# A program that says what it was given: its folder, its context, its flags
# and environment. It also deletes its copy of the output, which must not
# reach the run folder.
PROBE = r'''import json, os, sys
from pathlib import Path
case = Path(sys.argv[1])
ctx = json.loads((case / "context.json").read_text(encoding="utf-8"))
seen = {"ls": sorted(p.name for p in case.iterdir()), "cwd": Path.cwd().name, "here": Path.cwd().resolve() == case.resolve(),
        "iso": sys.flags.isolated, "keys": sorted(k for k in os.environ if "API_KEY" in k), "ctx": sorted(ctx),
        "case": ctx["case"], "start": ctx["starting_files"], "runner": ctx["runner"]}
(case / "output.md").unlink(missing_ok=True)
print("pass " + json.dumps(seen, separators=(",", ":")))
'''


class Check(unittest.TestCase):
    """`check` on program checks, offline: no runs."""

    def setUp(self):
        self.root = tmpdir()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def check(self, path):
        return run_ab("check", path)

    def test_the_demonstration_passes(self):
        r = self.check(DEMO)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("must fix", r.stdout)
        self.assertIn("program:   looked-up-first: a process check, so it isn't run on the references (they have no trace); "
                      "4 of 4 fixtures as expected.", r.stdout)
        self.assertIn("program:   no-made-up-amounts: passes 2 of 2 references; 3 of 3 fixtures as expected.", r.stdout)
        exp = R.Experiment(DEMO)
        for c in exp.program_checks():
            self.assertEqual(c["sha256"], sha(exp.program_path(c)), "the demonstration's sha256 lines are its programs'")

    def test_what_check_says(self):
        prog = CLASS / "checks" / "looked-up-first" / "check.py"
        digest = sha(prog)
        cases = {
            "no sha256": (lambda t: t.replace(f'sha256 = "{digest}"\n', ""), None,
                          f"must fix:  Check 'looked-up-first': add this line to it, so that the freeze covers its program: sha256 = \"{digest}\""),
            "a changed program": (None, lambda d: (d / "checks/looked-up-first/check.py").write_text(prog.read_text() + "# changed\n"),
                                  "its program has changed since its sha256 was written"),
            "a path that climbs out": (lambda t: t.replace('program = "checks/looked-up-first/check.py"', 'program = "../check.py"'), None,
                                       "its program must be a Python file in a folder of its own under checks/, such as "
                                       "checks/looked-up-first/check.py, not '../check.py'."),
            "a program not in a folder of its own": (lambda t: t.replace('program = "checks/looked-up-first/check.py"', 'program = "checks/check.py"'),
                                                     None, "in a folder of its own"),
            "not Python": (lambda t: t.replace('program = "checks/looked-up-first/check.py"', 'program = "checks/looked-up-first/check.sh"'),
                           None, "in a folder of its own"),
            "no program": (lambda t: t.replace('program = "checks/looked-up-first/check.py"\n', ""), None,
                           "is a program check: add program = \"checks/<id>/check.py\""),
            "a missing program": (lambda t: t.replace("checks/looked-up-first/check.py", "checks/looked-up-first/main.py"), None,
                                  "its program checks/looked-up-first/main.py isn't there"),
            "an id that can't name a file": (lambda t: t.replace('id = "looked-up-first"', 'id = "Looked Up"').replace('"looked-up-first", ', ""), None,
                                             "Check 'Looked Up': a program check's id names the files of its results"),
            "params that aren't a table": (lambda t: t.replace('params = { amounts = ["120,000", "50,000"] }', 'params = "120,000"'), None,
                                           "params must be a table"),
            "no time at all": (lambda t: t.replace('kind = "program"\nobject = "product"', 'kind = "program"\nobject = "product"\ntimeout_seconds = 0'),
                               None, "timeout_seconds must be a number of seconds, from 1 to 600."),
            "two checks with one id": (lambda t: t.replace('id = "names-the-renewal-amount"', 'id = "looked-up-first"'), None,
                                       "Two checks are called 'looked-up-first'. Give each its own id."),
            "an unknown kind": (lambda t: t.replace('kind = "matches"', 'kind = "regex"'), None,
                                "Use one of: contains, json-parses, matches, not-contains, program, trace-no-tool-outside, trace-ran-command, word-count."),
        }
        for name, (edit, files, want) in cases.items():
            with self.subTest(name):
                path = experiment_folder(self.root, re.sub(r"\W+", "-", name), edit)
                if files:
                    files(path.parent)
                r = self.check(path)
                self.assertEqual(r.returncode, 1, name + ": " + r.stdout)
                self.assertIn(want, r.stdout, name)

    def test_a_fixture_it_should_fail(self):
        path = experiment_folder(self.root)
        for name in ("wrote-first", "search-failed"):
            shutil.rmtree(path.parent / "checks" / "looked-up-first" / "fixtures" / name)
        r = self.check(path)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("(demo)    Check 'looked-up-first': add a fixture its program should fail: a folder in "
                      "checks/looked-up-first/fixtures/ with an expect.json that says \"fail\" (CHECKS.md).", r.stdout)

    def test_a_reference_it_fails_is_a_must_fix(self):
        path = experiment_folder(self.root, edit=lambda t: t.replace('amounts = ["120,000", "50,000"]', 'amounts = ["120,000"]'))
        r = self.check(path)
        self.assertEqual(r.returncode, 1)
        self.assertIn("must fix:  Check 'no-made-up-amounts' gives fail on the reference of prep-dana-checkin (50,000 is not an amount "
                      "the graph holds (it holds 120,000)). A check that fails a known-good output is set up wrong", r.stdout)
        self.assertIn("passes 0 of 2 references", r.stdout)
        run = run_ab("run", path, "--assistant", self.root, "--claude", FAKE)
        self.assertEqual(run.returncode, 1, "run won't start with a program that fails its own tests")
        self.assertIn("gives fail on the reference of prep-dana-checkin", run.stdout)

    def test_a_fixture_that_gives_the_wrong_answer(self):
        path = experiment_folder(self.root)
        (path.parent / "checks/looked-up-first/fixtures/wrote-first/expect.json").write_text('{"expect": "pass"}')
        (path.parent / "checks/looked-up-first/fixtures/no-trace/expect.json").write_text('{"note": "no expect"}')
        r = self.check(path)
        self.assertEqual(r.returncode, 1)
        self.assertIn("must fix:  Check 'looked-up-first': fixture wrote-first should give pass, but its program gave fail "
                      "(no lookup in the knowledge graph before the first write (step 1)).", r.stdout)
        self.assertIn("fixture no-trace needs an expect.json that says what its program should give", r.stdout)

    def test_programs_that_misbehave(self):
        path = experiment_folder(self.root)
        add_check(path, "says-yes", 'print("yes, it does")\n')
        fixture(path, "says-yes", "a", "fail", {"output.md": "x"})
        add_check(path, "crashes", 'raise SystemExit("cannot read the case")\n')
        fixture(path, "crashes", "a", "fail", {"output.md": "x"})
        add_check(path, "slow", 'import time\ntime.sleep(30)\nprint("pass late")\n', entry="timeout_seconds = 1\n")
        fixture(path, "slow", "a", "fail", {"output.md": "x"})
        # A module on PYTHONPATH (or in the user's site-packages) isn't imported: Python's isolated mode.
        planted = self.root / "planted"
        planted.mkdir()
        (planted / "planted.py").write_text("X = 1\n")
        add_check(path, "imports", 'try:\n    import planted\n    print("fail it imported planted.py")\n'
                                   'except ImportError:\n    print("pass nothing imported from outside")\n')
        fixture(path, "imports", "a", "pass", {"output.md": "x"})
        r = run_ab("check", path, env={"PYTHONPATH": str(planted)})
        out = r.stdout
        self.assertIn("Check 'says-yes': fixture a should give fail, but its program gave n/a (the program printed 'yes, it does', "
                      "not pass, fail or n/a).", out)
        self.assertIn("Check 'crashes': fixture a should give fail, but its program gave n/a (the program printed nothing: "
                      "cannot read the case).", out)
        self.assertIn("Check 'slow': fixture a should give fail, but its program gave n/a (the program took longer than 1 second, "
                      "so it gave no result).", out)
        self.assertIn("program:   imports: passes 3 of 3 references; 1 of 1 fixture as expected.", out)
        self.assertIn("reference of prep-dana-checkin (the program printed 'yes, it does'", out, "a product check runs on every reference")


@unittest.skipUnless(POSIX, "the fake claude is a POSIX script")
class Runs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.chmod(FAKE, 0o755)
        cls.root = tmpdir()
        cls.assistant = class_assistant(cls.root)
        cls.exp = experiment_folder(cls.root, "pc")
        add_check(cls.exp, "probe", PROBE)
        cls.out = cls.root / "runs" / "pc"
        cls.r = fake_run(cls.exp, cls.assistant, cls.out, {"MY_SERVICE_API_KEY": "secret-0451"})
        cls.bundle = json.loads((cls.out / "bundle.json").read_text())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def results(self, check=None, bundle=None):
        b = bundle or self.bundle
        return {(r["prompt"], r["round"], r["repeat"]): r for r in b["program_results"] if not check or r["check"] == check}

    def test_1_run_runs_the_programs(self):
        self.assertEqual(self.r.returncode, 0, self.r.stdout + self.r.stderr)
        self.assertIn("Ran the program checks (CHECKS.md): 12 results on the outputs and 5 on the references.", self.r.stdout)
        self.assertIn("looked-up-first              A: 2 pass · C: 2 fail", self.r.stdout)
        looked = self.results("looked-up-first")
        self.assertEqual({k: v["result"] for k, v in looked.items()},
                         {("prep-dana-checkin", "A", 1): "pass", ("prep-priya-call", "A", 1): "pass",
                          ("prep-dana-checkin", "C", 1): "fail", ("prep-priya-call", "C", 1): "fail"})
        self.assertEqual(looked[("prep-dana-checkin", "C", 1)]["reason"], "no lookup in the knowledge graph before the first write (step 2)")
        exp = R.Experiment(self.exp)
        versions = {c["id"]: R.program_version(c) for c in exp.program_checks()}
        outs = {(o["prompt"], o["round"], o["repeat"]): o for o in self.bundle["outputs"]}
        for (p, r, k), res in self.results().items():
            self.assertEqual(res["version"], versions[res["check"]])
            self.assertFalse(res["added_after_run"], "the runs were made with these checks")
            self.assertEqual(res["output_when"], outs[(p, r, k)]["when"])
            kept = json.loads((self.out / "outputs" / p / r / str(k) / "checks" / f"{res['check']}.json").read_text())
            check = next(c for c in exp.program_checks() if c["id"] == res["check"])
            self.assertEqual((kept["result"], kept["sha256"]), (res["result"], check["sha256"]), "kept beside its output too")
        self.assertEqual(outs[("prep-dana-checkin", "A", 1)]["program_checks"], versions)
        refs = {(r["check"], r["prompt"]): r["result"] for r in self.bundle["program_reference_results"]}
        self.assertEqual(refs[("no-made-up-amounts", "prep-dana-checkin")], "pass")
        self.assertNotIn(("looked-up-first", "prep-dana-checkin"), refs, "a process check isn't run on a reference")
        for f in ("checks/looked-up-first/check.py", "checks/looked-up-first/fixtures/wrote-first/trace.jsonl", "checks/probe/check.py"):
            self.assertTrue((self.out / f).is_file(), f"the run folder keeps the programs as they were run: {f}")

    def test_2_what_a_program_sees(self):
        for (p, r, k), res in self.results("probe").items():
            seen = json.loads(res["reason"])
            self.assertEqual(seen["ls"], ["context.json", "files", "output.md", "reference.md", "trace.jsonl", "transcript.jsonl"], p)
            self.assertEqual((seen["cwd"], seen["here"], seen["iso"], seen["case"], seen["runner"]), ("case", True, 1, "output", "claude-code"))
            self.assertEqual(seen["keys"], [], "no API key reaches a program")
            self.assertEqual(seen["ctx"], ["case", "check", "files", "object", "output", "params", "prompt", "reference", "runner",
                                           "starting_files", "tool", "trace", "transcript"], "never the round, the repeat or the run's folder")
            self.assertTrue((self.out / "outputs" / p / r / str(k) / "output.md").read_text().strip(), "a program can't change an output")
        ref = next(x for x in self.bundle["program_reference_results"] if x["check"] == "probe" and x["prompt"] == "reply-to-school")
        seen = json.loads(ref["reason"])
        self.assertEqual((seen["case"], seen["start"]), ("reference", ["input/school-email.md"]))
        self.assertIn("starting", seen["ls"])
        self.assertNotIn("trace.jsonl", seen["ls"])
        self.assertNotIn("secret-0451", (self.out / "bundle.json").read_text())

    def test_3_a_failed_run_is_not_given_to_a_program(self):
        out = self.root / "runs" / "pc-fail"
        r = fake_run(self.exp, self.assistant, out, {"FAKE_CLAUDE_FAIL": "Priya Raman is calling"}, "--rounds", "A")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        b = json.loads((out / "bundle.json").read_text())
        got = self.results(bundle=b)
        self.assertIn(("prep-dana-checkin", "A", 1), got)
        self.assertNotIn(("prep-priya-call", "A", 1), got, "the wizard fails every check on a failed run")

    def test_4_score_a_check_added_after_the_runs(self):
        later = self.exp.parent / "later.toml"
        later.write_text(self.exp.read_text())
        add_check(later, "only-known", (CLASS / "checks/no-made-up-amounts/check.py").read_text(),
                  entry='params = { amounts = ["120,000", "50,000", "75,000"] }\nprompts = ["prep-dana-checkin", "prep-priya-call"]\n')
        out = self.root / "runs" / "pc-later"
        shutil.copytree(self.out, out)
        s = run_ab("score", later, "--out", out)
        self.assertEqual(s.returncode, 0, s.stdout + s.stderr)
        self.assertIn("4 results on the outputs and 2 on the references", s.stdout, "only the new check had no result")
        self.assertIn("The runs were made without only-known as it is now: it was added or changed after the runs.", s.stdout)
        self.assertIn("is not the experiment file these runs were made with", s.stdout)
        b = json.loads((out / "bundle.json").read_text())
        self.assertTrue(all(r["added_after_run"] for r in b["program_results"] if r["check"] == "only-known"))
        self.assertFalse(any(r["added_after_run"] for r in b["program_results"] if r["check"] != "only-known"))
        again = run_ab("score", later, "--out", out)
        self.assertIn("already has a result from each program check as it is now", again.stdout)
        again = run_ab("score", later, "--out", out, "--again", "--checks", "only-known")
        self.assertIn("4 results on the outputs and 2 on the references", again.stdout)
        bad = run_ab("score", later, "--out", out, "--checks", "nope")
        self.assertEqual(bad.returncode, 2)
        self.assertIn("has no program check called nope", bad.stderr)
        none = run_ab("score", EXAMPLES / "demo-graph-removed.toml", "--out", out)
        self.assertIn("has no program checks", none.stdout)

    def test_5_the_assistant_never_sees_the_checks(self):
        a = self.root / "inside"
        shutil.copytree(self.assistant, a)
        for sub in ("rounds", "prompts", "checks"):
            shutil.copytree(self.exp.parent / sub, a / sub)
        (a / "checks" / "its-own").mkdir()
        (a / "checks" / "its-own" / "notes.md").write_text("The assistant's own folder called checks/.\n")
        (a / "experiment.toml").write_text(self.exp.read_text())
        r = fake_run(a / "experiment.toml", a, self.root / "runs" / "inside", None, "--rounds", "A", "--prompts", "prep-dana-checkin", "--keep-work")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        work = Path(re.search(r"kept the working copy: (\S+)", r.stdout).group(1))
        try:
            self.assertFalse((work / "checks" / "looked-up-first").exists(), "a program check's folder is left out of the run")
            self.assertFalse((work / "checks" / "probe").exists())
            self.assertFalse((work / "experiment.toml").exists())
            self.assertTrue((work / "checks" / "its-own" / "notes.md").is_file(), "the assistant's own checks/ folder is kept")
        finally:
            shutil.rmtree(work.parent, ignore_errors=True)

    def test_6_new_copies_the_checks_and_status_says_score(self):
        work = self.root / "sel"
        work.mkdir()
        r = run_ab("new", "pc", "--from", DEMO, "--root", work, cwd=work)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("checks/ (looked-up-first, no-made-up-amounts)", r.stdout)
        path = work / "experiments" / "pc" / "experiment.toml"
        self.assertEqual(run_ab("check", path).returncode, 0)

        def freeze():
            text = re.sub(r'\[frozen\]\ndate = "[^"]*"\nhash = "[^"]*"', "[frozen]\ndate = \"\"\nhash = \"\"", path.read_text())
            path.write_text(text.replace('[frozen]\ndate = ""\nhash = ""', f'[frozen]\ndate = "2026-11-03T12:00:00Z"\nhash = "{R.fingerprint(text)}"'))
        freeze()
        self.assertEqual(fake_run(path, self.assistant, work / "runs" / "pc").returncode, 0)

        def status():
            s = run_ab("status", "--claude", FAKE, "--root", work, "--assistant", self.assistant, "--json", cwd=work)
            self.assertEqual(s.returncode, 0, s.stdout + s.stderr)
            return json.loads(s.stdout)
        self.assertIn("judge", status()["next"]["command"], "every program check has its results")
        add_check(path, "only-known", (CLASS / "checks/no-made-up-amounts/check.py").read_text(),
                  entry='params = { amounts = ["120,000", "50,000"] }\nprompts = ["prep-dana-checkin", "prep-priya-call"]\n')
        freeze()
        st = status()
        self.assertEqual(st["next"]["command"], "python3 run_ab.py score experiments/pc/experiment.toml --out runs/pc")
        self.assertIn("4 of their results are missing or out of date", st["next"]["what"])

    def test_9_a_run_made_again_is_scored_again(self):
        r = fake_run(self.exp, self.assistant, self.out, None, "--again", "--rounds", "A", "--prompts", "prep-dana-checkin")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        b = json.loads((self.out / "bundle.json").read_text())
        o = next(o for o in b["outputs"] if (o["prompt"], o["round"]) == ("prep-dana-checkin", "A"))
        got = self.results(bundle=b)
        self.assertEqual(len(b["program_results"]), len(self.bundle["program_results"]))
        for c in ("looked-up-first", "no-made-up-amounts", "probe"):
            r = next(x for x in b["program_results"] if x["check"] == c and (x["prompt"], x["round"]) == ("prep-dana-checkin", "A"))
            self.assertEqual(r["output_when"], o["when"], c)
        self.assertTrue(got)


class Guide(unittest.TestCase):
    def test_checks_md_is_the_skill(self):
        skill = (REPO / ".claude/skills/check-authoring/SKILL.md").read_text(encoding="utf-8")
        guide = (REPO / "CHECKS.md").read_text(encoding="utf-8")
        self.assertTrue(skill.startswith("---\nname: check-authoring\n"))
        self.assertTrue(guide.endswith(skill.split("---\n", 2)[2].lstrip("\n")), "CHECKS.md is SKILL.md without its front matter")
        self.assertIn(R.CHECKS_MARK, guide[:400], "the runner leaves CHECKS.md out of a run by this mark")
        for must in ("python3 -I -B -X utf8", "context.json", "never holds the round", "expect.json", "sha256", "score",
                     "exploratory", "never calls a model"):
            self.assertIn(must, guide)
        for f in ("AGENTS.md", ".claude/skills/experiment-intake/SKILL.md", "HELPER.md"):
            self.assertIn("CHECKS.md", (REPO / f).read_text(encoding="utf-8"), f)

    def test_the_runner_leaves_the_guide_out(self):
        root = tmpdir()
        try:
            src, dst = root / "asst", root / "copy"
            (src / ".claude" / "skills" / "check-authoring").mkdir(parents=True)
            shutil.copy(REPO / ".claude/skills/check-authoring/SKILL.md", src / ".claude/skills/check-authoring/SKILL.md")
            shutil.copy(REPO / "CHECKS.md", src / "CHECKS.md")
            (src / "CLAUDE.md").write_text("# mine\n")
            dst.mkdir()
            R.copy_assistant(src, dst)
            self.assertEqual(sorted(p.relative_to(dst).as_posix() for p in dst.rglob("*") if p.is_file()), ["CLAUDE.md"])
        finally:
            shutil.rmtree(root, ignore_errors=True)


@unittest.skipUnless(CHROME, "headless Chrome is not available")
class Wizard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.chmod(FAKE, 0o755)
        cls.root = tmpdir()
        assistant = class_assistant(cls.root)
        r = fake_run(DEMO, assistant, cls.root / "runs" / "pc")
        assert r.returncode == 0, r.stdout + r.stderr
        cls.bundle = json.loads((cls.root / "runs" / "pc" / "bundle.json").read_text())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def setUp(self):
        self.b = Browser(CHROME, timeout=60)
        self.b.goto(WIZARD.as_uri())
        self.b.js("localStorage.clear()")
        self.b.goto(WIZARD.as_uri())

    def tearDown(self):
        errors = list(self.b.errors)
        self.b.close()
        self.assertEqual(errors, [], "console errors in the wizard")

    def load(self, text):
        self.b.js(f"loadIntake({json.dumps(text)}, 'experiment.toml'); loadBundle({json.dumps(self.bundle)}, 'bundle.json'); true")

    def test_the_bundles_results_are_checks(self):
        b = self.b
        self.load(DEMO.read_text())
        exp = tomllib.loads(DEMO.read_text())
        for c in (c for c in exp["checks"] if c["kind"] == "program"):
            self.assertEqual(b.js(f"programVersion(X.checks.find(c => c.id === {json.dumps(c['id'])}))"), R.program_version(c), c["id"])
        got = json.loads(b.js("JSON.stringify(['A', 'C'].map(r => runCheck(X.checks.find(c => c.id === 'looked-up-first'), promptById('prep-dana-checkin'), S.outputs[okey('prep-dana-checkin', r, 1)])))"))
        self.assertEqual([g["result"] for g in got], ["pass", "fail"])
        self.assertEqual(got[1]["reason"], "no lookup in the knowledge graph before the first write (step 2)")
        refs = json.loads(b.js("JSON.stringify(referenceResults().filter(x => x.check.id === 'no-made-up-amounts').map(x => [x.prompt, x.r.result]))"))
        self.assertEqual(refs, [["prep-dana-checkin", "pass"], ["prep-priya-call", "pass"]])
        self.assertEqual(b.js("results().checks.find(x => x.c.id === 'looked-up-first').s.est"), -1)
        rows = json.loads(b.js("JSON.stringify(controlRows(roundById('C')).filter(r => r.source === 'looked-up-first').map(r => r.verdict))"))
        self.assertEqual(rows, ["as predicted"])
        csv = b.js("judgmentsCsv()")
        v = R.program_version(next(c for c in exp["checks"] if c["id"] == "looked-up-first"))
        self.assertIn(f"prep-dana-checkin/1,C,process,looked-up-first,mechanical,checks/looked-up-first/check.py (run_ab.py),{v},fail,", csv)
        self.assertIn("prep-dana-checkin/reference,reference,product,no-made-up-amounts,mechanical,", csv)
        self.assertIsNone(b.js("S.programNote"))
        b.js("render(); true")
        self.assertIn("are programs, which this page can’t run", b.js("document.getElementById('program-references').textContent"))
        b.js("openRun('prep-dana-checkin', 'C', 1); true")
        drawer = b.js("document.body.innerText")
        self.assertIn("looked-up-first", drawer)
        self.assertIn("no lookup in the knowledge graph before the first write (step 2)", drawer)

    def test_another_version_and_results_it_doesnt_have(self):
        b = self.b
        self.load(DEMO.read_text().replace('amounts = ["120,000", "50,000"]', 'amounts = ["120,000", "50,000", "1"]'))
        r = json.loads(b.js("JSON.stringify(runCheck(X.checks.find(c => c.id === 'no-made-up-amounts'), promptById('prep-dana-checkin'), S.outputs[okey('prep-dana-checkin', 'A', 1)]))"))
        self.assertEqual(r["result"], "n/a")
        self.assertIn("another version of this check", r["reason"])
        self.assertIn("no-made-up-amounts", b.js("S.programNote"))
        self.assertNotIn("looked-up-first", b.js("S.programNote"))
        later = dict(self.bundle, program_results=[dict(x, added_after_run=True) for x in self.bundle["program_results"]])
        b.js(f"loadIntake({json.dumps(DEMO.read_text())}, 'experiment.toml'); loadBundle({json.dumps(later)}, 'bundle.json'); true")
        self.assertTrue(b.js("addedAfter(X.checks.find(c => c.id === 'looked-up-first'))"))
        self.assertFalse(b.js("addedAfter(X.checks.find(c => c.id === 'searched-the-graph'))"))

    def test_the_designer_keeps_a_program_check(self):
        b = self.b
        files = json.loads(b.js("JSON.stringify(edOutput(edFromStart('demo-program-check')).files)"))
        for name in ("checks/looked-up-first/check.py", "checks/looked-up-first/fixtures/wrote-first/expect.json",
                     "checks/no-made-up-amounts/fixtures/made-up-amount/output.md"):
            self.assertEqual(files[name], (CLASS / name).read_text(), name)
        got = tomllib.loads(files["experiment.toml"])
        want = tomllib.loads(DEMO.read_text())
        self.assertEqual(got["checks"], want["checks"])
        dropped = json.loads(b.js("const D = edFromStart('demo-program-check'); D.checks = D.checks.filter(c => c.id !== 'looked-up-first'); JSON.stringify(Object.keys(edOutput(D).files))"))
        self.assertFalse(any(k.startswith("checks/looked-up-first/") for k in dropped), "a removed program check's folder isn't saved")
        self.assertIn("no-made-up-amounts", b.js("ezCheckCard(edFromStart('demo-program-check'), Object.assign(edFromStart('demo-program-check').checks[3], { _open: true }), 3).textContent"))

    def test_the_designers_check_says_what_run_ab_says(self):
        text = DEMO.read_text().replace('files_from = "class-assistant"\n', "")
        files = {p.relative_to(CLASS).as_posix(): p.read_text() for p in sorted(CLASS.rglob("*"))
                 if p.is_file() and p.name != "experiment.toml" and "__pycache__" not in p.parts}
        prog = "checks/looked-up-first/check.py"
        digest = sha(CLASS / prog)
        variants = {
            "as it is": (text, files),
            "no sha256": (text.replace(f'sha256 = "{digest}"\n', ""), files),
            "a changed program": (text, dict(files, **{prog: files[prog] + "# changed\n"})),
            "a bad path": (text.replace(f'program = "{prog}"', 'program = "checks/x.py"'), files),
            "a missing program": (text, {k: v for k, v in files.items() if k != prog}),
            "no program": (text.replace(f'program = "{prog}"\n', ""), files),
            "a bad id": (text.replace('id = "looked-up-first"', 'id = "Looked_Up"'), files),
            "params, time": (text.replace('params = { amounts = ["120,000", "50,000"] }', 'params = "x"\ntimeout_seconds = 900'), files),
            "two ids": (text.replace('id = "names-the-renewal-amount"', 'id = "looked-up-first"'), files),
            "no fixture to fail": (text, {k: v for k, v in files.items() if not re.match(r"checks/looked-up-first/fixtures/(wrote-first|search-failed)/", k)}),
        }
        plain = None
        for i, (name, (t, fs)) in enumerate(variants.items()):
            with self.subTest(name):
                folder = self.root / "mirror" / str(i)
                for rel, body in dict(fs, **{"experiment.toml": t}).items():
                    (folder / rel).parent.mkdir(parents=True, exist_ok=True)
                    (folder / rel).write_text(body, encoding="utf-8")
                errors, warns = R.Experiment(folder / "experiment.toml").problems()
                norm = lambda xs: [x.replace(str(folder), "BASE") for x in xs]  # noqa: E731
                got = json.loads(self.b.js(f"JSON.stringify(checkProblems(parseToml({json.dumps(t)}), {json.dumps(fs)}, 'BASE'))"))
                self.assertEqual(got["errors"], norm(errors), name)
                self.assertEqual(got["warns"], norm(warns), name)
                if plain is None:
                    plain = (norm(errors), norm(warns))
                    self.assertEqual(plain[0], [], "the demonstration, in a folder of its own, has nothing to fix")
                else:
                    self.assertNotEqual((norm(errors), norm(warns)), plain, f"{name}: run_ab.py notices it")


if __name__ == "__main__":
    unittest.main()

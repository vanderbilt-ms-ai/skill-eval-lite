"""Freezing (0.1.1): the fingerprint is checked, and `run` runs only a frozen
experiment.

- A file frozen with a fingerprint that matches it reads "Frozen: yes" in
  `check` and `status`, and runs.
- A one-character edit after freezing is a "must fix" in `check`, "changed
  since it was frozen" in `status`, refused by `run`, and said in the
  wizard's step 2.
- A 0.1.0 freeze ("sha256:") reads as frozen, with a note, and runs.
- An experiment that isn't frozen is refused by `run` (held-out runs too);
  `--unfrozen` runs it, and marks the runs, the run records and the bundle
  "frozen": false, which the wizard shows in steps 3 to 5. A demonstration
  runs unfrozen without the flag (test_pipeline.py).
- `doctor` and `status` say when a newer Skill Eval Lite is out (from a file
  here, never GitHub), and nothing when it can't be read.
"""
import json
import os
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cdp import Browser, find_chrome  # noqa: E402
from helpers import EXAMPLES, FAKE, REPO, class_assistant, fake_run, run_ab, tmpdir  # noqa: E402

sys.path.insert(0, str(REPO))
import run_ab as R  # noqa: E402

CHROME = find_chrome() if os.name == "posix" else None
DATE = "2026-11-05T18:00:00.000Z"


def frozen(text: str, hash_=None) -> str:
    """The text with its [frozen] record filled in, as the wizard writes it."""
    i = text.index("[frozen]\n")
    j = text.index("\n[", i)
    return text[:i] + f'[frozen]\ndate = "{DATE}"\nhash = "{hash_ or R.fingerprint(text)}"\n' + text[j:]


class Freeze(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.chmod(FAKE, 0o755)
        cls.root = tmpdir()
        cls.assistant = class_assistant(cls.root)
        text = (EXAMPLES / "demo-graph-removed.toml").read_text(encoding="utf-8")
        text = text.replace("demo = true\n", "")
        text = text.replace('files_from = "class-assistant"', f'files_from = "{(EXAMPLES / "class-assistant").as_posix()}"')
        cls.text = text
        cls.dir = cls.root / "sel" / "experiments"
        for name, body in (("open", text), ("frozen", frozen(text)), ("changed", frozen(text).replace("repeats = 1", "repeats = 2")),
                           ("old", frozen(text, "sha256:" + "0" * 64)), ("made-up", frozen(text, "filled in by the wizard"))):
            (cls.dir / name).mkdir(parents=True)
            (cls.dir / name / "experiment.toml").write_text(body, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def exp(self, name):
        return self.dir / name / "experiment.toml"

    def test_check(self):
        r = run_ab("check", self.exp("frozen"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"Frozen: yes, {DATE}", r.stdout)
        r = run_ab("check", self.exp("changed"))
        self.assertEqual(r.returncode, 1)
        self.assertIn(f"must fix:  The file has changed since it was frozen on {DATE}. Freeze it again in the wizard, keep the "
                      "earlier file, dated, and say in your report what you changed and why.", r.stdout)
        self.assertIn("Frozen: no: it has changed since it was frozen", r.stdout)
        r = run_ab("check", self.exp("old"))
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn(f"Frozen: yes, {DATE} (frozen with 0.1.0; the fingerprint can't be checked)", r.stdout)
        r = run_ab("check", self.exp("open"))
        self.assertIn("Frozen: not yet", r.stdout)
        r = run_ab("check", self.exp("made-up"))
        self.assertIn("Frozen: not yet", r.stdout, "a hash that is no fingerprint is not a freeze")

    def test_status(self):
        r = run_ab("status", "--claude", FAKE, "--assistant", self.assistant, "--root", self.root / "sel", "--json", cwd=self.root / "sel")
        st = json.loads(r.stdout)
        state = {Path(e["file"]).parent.name: e["freeze"] for e in st["experiments"] if e["kind"] == "yours"}
        self.assertEqual(state, {"changed": "changed", "frozen": "frozen", "old": "old", "open": "unfrozen", "made-up": "unfrozen"})
        self.assertIn("has changed since it was frozen", st["next"]["what"], "changed comes first, alphabetically")
        text = run_ab("status", "--claude", FAKE, "--assistant", self.assistant, "--root", self.root / "sel", cwd=self.root / "sel").stdout
        self.assertIn("changed since it was frozen: freeze it again", text)
        self.assertIn("frozen, ready to run", text)

    def run_it(self, name, *extra):
        return fake_run(self.exp(name), self.assistant, self.root / "runs" / name, None, "--prompts", "prep-dana-checkin", *extra)

    def test_run_refuses_unless_frozen(self):
        r = self.run_it("open")
        self.assertEqual(r.returncode, 2)
        self.assertIn("isn't frozen yet, so it can't be run", r.stderr)
        self.assertFalse((self.root / "runs" / "open" / "bundle.json").exists(), "nothing ran")
        r = self.run_it("changed")
        self.assertEqual(r.returncode, 2)
        self.assertIn(f"has changed since it was frozen on {DATE}", r.stderr)
        r = fake_run(self.exp("open"), self.assistant, self.root / "runs" / "held", None, "--prompts", "reply-to-priya", "--held-out")
        self.assertEqual(r.returncode, 2, "held-out runs too")

    def test_run_frozen_and_old(self):
        for name in ("frozen", "old"):
            r = self.run_it(name)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            b = json.loads((self.root / "runs" / name / "bundle.json").read_text())
            self.assertNotIn("frozen", b)
            self.assertTrue(all("frozen" not in o for o in b["outputs"]))
            self.assertEqual(b["experiment"]["freeze"], name)

    def test_run_unfrozen_marks_the_runs(self):
        r = self.run_it("changed", "--unfrozen")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("this file has changed since it was frozen; with --unfrozen, these runs are marked", r.stdout)
        out = self.root / "runs" / "changed"
        b = json.loads((out / "bundle.json").read_text())
        self.assertIs(b["frozen"], False)
        self.assertEqual(len(b["outputs"]), 4, "two rounds, and the changed file asks for two repeats")
        self.assertTrue(all(o["frozen"] is False for o in b["outputs"]))
        rec = json.loads((out / "outputs" / "prep-dana-checkin" / "A" / "1" / "run.json").read_text())
        self.assertIs(rec["frozen"], False)
        st = R.run_folder_state(out / "bundle.json")
        self.assertEqual(st["unfrozen"], 4)
        if CHROME:
            self.wizard_shows_the_mark(out / "bundle.json")

    def wizard_shows_the_mark(self, bundle):
        b = Browser(CHROME, timeout=60)
        try:
            b.goto((REPO / "wizard.html").as_uri())
            b.js("localStorage.clear()")
            b.goto((REPO / "wizard.html").as_uri())
            b.set_files("#bundle-file", [bundle])
            b.until("document.querySelector('main').innerText.includes('Can the evaluation see the knowledge graph')")
            b.js("document.querySelectorAll('#steps button')[1].click(); true")
            self.assertTrue(b.js("!!document.getElementById('changed-since-frozen')"), "step 2 says the file changed since its freeze")
            self.assertFalse(b.js("!!document.getElementById('unfrozen-runs')"), "the mark is for steps 3 to 5")
            b.js("[...document.querySelectorAll('button')].find(x => x.textContent.startsWith('Freeze anyway')).click(); true")
            b.until("document.querySelector('main').innerText.includes('The record')")
            b.js("document.querySelectorAll('#steps button')[2].click(); true")
            self.assertIn("These runs were made before the experiment was frozen", b.js("document.getElementById('unfrozen-runs').innerText"))
            self.assertEqual(list(b.errors), [])
        finally:
            b.close()


@unittest.skipUnless(CHROME, "headless Chrome is not available")
class WizardLoads(unittest.TestCase):
    def load(self, text):
        b = Browser(CHROME, timeout=60)
        b.goto((REPO / "wizard.html").as_uri())
        b.js("localStorage.clear()")
        b.js(f"loadIntake({json.dumps(text)}, 'experiment.toml'); set({{ step: 2 }}); true")
        return b

    def test_a_frozen_file_verifies_and_a_changed_one_does_not(self):
        text = (EXAMPLES / "class-assistant" / "experiment.toml").read_text(encoding="utf-8")
        for body, frozen_, changed, note in ((frozen(text), True, False, "its fingerprint matches"),
                                             (frozen(text).replace("repeats = 2", "repeats = 3"), False, True, None),
                                             (frozen(text, "sha256:" + "0" * 64), True, False, "with Skill Eval Lite 0.1.0")):
            b = self.load(body)
            try:
                self.assertEqual(b.js("!!S.frozen"), frozen_)
                self.assertEqual(b.js("!!document.getElementById('changed-since-frozen')"), changed)
                if note:
                    self.assertIn(note, b.js("document.querySelector('main').innerText"))
                self.assertEqual(list(b.errors), [])
            finally:
                b.close()


    def test_the_export_and_the_fingerprint_agree_on_the_frozen_table(self):
        text = (EXAMPLES / "class-assistant" / "experiment.toml").read_text(encoding="utf-8")
        shapes = {"indented": text.replace("\n[frozen]\n", "\n  [frozen]\n"), "spaced": text.replace("\n[frozen]\n", "\n[ frozen ]  # the wizard's\n"),
                  "none, ending in a non-breaking space": text.replace('[frozen]\ndate = ""\nhash = ""\n', "").rstrip() + "\n# the end\u00a0\n"}
        for name, body in shapes.items():
            b = self.load(body)
            try:
                out = b.js("freeze([]); frozenText()")
                self.assertIn("frozen", __import__("tomllib").loads(out), name)
                self.assertEqual(__import__("tomllib").loads(out)["frozen"]["hash"], R.fingerprint(out), name)
                self.assertEqual(R.design_text(out), R.design_text(body), name)
            finally:
                b.close()


class NewerVersion(unittest.TestCase):
    def test_doctor_and_status_say_so(self):
        root = tmpdir()
        try:
            (root / "VERSION").write_text("9.0.0\n")
            env = {"SKILL_EVAL_LITE_UPDATE_URL": (root / "VERSION").as_uri()}
            r = run_ab("doctor", "--claude", FAKE, "--no-probe", env=env)
            self.assertIn(f"Skill Eval Lite 9.0.0 is out; you have {R.VERSION}. In this folder, run git pull.", r.stdout)
            r = run_ab("status", "--claude", FAKE, "--root", root, env=env, cwd=root)
            self.assertIn("Skill Eval Lite 9.0.0 is out", r.stdout)
            r = run_ab("status", "--claude", FAKE, "--root", root, "--json", env=env, cwd=root)
            self.assertEqual(json.loads(r.stdout)["update"], "9.0.0")
            (root / "VERSION").write_text(R.VERSION + "\n")
            self.assertNotIn("is out", run_ab("status", "--claude", FAKE, "--root", root, env=env, cwd=root).stdout)
            env = {"SKILL_EVAL_LITE_UPDATE_URL": (root / "nowhere").as_uri()}
            self.assertNotIn("is out", run_ab("doctor", "--claude", FAKE, "--no-probe", env=env).stdout, "offline: nothing")
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

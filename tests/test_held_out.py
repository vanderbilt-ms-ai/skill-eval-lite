"""The held-out confirmation (Shared I's fourth step: "unseal the held-out
prompts, run A and your final version on them, judge them blind as before"):
which rounds are paired on the held-out prompts, and `judge --held-out`
judging that pair even when the frozen file lists no comparison for it."""
import json
import os
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import FAKE, REPO, class_assistant, fake_run, held_out_experiment, run_ab, tmpdir  # noqa: E402

sys.path.insert(0, str(REPO))
import run_ab as R  # noqa: E402


class Confirmation(unittest.TestCase):
    def setUp(self):
        self.root = tmpdir()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def exp(self, **kw):
        return R.Experiment(held_out_experiment(self.root, **kw))

    def test_sealed_until_the_baseline_runs_on_them(self):
        exp = self.exp(drop_rounds=("C",))
        dev = {("reply-to-priya", r, 1): {} for r in "ABD"}
        self.assertEqual(R.held_out_comparisons(exp, dev), [], "nothing held out has run")
        only_new = {**dev, ("ellis-board-note", "D", 1): {}}
        self.assertEqual(R.held_out_comparisons(exp, only_new), [], "the baseline hasn't run on them")

    def test_the_baseline_against_each_round_run_on_them(self):
        exp = self.exp(drop_rounds=("C",))
        outputs = {(p, r, 1): {} for p in ("ellis-board-note", "reply-to-school") for r in "AD"}
        self.assertEqual(R.held_out_comparisons(exp, outputs), [{"baseline": "A", "new": "D"}],
                         "A against the final version, though the file compares only A and B")
        outputs.update({("ellis-board-note", "B", 1): {}})
        self.assertEqual(R.held_out_comparisons(exp, outputs), [{"baseline": "A", "new": "B"}, {"baseline": "A", "new": "D"}])

    def test_the_baseline_without_a_role(self):
        exp = self.exp(drop_rounds=("C", "D"))
        exp.rounds["A"]["role"] = "improvement"
        self.assertEqual(R.baseline_round(exp), "A", "the first comparison's baseline")


class JudgeHeldOut(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.chmod(FAKE, 0o755)
        cls.root = tmpdir()
        cls.assistant = class_assistant(cls.root)
        # Rounds A, B and D; the file compares only A and B. D stands in for the
        # group's final version, run on the held-out prompts with A.
        cls.exp = held_out_experiment(cls.root, comparisons=(("A", "B"),), drop_rounds=("C",))
        cls.out = cls.root / "runs" / "held"
        r = fake_run(cls.exp, cls.assistant, cls.out, None, "--rounds", "A,B")
        assert r.returncode == 0, r.stdout + r.stderr

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def bundle(self):
        return json.loads((self.out / "bundle.json").read_text(encoding="utf-8"))

    def test_sealed_then_confirmed(self):
        j = run_ab("judge", self.out, "--claude", FAKE)
        self.assertEqual(j.returncode, 0, j.stdout + j.stderr)
        self.assertEqual({(v["comparison"], v["prompt"]) for v in self.bundle()["judge"]},
                         {("A|B", "reply-to-priya"), ("A|B", "summarize-committee-notes")}, "development pairs only")
        r = fake_run(self.exp, self.assistant, self.out, None, "--rounds", "A,D", "--held-out")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        j = run_ab("judge", self.out, "--claude", FAKE)
        self.assertIn("already judged", j.stdout, "without --held-out the held-out pairs stay unjudged")
        j = run_ab("judge", self.out, "--held-out", "--comparisons", "A-D", "--claude", FAKE)
        self.assertEqual(j.returncode, 0, j.stdout + j.stderr)
        held = [v for v in self.bundle()["judge"] if v["prompt"] in ("ellis-board-note", "reply-to-school")]
        self.assertEqual(sorted((v["comparison"], v["prompt"]) for v in held),
                         [("A|D", "ellis-board-note"), ("A|D", "reply-to-school")],
                         "A against the final version on each held-out prompt, though the file lists no A-D comparison")
        self.assertTrue((self.out / "judge" / "A-D" / "ellis-board-note__1.json").is_file())
        self.assertEqual(len([v for v in self.bundle()["judge"] if v["comparison"] == "A|D"]), 2,
                         "the development prompts aren't judged as A against D")


if __name__ == "__main__":
    unittest.main()

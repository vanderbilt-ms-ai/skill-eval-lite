"""`status`, `new` and `ask`, offline: status reads the setup, the assistant,
the experiments and the runs and names the one next step, with the skill that
does it in Claude (`skill`, 0.2.0) beside its command; `new` copies the
class experiment for a group; `ask` builds the right command for Claude Code
and Codex (nothing is launched), with the helper's instructions and the
status, permission prompts left on, and nothing of the person's loaded."""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import EXAMPLES, FAKE, FAKE_CODEX, REPO, class_assistant, fake_codex_env, fake_run, run_ab, tmpdir

sys.path.insert(0, str(REPO))
import run_ab as R  # noqa: E402

POSIX = os.name == "posix"


@unittest.skipUnless(POSIX, "the fakes are POSIX scripts")
class Status(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for f in (FAKE, FAKE_CODEX):
            os.chmod(f, 0o755)
        cls.root = tmpdir()
        cls.work = cls.root / "sel"
        cls.work.mkdir()
        cls.assistant = class_assistant(cls.root)
        cls.env = fake_codex_env(cls.root)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def status(self, *extra, env=None, json_out=True):
        args = ["status", "--claude", FAKE, "--codex", FAKE_CODEX, "--root", self.work, *extra]
        r = run_ab(*args, *(["--json"] if json_out else []), env={**self.env, **(env or {})}, cwd=self.work)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout) if json_out else r.stdout

    def test_1_no_assistant_yet(self):
        st = self.status("--assistant", self.root / "nowhere")
        self.assertEqual(st["schema"], "skill-eval-lite/status@1")
        self.assertTrue(st["setup"]["claude_code"]["logged_in"])
        self.assertEqual(st["setup"]["runner"], "claude-code")
        self.assertFalse(st["assistant"]["exists"])
        self.assertIn("run_ab.py setup ../class-assistant", st["next"]["command"])
        self.assertEqual(st["next"]["skill"], "/get-ready", "0.2.0: the skill that does it in Claude, beside the command")
        self.assertIn("OPENAI_API_KEY", st["setup"]["api_keys_set"], "names only")
        self.assertNotIn("fake-openai-key", json.dumps(st))

    def test_2_not_logged_in(self):
        st = self.status("--assistant", self.assistant, env={"FAKE_CLAUDE_LOGGED_OUT": "1", "FAKE_CODEX_LOGGED_OUT": "1"})
        self.assertEqual(st["next"]["command"], "claude auth login", "0.2.0: signing in, not a session to exit")
        self.assertEqual(st["next"]["skill"], "/get-ready")
        st = self.status("--assistant", self.assistant, "--runner", "codex", env={"FAKE_CODEX_LOGGED_OUT": "1"})
        self.assertEqual(st["next"]["command"], "codex login")
        self.assertIsNone(st["next"]["skill"], "the skills are Claude's: with Codex, the command alone")

    def test_3_first_demonstration_then_judge_then_wizard(self):
        st = self.status("--assistant", self.assistant)
        self.assertTrue(st["assistant"]["claude_md"] and st["assistant"]["git"])
        self.assertEqual(st["runs"], [])
        self.assertIn("run examples/demo-one-line.toml --assistant", st["next"]["command"])
        self.assertEqual(st["next"]["skill"], "/skill-eval-helper", "the helper's steps run the demonstrations, which aren't frozen")
        self.assertNotIn("--runner codex", st["next"]["command"])
        codex = self.status("--assistant", self.assistant, "--runner", "codex")["next"]
        self.assertIn("--runner codex", codex["command"])
        self.assertIsNone(codex["skill"])
        names = {e["file"]: e for e in st["experiments"]}
        self.assertEqual(names["examples/demo-graph-removed.toml"]["kind"], "demonstration")
        self.assertEqual(names["examples/class-assistant/experiment.toml"]["errors"], [])
        r = fake_run(EXAMPLES / "demo-graph-removed.toml", self.assistant, self.work / "runs" / "demo-graph-removed")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        st = self.status("--assistant", self.assistant)
        run = st["runs"][0]
        self.assertEqual((run["runner"], run["ok"], run["runs"], run["pairs"], run["judged"]), ("claude-code", 4, 4, 2, 0))
        self.assertIn("judge", st["next"]["command"])
        self.assertIn("runs/demo-graph-removed", st["next"]["command"])
        self.assertEqual(st["next"]["skill"], "/skill-eval-helper")
        run_ab("judge", self.work / "runs" / "demo-graph-removed", "--claude", FAKE)
        st = self.status("--assistant", self.assistant)
        self.assertEqual(st["runs"][0]["judged"], 2)
        self.assertIn("wizard.html", st["next"]["command"])
        self.assertEqual(st["next"]["skill"], "/wizard")
        self.assertIn("new <name> --from class", st["next"]["what"])
        self.assertIn("In Claude, type /shared-i (in a terminal: python3 run_ab.py new <name> --from class)", st["next"]["what"])
        text = self.status("--assistant", self.assistant, json_out=False)
        for line in ("Your setup", "The assistant", "Experiments", "Runs", "Next step", "4 of 4 finished; judge: 2 of 2 pairs",
                     "      In Claude, type /wizard\n      (in a terminal: " + R.OPEN_WIZARD + ")"):
            self.assertIn(line, text)

    def test_4_new_from_class_and_freeze(self):
        r = run_ab("new", "board-memo", "--from", "class", "--root", self.work, cwd=self.work)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        d = self.work / "experiments" / "board-memo"
        self.assertTrue((d / "experiment.toml").is_file())
        self.assertTrue((d / "rounds" / "B" / ".claude" / "identity" / "voice.md").is_file())
        self.assertTrue((d / "prompts" / "reply-to-priya" / "files").is_dir())
        self.assertIn("run_ab.py check experiments/board-memo/experiment.toml", r.stdout)
        self.assertEqual(run_ab("check", d / "experiment.toml").returncode, 0)
        st = self.status("--assistant", self.assistant)
        mine = [e for e in st["experiments"] if e["kind"] == "yours"]
        self.assertEqual(len(mine), 1)
        self.assertIn("Freeze it in the wizard: load it in step 1, press Freeze in step 2, then press 'Export the frozen "
                      "experiment' (now in step 2) and save the file over experiments/board-memo/experiment.toml.", st["next"]["what"])
        self.assertEqual(st["next"]["skill"], "/wizard")
        again = run_ab("new", "board-memo", "--from", "class", "--root", self.work, cwd=self.work)
        self.assertEqual(again.returncode, 2)
        self.assertIn("not empty", again.stderr)

    def test_new_from_a_demonstration_and_without_from(self):
        r = run_ab("new", "graph", "--from", EXAMPLES / "demo-graph-removed.toml", "--root", self.work, cwd=self.work)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = (self.work / "experiments" / "graph" / "experiment.toml").read_text()
        self.assertNotIn("files_from", text, "the round and prompt files now sit beside it")
        self.assertEqual(run_ab("check", self.work / "experiments" / "graph" / "experiment.toml").returncode, 0)
        r = run_ab("new", "mine", "--root", self.work, cwd=self.work)
        self.assertEqual(r.returncode, 0)
        self.assertIn("/experiment-intake", r.stdout)
        self.assertFalse((self.work / "experiments" / "mine").exists())
        bad = run_ab("new", "My Experiment", "--from", "class", "--root", self.work, cwd=self.work)
        self.assertEqual(bad.returncode, 2)


@unittest.skipUnless(POSIX, "the fakes are POSIX scripts")
class Projects(unittest.TestCase):
    """0.1.3: status follows a Personal I packet (fix 1), and says who pays for a run (fix 2)."""

    @classmethod
    def setUpClass(cls):
        os.chmod(FAKE, 0o755)
        cls.base = tmpdir()
        cls.assistant = class_assistant(cls.base)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(dir=self.base))
        self.work = self.root / "sel"
        self.work.mkdir()

    def packet(self) -> Path:
        shutil.copytree(EXAMPLES / "personal-suites", self.root / "my-suites")
        return self.root / "my-suites" / "suites.yaml"

    def status(self, *extra, assistant=None, env=None, text=False):
        r = run_ab("status", "--claude", FAKE, "--codex", self.root / "no-codex", "--root", self.work,
                   "--assistant", assistant or self.root / "no-wren", *extra, *([] if text else ["--json"]),
                   env=env, cwd=self.work)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout if text else json.loads(r.stdout)

    def test_a_packet_not_run_yet(self):
        self.packet()
        st = self.status()
        self.assertEqual(st["next"]["command"], "python3 run_ab.py suite ../my-suites/suites.yaml --no-llm",
                         "0.2.0: the mechanical tests first, then the student's reference, then the LLM tests")
        self.assertEqual(st["next"]["skill"], "/run-suites")
        self.assertEqual(st["next"]["project"], "personal")
        self.assertIn("they call no model", st["next"]["what"])
        self.assertEqual([s["project"] for s in st["next_steps"]], ["personal"], "Wren is not asked for")
        text = self.status(text=True)
        self.assertIn("no-wren: not set up yet (Shared I and the demonstrations need it; Personal I's suites don't)", text)
        self.assertNotIn("run_ab.py setup", text)

    def test_a_broken_packet(self):
        f = self.packet()
        shutil.rmtree(f.parent / "product" / "note-2")
        st = self.status()
        self.assertEqual(st["next"]["command"], "python3 run_ab.py suite ../my-suites/suites.yaml --check")
        self.assertIn("has 1 thing(s) to fix", st["next"]["what"])
        self.assertIn("1 thing(s) to fix", self.status(text=True))

    def test_a_packet_run_then_judged_then_changed(self):
        f = self.packet()
        r = run_ab("suite", f, "--claude", FAKE)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        st = self.status()
        self.assertEqual(st["next"]["command"], R.OPEN_WIZARD)
        self.assertIn("load ../my-suites/bundle.json in step 1. Judge each LLM test's criterion yourself (Reference)", st["next"]["what"])
        with open(f.parent / "judgments.csv", "a", encoding="utf-8") as fh:
            fh.write("reference,,product,facts-match-the-source-reference,human,SL,x,pass,mine,,2030-01-01T00:00:00Z\n")
        st = self.status()
        self.assertIn("In the wizard's Report step, export judgments.csv into ../my-suites/", st["next"]["what"])
        time.sleep(0.05)
        p = f.parent / "tests" / "facts-match-the-source" / "prompt.md"
        p.write_text(p.read_text() + "\nOne more rule.\n")
        st = self.status()
        self.assertEqual(st["next"]["command"], "python3 run_ab.py suite ../my-suites/suites.yaml")
        self.assertIn("1 test(s) have changed since the last run", st["next"]["what"])

    def test_the_reference_comes_before_the_llm_tests(self):
        """0.2.0: `suite` prints each LLM test's verdict as it runs, so status
        puts the mechanical tests first, then the student's own reference in
        the wizard, then the LLM tests."""
        f = self.packet()
        r = run_ab("suite", f, "--no-llm", "--claude", FAKE)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        st = self.status()
        self.assertEqual(st["next"]["command"], R.OPEN_WIZARD)
        self.assertEqual(st["next"]["skill"], "/wizard")
        self.assertIn("Before the LLM tests run, open the wizard and load ../my-suites/bundle.json in step 1", st["next"]["what"])
        self.assertIn("each LLM test run uses a little of your plan", st["next"]["what"])
        with open(f.parent / "judgments.csv", "a", encoding="utf-8") as fh:
            fh.write("reference,,product,facts-match-the-source-reference,human,SL,x,pass,mine,,2030-01-01T00:00:00Z\n")
        st = self.status()
        self.assertEqual(st["next"]["command"], "python3 run_ab.py suite ../my-suites/suites.yaml")
        self.assertIn("have no results yet", st["next"]["what"])
        self.assertEqual(run_ab("suite", f, "--claude", FAKE).returncode, 0)
        self.assertIn("In the wizard's Report step, export judgments.csv into ../my-suites/", self.status()["next"]["what"])

    def test_a_packet_and_an_experiment(self):
        self.packet()
        self.assertEqual(run_ab("new", "mine", "--from", "class", "--root", self.work, cwd=self.work).returncode, 0)
        st = self.status(assistant=self.assistant)
        self.assertEqual([s["project"] for s in st["next_steps"]], ["shared", "personal"])
        self.assertEqual(st["next"], st["next_steps"][0], "next is still the first step, for ask and scripts")
        self.assertIn("freeze", st["next_steps"][0]["what"].lower())
        self.assertEqual(st["next_steps"][1]["command"], "python3 run_ab.py suite ../my-suites/suites.yaml --no-llm")
        text = self.status(assistant=self.assistant, text=True)
        self.assertIn("Next step, Shared I", text)
        self.assertIn("Next step, Personal I", text)

    def test_neither(self):
        st = self.status()
        self.assertEqual(st["next"]["command"], "python3 run_ab.py setup ../class-assistant")
        self.assertIn("On Personal I? You don't need Wren. Make your packet, or start from a copy of the worked example. "
                      "In Claude, type /personal-i (in a terminal: cp -r examples/personal-suites ../my-suites).",
                      self.status(text=True))

    def test_the_project_forced(self):
        self.packet()
        st = self.status("--project", "shared")
        self.assertEqual(st["next"]["command"], "python3 run_ab.py setup ../class-assistant")
        self.assertEqual([s["project"] for s in st["next_steps"]], ["shared"])
        shutil.rmtree(self.root / "my-suites")
        st = self.status("--project", "personal")
        self.assertEqual(st["next"]["command"], "cp -r examples/personal-suites ../my-suites")
        self.assertEqual(st["next"]["skill"], "/personal-i")
        ask = run_ab("ask", "--claude", FAKE, "--root", self.work, "--assistant", self.root / "no-wren", "--project", "personal",
                     "--show-command", cwd=self.work)
        self.assertEqual(ask.returncode, 0, ask.stdout + ask.stderr)
        self.assertIn("cp -r examples/personal-suites ../my-suites", ask.stdout, "ask passes the project on to the status it gives")

    def test_who_pays(self):
        plan = self.status(assistant=self.assistant)
        self.assertIn("about half a minute; each run uses a little of your plan", plan["next"]["what"])
        key = self.status(assistant=self.assistant, env={"FAKE_CLAUDE_AUTH": "api_key"})
        self.assertIn("about half a minute; each run is billed to your API key", key["next"]["what"])
        text = self.status(assistant=self.assistant, env={"FAKE_CLAUDE_AUTH": "api_key"}, text=True)
        self.assertIn("logged in (api_key): runs are billed to the key", text)
        f = self.packet()
        self.assertEqual(run_ab("suite", f, "--no-llm", "--claude", FAKE).returncode, 0, "the first step calls no model")
        self.assertIn("each LLM test run is billed to your API key", self.status(env={"FAKE_CLAUDE_AUTH": "api_key"})["next"]["what"])


@unittest.skipUnless(POSIX, "the fakes are POSIX scripts")
class Ask(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for f in (FAKE, FAKE_CODEX):
            os.chmod(f, 0o755)
        cls.root = tmpdir()
        cls.env = fake_codex_env(cls.root)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def show(self, *extra):
        r = run_ab("ask", "--claude", FAKE, "--codex", FAKE_CODEX, "--root", self.root, "--assistant", self.root / "none",
                   "--show-command", *extra, env=self.env, cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def test_helper_files_agree(self):
        skill = (REPO / ".claude/skills/skill-eval-helper/SKILL.md").read_text()
        helper = (REPO / "HELPER.md").read_text()
        self.assertTrue(skill.startswith("---\nname: skill-eval-helper\n"))
        self.assertTrue(helper.endswith(skill.split("---\n", 2)[2].lstrip("\n")), "HELPER.md is SKILL.md without its front matter")
        self.assertIn("skill-eval-lite helper", helper[:400], "the runner leaves HELPER.md out of a run by this mark")
        self.assertIn("/experiment-intake", helper, "the helper hands over to the intake")

    def test_claude_interactive(self):
        c = self.show("--runner", "claude-code")
        argv = c["argv"]
        self.assertEqual(Path(c["cwd"]), REPO)
        for flag in ("--setting-sources", "--strict-mcp-config", "--settings", "--append-system-prompt"):
            self.assertIn(flag, argv)
        self.assertIn("disableClaudeAiConnectors", argv[argv.index("--settings") + 1])
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "project")
        prompt = argv[argv.index("--append-system-prompt") + 1]
        self.assertIn("Helping a student use Skill Eval Lite", prompt)
        self.assertIn("Where the student is now", prompt)
        self.assertIn("Next step", prompt, "the status is in the prompt")
        for flag in ("-p", "--permission-prompts", "--dangerously-skip-permissions"):
            self.assertNotIn(flag, argv, "an interactive helper keeps its permission prompts")
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "manual", "it asks before every command, whatever the default")
        self.assertEqual(argv[-1], "Hello! Please help me with Skill Eval Lite.")
        self.assertEqual(c["env"]["ENABLE_CLAUDEAI_MCP_SERVERS"], "false")
        self.assertIsNone(c["stdin"])

    def test_claude_once(self):
        c = self.show("--runner", "claude-code", "how", "do", "I", "freeze", "my", "experiment?")
        argv = c["argv"]
        self.assertIn("-p", argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Glob,Grep", "a one-shot answer only reads")
        self.assertEqual(c["stdin"], "how do I freeze my experiment?\n")
        self.assertIn("answer it once", argv[argv.index("--append-system-prompt") + 1].lower())

    def test_codex_interactive(self):
        c = self.show("--runner", "codex")
        self.assertEqual(c["argv"][1:], ["Hello! Please help me with Skill Eval Lite."])
        self.assertIn("codex-home-", c["env"]["CODEX_HOME"])
        self.assertNotIn("OPENAI_API_KEY", c["env_names"])
        cfg = c["config"]
        for line in ('approval_policy = "on-request"', 'sandbox_mode = "workspace-write"', "network_access = false",
                     "apps = false", "plugins = false", "memories = false", 'web_search = "disabled"'):
            self.assertIn(line, cfg)
        self.assertIn("Helping a student use Skill Eval Lite", json.loads(cfg.split("developer_instructions = ", 1)[1].split("\n")[0]))
        self.assertNotIn("mcp_servers", cfg)
        self.assertFalse(Path(c["env"]["CODEX_HOME"]).exists(), "the helper's temporary Codex home is deleted")

    def test_codex_once(self):
        c = self.show("--runner", "codex", "what next?")
        self.assertEqual(c["argv"][1:3], ["exec", "--json"])
        self.assertIn('sandbox_mode = "read-only"', c["config"])
        self.assertIn('approval_policy = "never"', c["config"])
        r = run_ab("ask", "--runner", "codex", "--codex", FAKE_CODEX, "--root", self.root, "--assistant", self.root / "none",
                   "what", "next?", env=self.env, cwd=self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Draft for:", r.stdout, "the fake's answer is printed")


if __name__ == "__main__":
    unittest.main()

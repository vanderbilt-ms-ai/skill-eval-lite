"""The Codex runner, offline, with the fake `codex` (tests/fake_codex.py): runs,
the judge, a suite's LLM tests and doctor; what reaches Codex (a temporary
CODEX_HOME with only the runner's config and a link to the login, no API key
unless asked); the assistant mapped to AGENTS.md and .agents/skills; a run
stopped when something of the person's loads; runners not mixed; and the
pieces (imports, the trace, the check before each run) on their own."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import EXAMPLES, FAKE, FAKE_CODEX, REPO, class_assistant, fake_codex_env, fake_codex_run, fake_run, run_ab, tmpdir

sys.path.insert(0, str(REPO))
import run_ab as R  # noqa: E402

POSIX = os.name == "posix"


def log_lines(root: Path) -> list[dict]:
    p = root / "codex-log.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


@unittest.skipUnless(POSIX, "the fake codex is a POSIX script")
class CodexPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.chmod(FAKE_CODEX, 0o755)
        cls.root = tmpdir()
        cls.assistant = class_assistant(cls.root)
        cls.out = cls.root / "runs" / "graph-codex"
        cls.env = fake_codex_env(cls.root)
        cls.r = fake_codex_run(EXAMPLES / "demo-graph-removed.toml", cls.assistant, cls.out, cls.env)
        cls.j = run_ab("judge", cls.out, "--codex", FAKE_CODEX, env=cls.env)
        cls.bundle = json.loads((cls.out / "bundle.json").read_text())
        cls.log = log_lines(cls.root)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def test_runs(self):
        self.assertEqual(self.r.returncode, 0, self.r.stdout + self.r.stderr)
        outs = {(o["prompt"], o["round"]): o for o in self.bundle["outputs"]}
        self.assertEqual(len(outs), 4)
        self.assertTrue(all(o["status"] == "ok" and o["runner"] == "codex" for o in outs.values()))
        a, c = outs[("prep-dana-checkin", "A")], outs[("prep-dana-checkin", "C")]
        self.assertIn("120,000", a["output"])
        self.assertNotIn("120,000", c["output"])
        self.assertIn(["Bash", "kb/kb search Dana"], a["trace"])
        self.assertIn(["Bash", "kb/kb search Dana", "error"], c["trace"])
        self.assertIn(["Skill", "knowledge-graph"], a["trace"], "reading a SKILL.md under .agents/skills is a Skill step")
        self.assertIn(["ListMcpResources", "{}"], a["trace"], "Codex's own resource tool is named, not stopped")
        self.assertTrue(any(s[0] == "Write" and s[1].startswith("notes/") for s in a["trace"]))
        self.assertIn("usage", a)
        self.assertIsNone(a["cost_usd"])
        self.assertEqual(self.bundle["runner"]["name"], "codex")
        self.assertIn('approval_policy = "never"', self.bundle["runner"]["config_toml"])
        self.assertIn("Codex", self.r.stdout)

    def test_the_assistant_as_codex_reads_it(self):
        outs = {(o["prompt"], o["round"]): o for o in self.bundle["outputs"]}
        self.assertIn("Voice inlined: yes", outs[("prep-dana-checkin", "A")]["output"], "CLAUDE.md's @ import is inlined into AGENTS.md")
        run = json.loads((self.out / "outputs/prep-dana-checkin/A/1/run.json").read_text())
        m = run["codex_mapping"]
        self.assertIn(".claude/identity/voice.md", m["imports"])
        self.assertIn("knowledge-graph", m["skills"])
        self.assertIn("not interchangeable", m["note"])
        self.assertEqual(run["runner"], "codex")
        self.assertEqual(run["codex_version"], "0.164.0")
        self.assertEqual(run["model"], R.CODEX_DEFAULT_MODEL, "a Claude model in the experiment is not passed to Codex")
        self.assertEqual(run["command"][:2], ["codex", "exec"])
        for flag in ("--json", "--ephemeral", "--skip-git-repo-check"):
            self.assertIn(flag, run["command"])
        self.assertTrue(run["isolation"]["verified"])
        self.assertEqual(run["isolation"]["skills"], ["knowledge-graph", "knowledge-graph-maintain"])
        self.assertEqual(run["isolation"]["instructions"], ["AGENTS.md in the run's folder"])
        c = json.loads((self.out / "outputs/prep-dana-checkin/C/1/run.json").read_text())
        self.assertEqual(c["codex_mapping"]["skills"], [], "round C's removed skills are not mapped")
        self.assertEqual(c["written"], ["notes/my-check-in-with-dana-is-wedne.md"], "AGENTS.md and .agents/ are not outputs")

    def test_what_reaches_codex(self):
        execs = [l for l in self.log if l["args"][:1] == ["exec"] or "exec" in l["args"][:1]]
        execs = [l for l in self.log if l.get("prompt_start") is not None]
        self.assertTrue(execs)
        for l in execs:
            self.assertNotIn("OPENAI_API_KEY", l["env"], "the API key is left out by default")
            self.assertFalse([k for k in l["env"] if k.startswith("CODEX_") and k != "CODEX_HOME"])
            self.assertTrue(l["auth_is_link"], "the login is a link, not a copy")
            self.assertEqual(Path(l["auth_target"]), Path(self.env["CODEX_HOME"]) / "auth.json")
            self.assertEqual(set(l["home_entries"]) - {"skills", "tmp"}, {"auth.json", "config.toml"})
            self.assertNotIn("my-codex", l["cwd"])
            self.assertIn('default_permissions = "skill-eval-lite"', l["config"])
            self.assertIn('":workspace_roots" = "write"', l["config"])
            self.assertIn("apps = false", l["config"])
            self.assertNotIn("mcp_servers", l["config"])
        homes = list((self.root / "cache" / "skill-eval-lite").glob("codex-home-*"))
        self.assertEqual(homes, [], "the temporary CODEX_HOME is deleted")

    def test_nothing_personal_saved(self):
        home = str(Path.home())
        for p in self.out.rglob("*"):
            if p.is_file():
                text = p.read_text(encoding="utf-8", errors="replace")
                self.assertNotIn("FAKE-LOGIN-TOKEN", text, p)
                self.assertNotIn("fake-openai-key", text, p)
                self.assertNotIn("codex-home-", text, p)
                self.assertNotIn(home + "/", text, p)
                self.assertNotIn("MY GLOBAL INSTRUCTIONS", text, p)
                self.assertIsNone(re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text), p)

    def test_judge(self):
        self.assertEqual(self.j.returncode, 0, self.j.stdout + self.j.stderr)
        verdicts = self.bundle["judge"]
        self.assertEqual(len(verdicts), 2)
        self.assertTrue(all(v["winner"] == "A" and v["runner"] == "codex" for v in verdicts))
        saved = json.loads(next((self.out / "judge" / "A-C").glob("*.json")).read_text())
        self.assertIn("--disable", saved["command"])
        self.assertIn("shell_tool", saved["command"], "the judge has no shell")

    def test_mixing_runners_is_refused(self):
        r = fake_run(EXAMPLES / "demo-graph-removed.toml", self.assistant, self.out)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("made with Codex", r.stderr)
        mixed = self.root / "mixed"
        shutil.copytree(self.out, mixed)
        b = json.loads((mixed / "bundle.json").read_text())
        b["outputs"][0]["runner"] = "claude-code"
        (mixed / "bundle.json").write_text(json.dumps(b))
        j = run_ab("judge", mixed, "--codex", FAKE_CODEX, "--again", env=self.env)
        self.assertEqual(j.returncode, 2)
        self.assertIn("mixes runs", j.stderr)

    def test_default_folder_for_another_runner(self):
        r = run_ab("plan", EXAMPLES / "demo-graph-removed.toml", "--runner", "codex")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("codex exec --json --ephemeral --skip-git-repo-check -m " + R.CODEX_DEFAULT_MODEL, r.stdout)


@unittest.skipUnless(POSIX, "the fake codex is a POSIX script")
class CodexIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.chmod(FAKE_CODEX, 0o755)
        cls.root = tmpdir()
        cls.assistant = class_assistant(cls.root)
        text = (EXAMPLES / "demo-graph-removed.toml").read_text()
        text = text.replace("timeout_seconds = 300", "timeout_seconds = 4")
        text = text.replace('files_from = "class-assistant"', f'files_from = "{(EXAMPLES / "class-assistant").as_posix()}"')
        cls.exp = cls.root / "short.toml"
        cls.exp.write_text(text)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def stopped(self, name, **env):
        out = self.root / "runs" / name
        r = fake_codex_run(self.exp, self.assistant, out, fake_codex_env(self.root, **env), "--jobs", "1")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("STOPPED", r.stderr)
        b = json.loads((out / "bundle.json").read_text())
        self.assertEqual(len(b["outputs"]), 1, "no run starts after a breach")
        return r, b

    def test_stops_on_a_global_agents_md(self):
        r, b = self.stopped("agents", FAKE_CODEX_LEAK="agents")
        self.assertIn("outside the run's folder", r.stderr)

    def test_stops_on_a_personal_skill(self):
        r, b = self.stopped("skill", FAKE_CODEX_LEAK="skill")
        self.assertIn("leaked-skill", r.stderr)

    def test_stops_on_an_mcp_tool(self):
        r, b = self.stopped("mcp", FAKE_CODEX_LEAK="mcp")
        self.assertIn("mcp__gmail__send_message", r.stderr)

    def test_stops_on_an_mcp_call(self):
        r, b = self.stopped("call", FAKE_CODEX_MCP_CALL="1")
        self.assertIn("gmail/send_message", r.stderr)

    def test_personal_skills_in_home_are_switched_off(self):
        home = self.root / "fakehome"
        (home / ".agents" / "skills" / "mine").mkdir(parents=True, exist_ok=True)
        (home / ".agents" / "skills" / "mine" / "SKILL.md").write_text("---\nname: mine\ndescription: a personal skill\n---\n")
        out = self.root / "runs" / "homeskill"
        r = fake_codex_run(self.exp, self.assistant, out, fake_codex_env(self.root, HOME=str(home)), "--prompts", "prep-dana-checkin",
                           "--rounds", "A")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        run = json.loads((out / "outputs/prep-dana-checkin/A/1/run.json").read_text())
        self.assertNotIn("mine", run["isolation"]["skills"])
        self.assertTrue(run["isolation"]["verified"])

    def test_api_key_only_when_asked(self):
        root = self.root / "key"
        root.mkdir()
        out = root / "runs"
        r = fake_codex_run(self.exp, self.assistant, out, fake_codex_env(root), "--use-api-key", "--prompts", "prep-dana-checkin",
                           "--rounds", "A")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        execs = [l for l in log_lines(root) if l.get("prompt_start") is not None]
        self.assertIn("OPENAI_API_KEY", execs[0]["env"])
        self.assertIn("CODEX_API_KEY", execs[0]["env"])
        self.assertNotIn("auth.json", execs[0]["home_entries"], "with an API key the plan's login is not linked")

    def test_not_logged_in(self):
        r = fake_codex_run(self.exp, self.assistant, self.root / "runs" / "login", fake_codex_env(self.root, FAKE_CODEX_LOGGED_OUT="1"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("codex login", r.stderr)
        d = run_ab("doctor", "--runner", "codex", "--codex", FAKE_CODEX, env=fake_codex_env(self.root, FAKE_CODEX_LOGGED_OUT="1"))
        self.assertEqual(d.returncode, 1)
        self.assertIn("not logged in", d.stdout)

    def test_timeout_and_failure_are_kept(self):
        out = self.root / "runs" / "t"
        r = fake_codex_run(self.exp, self.assistant, out, fake_codex_env(self.root, FAKE_CODEX_HANG="Dana", FAKE_CODEX_FAIL="Priya"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        st = {(o["prompt"], o["round"]): o["status"] for o in json.loads((out / "bundle.json").read_text())["outputs"]}
        self.assertEqual(st[("prep-dana-checkin", "A")], "timeout")
        self.assertEqual(st[("prep-priya-call", "C")], "failed")

    def test_doctor(self):
        d = run_ab("doctor", "--runner", "codex", "--codex", FAKE_CODEX, env=fake_codex_env(self.root))
        self.assertEqual(d.returncode, 0, d.stdout + d.stderr)
        for line in ("Codex: 0.164.0", "Login: logged in with your ChatGPT plan", "OPENAI_API_KEY is set, but runs leave it out",
                     "Isolation: nothing of yours loaded", "MCP servers: 0 configured", "probe-skill found",
                     "The assistant's CLAUDE.md loads (as AGENTS.md, imports inlined): yes",
                     "Your home folder: hidden from runs", "Session saved: no"):
            self.assertIn(line, d.stdout)
        bad = run_ab("doctor", "--runner", "codex", "--codex", FAKE_CODEX, env=fake_codex_env(self.root, FAKE_CODEX_HOME_READABLE="1"))
        self.assertEqual(bad.returncode, 1)
        self.assertIn("a run could read a file in it", bad.stdout)


@unittest.skipUnless(POSIX, "the fake codex is a POSIX script")
class CodexSuite(unittest.TestCase):
    def test_suite_llm_tests_on_codex(self):
        os.chmod(FAKE_CODEX, 0o755)
        root = tmpdir()
        try:
            out = root / "packet"
            r = run_ab("suite", EXAMPLES / "personal-suites" / "suites.yaml", "--out", out, "--runner", "codex",
                       "--codex", FAKE_CODEX, env=fake_codex_env(root))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("with Codex", r.stdout)
            import csv
            with open(out / "judgments.csv", newline="") as fh:
                rows = list(csv.DictReader(fh))
            by = {(x["item"], x["check"]): x for x in rows}
            self.assertEqual(by[("fault-wrong-date", "facts-match-the-source")]["result"], "fail")
            self.assertEqual(by[("reference", "steps-follow")]["result"], "pass")
            rec = json.loads(next((out / "tests" / "steps-follow" / "runs").glob("*.json")).read_text())
            self.assertEqual(rec["runner"], "codex")
            self.assertEqual(rec["command"][:2], ["codex", "exec"])
            self.assertIn("shell_tool", rec["command"], "a prompt test has no shell")
        finally:
            shutil.rmtree(root, ignore_errors=True)


class Pieces(unittest.TestCase):
    def test_inline_imports(self):
        root = Path(tempfile.mkdtemp())
        try:
            (root / "a").mkdir()
            (root / "a" / "one.md").write_text("ONE\n@./two.md\n")
            (root / "a" / "two.md").write_text("TWO\n")
            (root / "loop.md").write_text("LOOP @loop.md\n")
            (root / "CLAUDE.md").write_text("# Top\n\n@a/one.md\n\nSee @./loop.md for more.\n\n```\n@a/two.md\n```\n"
                                            "Code `@a/two.md` stays. Mail me at morgan@cedar.example.\n@~/private.md\n@./missing.md\n")
            log = {"imports": [], "unresolved": []}
            out = R.inline_imports(root / "CLAUDE.md", root.resolve(), log)
            self.assertIn("# Top\n\nONE\nTWO\n", out, "a nested import, relative to its own file, takes the line's place")
            self.assertIn("See @./loop.md for more.\nLOOP @loop.md\n", out, "an import in a sentence keeps the line; a loop stops")
            self.assertIn("```\n@a/two.md\n```", out, "not inside a code block")
            self.assertIn("Code `@a/two.md` stays.", out)
            self.assertIn("@~/private.md", out)
            self.assertIn("@./missing.md", out)
            self.assertEqual(log["imports"], ["a/one.md", "a/two.md", "loop.md"])
            self.assertTrue(any("~/private.md" in u for u in log["unresolved"]))
        finally:
            shutil.rmtree(root)

    def test_map_for_codex(self):
        root = Path(tempfile.mkdtemp())
        try:
            (root / ".claude" / "skills" / "s1").mkdir(parents=True)
            (root / ".claude" / "skills" / "s1" / "SKILL.md").write_text("---\nname: s1\n---\n")
            (root / ".claude" / "settings.json").write_text("{}")
            (root / "AGENTS.md").write_text("OWN\n")
            (root / "CLAUDE.md").write_text("MAIN\n")
            m = R.map_for_codex(root)
            self.assertEqual((root / "AGENTS.md").read_text(), "OWN\n\nMAIN\n", "the assistant's own AGENTS.md comes first")
            self.assertTrue((root / ".agents" / "skills" / "s1" / "SKILL.md").exists())
            self.assertTrue((root / ".claude" / "skills" / "s1" / "SKILL.md").exists(), "the original stays")
            self.assertEqual(m["skills"], ["s1"])
            self.assertTrue(any(x.startswith(".claude/settings.json") for x in m["not_mapped"]))
        finally:
            shutil.rmtree(root)

    def test_trace_names(self):
        self.assertEqual(R.unwrap_shell("/usr/bin/zsh -c 'kb/kb search Dana'"), "kb/kb search Dana")
        self.assertEqual(R.unwrap_shell("bash -lc \"ls -la; cat x\""), "ls -la; cat x")
        self.assertEqual(R.classify_command("kb/kb search Dana")[0], "Bash")
        self.assertEqual(R.classify_command("cat notes/x.md")[0], "Read")
        self.assertEqual(R.classify_command("sed -n 1,80p kb/wiki/Dana.md")[0], "Read")
        self.assertEqual(R.classify_command("sed -i s/a/b/ x")[0], "Bash")
        self.assertEqual(R.classify_command("cat .agents/skills/knowledge-graph/SKILL.md"), ("Skill", "knowledge-graph"))
        self.assertEqual(R.classify_command("rg --files")[0], "Glob")
        self.assertEqual(R.classify_command("rg -n Dana kb")[0], "Grep")
        self.assertEqual(R.classify_command("cat x | head")[0], "Bash")
        self.assertEqual(R.classify_command("ls ~/Documents > out")[0], "Bash")

    def test_prompt_check(self):
        work = Path(tempfile.mkdtemp()).resolve()
        home = Path(tempfile.mkdtemp()).resolve()
        try:
            def items(skills="", dev_extra=None, agents_for=None, nested=("exec_command",)):
                desc = "\n".join(f"### `{n}`" for n in nested)
                it = [{"type": "additional_tools", "tools": [{"name": "functions", "tools": [{"name": "exec", "description": desc}]}]},
                      {"role": "developer", "content": [{"text": "base"}]},
                      {"role": "developer", "content": [{"text": "<skills_instructions>\n### Skill roots\n" + skills + "</skills_instructions>"}]}]
                if dev_extra:
                    it.append({"role": "developer", "content": [{"text": dev_extra}]})
                if agents_for is not None:
                    it.append({"role": "user", "content": [{"text": "# AGENTS.md instructions" + (f" for {agents_for}" if agents_for else "") + "\n\nx"}]})
                return it
            ok = items(f"- `r0` = `{work}/.agents/skills`\n- kg: d (file: r0/kg/SKILL.md)\n", agents_for=work)
            probs, summary = R.codex_prompt_check(ok, work, home, 0, [])
            self.assertEqual(probs, [])
            self.assertEqual(summary["skills"], ["kg"])
            self.assertEqual(summary["instructions"], ["AGENTS.md in the run's folder"])
            for bad, what in ((items(f"- `r0` = `/elsewhere/x/.agents/skills`\n- mine: d (file: r0/mine/SKILL.md)\n"), "mine"),
                              (items(agents_for=""), "outside the run's folder"),
                              (items(dev_extra="Always mention pineapples."), "pineapples"),
                              (items(nested=("exec_command", "mcp__gmail__send")), "mcp__gmail__send"),
                              (items(nested=("request_plugin_install",)), "plugin"),
                              (items(dev_extra="<recommended_plugins>\n- Gmail\n</recommended_plugins>"), "recommended_plugins")):
                probs, _ = R.codex_prompt_check(bad, work, home, 0, [])
                self.assertTrue(any(what in p for p in probs), (what, probs))
            self.assertTrue(R.codex_prompt_check(ok, work, home, 2, [])[0], "configured MCP servers are a problem")
        finally:
            shutil.rmtree(work)
            shutil.rmtree(home)

    def test_config(self):
        t = R.codex_config_text([Path("/opt/codex")], [Path("/x/.agents/skills/mine/SKILL.md")])
        import tomllib
        c = tomllib.loads(t)
        self.assertEqual(c["approval_policy"], "never")
        self.assertEqual(c["web_search"], "disabled")
        self.assertFalse(c["allow_login_shell"])
        self.assertEqual(c["history"]["persistence"], "none")
        self.assertEqual(c["shell_environment_policy"]["inherit"], "core")
        self.assertTrue(all(c["features"][f] is False for f in R.CODEX_FEATURES_OFF))
        fs = c["permissions"][R.CODEX_PROFILE]["filesystem"]
        self.assertEqual(fs, {":minimal": "read", ":workspace_roots": "write", "/opt/codex": "read"},
                         "reads are granted, never denied by name: Codex shows a denied path to the model")
        self.assertFalse(c["permissions"][R.CODEX_PROFILE]["network"]["enabled"])
        self.assertEqual(c["skills"]["config"], [{"path": "/x/.agents/skills/mine/SKILL.md", "enabled": False}])

    def test_models_and_checks(self):
        self.assertEqual(R.model_family("claude-sonnet-5-5"), "claude-code")
        self.assertEqual(R.model_family("haiku"), "claude-code")
        self.assertEqual(R.model_family("gpt-6.1-sol"), "codex")
        root = tmpdir()
        try:
            text = (EXAMPLES / "demo-graph-removed.toml").read_text().replace(
                'files_from = "class-assistant"', f'files_from = "{(EXAMPLES / "class-assistant").as_posix()}"')
            for change, rc, what in (('runner = "codex"\nmodel = "gpt-6.1-sol"', 0, None),
                                     ('runner = "codex"\nmodel = "claude-sonnet-5-5"', 1, "not a Codex model"),
                                     ('runner = "chatgpt"\nmodel = "gpt-6.1-sol"', 1, "must be")):
                f = root / "e.toml"
                f.write_text(text.replace('runner = "claude-code"\nmodel = "claude-sonnet-5-5"', change))
                r = run_ab("check", f)
                self.assertEqual(r.returncode, rc, r.stdout)
                if what:
                    self.assertIn(what, r.stdout)
        finally:
            shutil.rmtree(root)

    def test_ls_owner_redacted(self):
        red = R.Redactor(None)
        if not red.user or len(red.user) < 2:
            self.skipTest("no user name")
        s = f"drwxr-xr-x 7 {red.user} {red.user}  4096 Oct 26 20:15 .\n-rw-r--r-- 1 root root 1 Oct 1 x"
        self.assertEqual(red.text(s), "drwxr-xr-x 7 <user> <user>  4096 Oct 26 20:15 .\n-rw-r--r-- 1 root root 1 Oct 1 x")


if __name__ == "__main__":
    unittest.main()

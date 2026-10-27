#!/usr/bin/env python3
"""A stand-in for the `codex` command (Codex CLI 0.164.0), for Skill Eval Lite's
offline tests. No model is called.

It answers `--version`, `login status`, `features list`, `mcp list --json` and
`debug prompt-input` from the CODEX_HOME it is given, as Codex does: the
config.toml's features, MCP servers and skills.config; a global AGENTS.md and
skills in CODEX_HOME; skills in $HOME/.agents/skills; the folder's AGENTS.md
and .agents/skills. Like Codex, it installs a small set of its own skills
into CODEX_HOME/skills/.system when it starts.

`exec --json ... -` reads the prompt from stdin and writes a JSONL session
shaped like Codex 0.164.0's: thread.started, turn.started, items
(command_execution, file_change, mcp_tool_call, agent_message), turn.completed
with usage. It really runs `kb/kb search` in its folder (a run without the
knowledge graph gets an error), really writes the draft when the prompt names
drafts/ or notes/, and says in the draft whether the folder's AGENTS.md has the
voice file's text inlined. It judges a pair when the prompt has "## Left" and
"## Right", and answers a suite test or the doctor's probe.

Behavior set by environment variables:
  FAKE_CODEX_LOGGED_OUT=1    not logged in
  FAKE_CODEX_LEAK=<what>     act as if a setting failed to hold: agents (a global
                             AGENTS.md is loaded anyway), skill (a personal skill
                             from elsewhere), mcp (an MCP tool is offered)
  FAKE_CODEX_MCP_CALL=1      call an MCP tool during the run
  FAKE_CODEX_HOME_READABLE=1 the doctor's canary file can be read
  FAKE_CODEX_HANG=<text>     hang when the prompt contains <text>
  FAKE_CODEX_FAIL=<text>     fail when the prompt contains <text>
  FAKE_CODEX_LOG=<file>      append a JSON line per invocation: the arguments,
                             the names of the environment variables, what is in
                             CODEX_HOME, whether auth.json is a link, the config
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import tomllib
import uuid
from pathlib import Path

ENV = os.environ
HOME = Path(ENV.get("CODEX_HOME") or Path.home() / ".codex")
FEATURES = ["apps", "plugins", "remote_plugin", "recommended_plugins", "tool_suggest", "hooks", "memories",
            "shell_snapshot", "multi_agent", "image_generation", "browser_use", "browser_use_external", "computer_use",
            "in_app_browser", "view_image", "goals", "skill_mcp_dependency_install", "daemon_auto_start",
            "shell_tool", "unified_exec"]
DEFAULT_OFF = {"memories", "recommended_plugins"}
SYSTEM_SKILLS = ["imagegen", "skill-creator"]


def config() -> dict:
    try:
        return tomllib.loads((HOME / "config.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def overrides(args) -> tuple[dict, set]:
    feats, cfg = {}, {}
    i = 0
    while i < len(args):
        if args[i] in ("--disable", "--enable") and i + 1 < len(args):
            feats[args[i + 1]] = args[i] == "--enable"
            i += 2
        elif args[i] == "-c" and i + 1 < len(args):
            k, _, v = args[i + 1].partition("=")
            cfg[k] = v.strip('"')
            i += 2
        else:
            i += 1
    return cfg, feats


def features(args) -> dict:
    f = {name: name not in DEFAULT_OFF for name in FEATURES}
    f.update({k: bool(v) for k, v in (config().get("features") or {}).items() if isinstance(v, bool)})
    f.update(overrides(args)[1])
    return f


def install_system_skills():
    for name in SYSTEM_SKILLS:
        d = HOME / "skills" / ".system" / name
        if not d.exists():
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Codex's own {name} skill.\n---\n")


def log(args, extra=None):
    if not ENV.get("FAKE_CODEX_LOG"):
        return
    rec = {"args": args, "env": sorted(ENV), "cwd": str(Path.cwd()),
           "home_entries": sorted(p.name for p in HOME.iterdir()) if HOME.is_dir() else [],
           "auth_is_link": (HOME / "auth.json").is_symlink(),
           "auth_target": os.readlink(HOME / "auth.json") if (HOME / "auth.json").is_symlink() else None,
           "config": (HOME / "config.toml").read_text() if (HOME / "config.toml").is_file() else None}
    rec.update(extra or {})
    with open(ENV["FAKE_CODEX_LOG"], "a") as fh:
        fh.write(json.dumps(rec) + "\n")


def logged_in() -> bool:
    if ENV.get("FAKE_CODEX_LOGGED_OUT"):
        return False
    return (HOME / "auth.json").exists() or bool(ENV.get("CODEX_API_KEY"))


def skill_lines(cwd: Path) -> str:
    off = {str(Path(s["path"]).resolve()) for s in (config().get("skills") or {}).get("config", []) if s.get("path") and s.get("enabled") is False}
    roots, lines = [], []
    for root in (cwd / ".agents" / "skills", Path.home() / ".agents" / "skills", HOME / "skills", HOME / "skills" / ".system"):
        found = [p for p in sorted(root.glob("*/SKILL.md")) if str(p.resolve()) not in off and not p.parent.name.startswith(".")]
        if ENV.get("FAKE_CODEX_LEAK") == "skill" and root == HOME / "skills":
            found = found or []
        if not found:
            continue
        r = f"r{len(roots)}"
        roots.append(f"- `{r}` = `{root}`")
        for p in found:
            m = re.search(r"description: (.*)", p.read_text())
            lines.append(f"- {p.parent.name}: {m.group(1) if m else ''} (file: {r}/{p.parent.name}/SKILL.md)")
    if ENV.get("FAKE_CODEX_LEAK") == "skill":
        roots.append("- `r9` = `/elsewhere/skills`")
        lines.append("- leaked-skill: A personal skill. (file: r9/leaked-skill/SKILL.md)")
    return "<skills_instructions>\n## Skills\n### Skill roots\n" + "\n".join(roots) + "\n### Available skills\n" + "\n".join(lines) + "\n</skills_instructions>"


def prompt_input(args) -> int:
    install_system_skills()
    cwd = Path.cwd()
    f = features(args)
    cfg = config()
    nested = ["apply_patch", "list_mcp_resources"]
    if f.get("shell_tool", True) and f.get("unified_exec", True):
        nested += ["exec_command", "write_stdin"]
    if f.get("plugins", True):
        nested.append("request_plugin_install")
    for name, s in (cfg.get("mcp_servers") or {}).items():
        if s.get("enabled", True):
            nested.append(f"mcp__{name}__send")
    if ENV.get("FAKE_CODEX_LEAK") == "mcp":
        nested.append("mcp__gmail__send_message")
    desc = "Run JavaScript.\n\n" + "\n\n".join(f"### `{n}`\nA tool." for n in nested)
    items = [{"type": "additional_tools", "role": "developer", "tools": [
        {"type": "namespace", "name": "functions", "tools": [{"type": "custom", "name": "exec", "description": desc}]}]},
        {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "You are Codex (a stand-in)."}]},
        {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": skill_lines(cwd)},
                                                             {"type": "input_text", "text": "<permissions instructions>\nfake\n</permissions instructions>"}]}]
    if f.get("recommended_plugins"):
        items[2]["content"].append({"type": "input_text", "text": "<recommended_plugins>\n- Gmail\n</recommended_plugins>"})
    if cfg.get("developer_instructions"):
        items.append({"type": "message", "role": "developer", "content": [{"type": "input_text", "text": cfg["developer_instructions"]}]})
    if (HOME / "AGENTS.md").is_file() or ENV.get("FAKE_CODEX_LEAK") == "agents":
        items.append({"type": "message", "role": "user", "content": [{"type": "input_text", "text": "# AGENTS.md instructions\n\n<INSTRUCTIONS>\nglobal\n</INSTRUCTIONS>"}]})
    if (cwd / "AGENTS.md").is_file():
        items.append({"type": "message", "role": "user", "content": [{"type": "input_text",
                      "text": f"# AGENTS.md instructions for {cwd}\n\n<INSTRUCTIONS>\n{(cwd / 'AGENTS.md').read_text()}\n</INSTRUCTIONS>"}]})
    items.append({"type": "message", "role": "user", "content": [{"type": "input_text", "text": args[-1] if args else ""}]})
    print(json.dumps(items, indent=2))
    return 0


SEQ = [0]


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def item(kind, **fields):
    SEQ[0] += 1
    it = {"id": f"item_{SEQ[0]}", "type": kind, **fields}
    if kind in ("command_execution", "mcp_tool_call"):
        emit({"type": "item.started", "item": {**it, "status": "in_progress"}})
    emit({"type": "item.completed", "item": it})


def command(cmd, cwd, really=True, output=None, code=None):
    if really:
        r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
        output, code = (r.stdout + r.stderr), r.returncode
    item("command_execution", command=f"/usr/bin/zsh -c '{cmd}'", aggregated_output=output or "", exit_code=code,
         status="completed" if code == 0 else "failed")
    return output, code


def finish(text, usage=(9000, 120)):
    item("agent_message", text=text)
    emit({"type": "turn.completed", "usage": {"input_tokens": usage[0], "cached_input_tokens": usage[0] // 2,
                                              "output_tokens": usage[1], "reasoning_output_tokens": 0}})


def exec_(args) -> int:
    prompt = sys.stdin.read()
    model = args[args.index("-m") + 1] if "-m" in args else "gpt-fake"
    log(args, {"prompt_start": prompt[:60]})
    cwd = Path.cwd()
    emit({"type": "thread.started", "thread_id": str(uuid.uuid4())})
    emit({"type": "turn.started"})
    if not logged_in():
        for k in range(2, 4):
            emit({"type": "error", "message": f"Reconnecting... {k}/5 (unexpected status 401 Unauthorized: Missing bearer)"})
        emit({"type": "turn.failed", "error": {"message": "unexpected status 401 Unauthorized"}})
        return 1
    if ENV.get("FAKE_CODEX_HANG") and ENV["FAKE_CODEX_HANG"] in prompt:
        time.sleep(120)
    if ENV.get("FAKE_CODEX_FAIL") and ENV["FAKE_CODEX_FAIL"] in prompt:
        emit({"type": "error", "message": "something went wrong"})
        emit({"type": "turn.failed", "error": {"message": "something went wrong"}})
        return 1
    if ENV.get("FAKE_CODEX_MCP_CALL"):
        item("mcp_tool_call", server="gmail", tool="send_message", arguments={"to": "someone"}, status="completed")
        time.sleep(5)
    item("mcp_tool_call", server="codex", tool="list_mcp_resources", arguments={}, status="completed",
         result={"content": [{"type": "text", "text": "{\"resources\":[]}"}]})
    if all(w in prompt for w in ("PASS", "FAIL", "UNKNOWN")):
        return suite_test(prompt)
    if "## Left" in prompt and "## Right" in prompt:
        return judge(prompt)
    if "probe word" in prompt:
        m = re.search(r"cat '([^']+)'", prompt)
        if m:
            if ENV.get("FAKE_CODEX_HOME_READABLE"):
                command(f"cat '{m.group(1)}'", cwd)
            else:
                command(f"cat '{m.group(1)}'", cwd, False, f"cat: {m.group(1)}: Permission denied\n", 1)
        a = (cwd / "AGENTS.md").read_text() if (cwd / "AGENTS.md").exists() else ""
        w = re.search(r"probe word is (\w+)", a)
        finish(w.group(1) if w else "I don't know", (4000, 5))
        return 0
    return assistant(prompt, cwd)


def assistant(prompt, cwd):
    for f in re.findall(r"input/[\w.-]+\.md", prompt):
        command(f"cat {f}", cwd)
    if (cwd / ".agents" / "skills" / "knowledge-graph" / "SKILL.md").exists():
        command("cat .agents/skills/knowledge-graph/SKILL.md", cwd)
    facts = []
    for name in ("Dana", "Priya", "Sam", "Ellis"):
        if name in prompt:
            out, code = command(f"kb/kb search {name}", cwd)
            if code == 0 and name in ("Dana", "Priya"):
                facts.append("The Hale renewal is 120,000 over two years.")
    agents = (cwd / "AGENTS.md").read_text() if (cwd / "AGENTS.md").exists() else ""
    command("ls -la", cwd)
    first = prompt.strip().splitlines()[0]
    lines = [f"Draft for: {first}", ""] + facts + ["", "Graph: " + ("yes" if (cwd / "kb").exists() else "no"),
             "Voice inlined: " + ("yes" if "The example's voice." in agents else "no"),
             f"(Looked in {Path.home()}/Documents.)", "", "Morgan"]
    draft = "\n".join(lines) + "\n"
    folder = next((d for d in ("drafts", "notes") if d + "/" in prompt), None)
    if folder:
        path = cwd / folder / (re.sub(r"[^a-z]+", "-", first.lower())[:30].strip("-") + ".md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(draft)
        item("file_change", changes=[{"path": str(path), "kind": "add"}], status="completed")
        finish(f"Saved it to {folder}/{path.name}.")
    else:
        finish(draft)
    return 0


def suite_test(prompt):
    steps = re.findall(r"^\d+\. (\w+): (.*)$", prompt, re.M)
    first_write = next((k for k, (tool, _) in enumerate(steps) if tool == "Write"), None)
    first_look = next((k for k, (tool, d) in enumerate(steps) if "kb/kb" in d or "knowledge-graph" in d), None)
    bad = ["17 November" in prompt, "10 December" in prompt, "No such file" in prompt or "not found" in prompt,
           steps and (first_look is None or (first_write is not None and first_write < first_look))]
    verdict = "FAIL" if any(bad) else "PASS"
    finish(("Something in the case does not hold up." if verdict == "FAIL" else "Everything checks out.") + "\n" + verdict, (3000, 30))
    return 0


def judge(prompt):
    left = prompt.split("## Left", 1)[1].split("## Right", 1)[0]
    right = prompt.split("## Right", 1)[1]
    a, b = "120,000" in left, "120,000" in right
    verdict = "LEFT" if a and not b else "RIGHT" if b and not a else "TIE"
    finish(("One draft names the renewal amount and the other doesn't." if verdict != "TIE" else "Much the same.") + "\n" + verdict, (5000, 40))
    return 0


def main(args):
    if "--version" in args:
        print("codex-cli 0.164.0")
        return 0
    if args[:2] == ["login", "status"]:
        log(args)
        if logged_in() and (HOME / "auth.json").exists():
            print("Logged in using ChatGPT")
            return 0
        print("Not logged in")
        return 1
    if args[:2] == ["features", "list"]:
        for name, on in features(args[2:]).items():
            print(f"{name:40} stable             {'true' if on else 'false'}")
        return 0
    if args[:2] == ["mcp", "list"]:
        servers = [{"name": n, "enabled": s.get("enabled", True)} for n, s in (config().get("mcp_servers") or {}).items()]
        print(json.dumps(servers))
        return 0
    if args[:2] == ["debug", "prompt-input"]:
        log(args)
        return prompt_input(args[2:])
    if args and args[0] == "exec":
        install_system_skills()
        return exec_(args[1:])
    print("fake codex: only --version, login status, features list, mcp list, debug prompt-input and exec", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

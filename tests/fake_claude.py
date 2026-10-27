#!/usr/bin/env python3
"""A stand-in for the `claude` command, for Skill Eval Lite's offline tests.

It answers `--version` and `auth status`, and in print mode (-p) reads the
prompt from stdin and writes a stream-json session shaped like Claude Code
2.1.310's: an init event, assistant messages with tool calls, tool results
and a result event. It really runs `kb/kb search` in its folder (so a run
without the knowledge graph gets an error), really writes the draft when the
prompt names drafts/ or notes/, and judges a pair when the prompt has "## Left"
and "## Right". No model is called.

Its behavior is set by environment variables:
  FAKE_CLAUDE_LOGGED_OUT=1   not logged in (auth status and -p say so)
  FAKE_CLAUDE_CONNECTOR=1    a claude.ai connector loads, as if not isolated
  FAKE_CLAUDE_HANG=<text>    hang when the prompt contains <text> (a timeout)
  FAKE_CLAUDE_FAIL=<text>    fail when the prompt contains <text>
  FAKE_CLAUDE_DELAY=<secs>   wait this long before answering
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

ENV = os.environ
SESSION = str(uuid.uuid4())


def emit(obj):
    obj.setdefault("session_id", SESSION)
    obj.setdefault("uuid", str(uuid.uuid4()))
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def flag(args, name, default=None):
    if name in args:
        i = args.index(name)
        return args[i + 1] if i + 1 < len(args) else default
    return default


def main(args):
    if "--version" in args:
        print("2.1.310 (Claude Code)")
        return 0
    if args[:2] == ["auth", "status"]:
        out = ENV.get("FAKE_CLAUDE_LOGGED_OUT")
        print(json.dumps({"loggedIn": not out, "authMethod": "none" if out else "claude.ai", "apiProvider": "firstParty"}, indent=2))
        return 1 if out else 0
    if "-p" not in args:
        print("fake claude: only -p, --version and auth status", file=sys.stderr)
        return 2
    prompt = sys.stdin.read()
    model = flag(args, "--model", "claude-fake-1")
    tools = [t for t in (flag(args, "--tools", "") or "").split(",") if t]
    cwd = Path.cwd()
    skills = sorted(p.name for p in (cwd / ".claude" / "skills").glob("*") if p.is_dir())
    servers = [] if "--strict-mcp-config" in args else [{"name": "claude.ai Gmail", "status": "connected"}]
    offered = list(tools)
    if ENV.get("FAKE_CLAUDE_CONNECTOR"):
        servers = [{"name": "claude.ai Gmail", "status": "connected", "source": "claudeai"}]
        offered.append("mcp__claude_ai_Gmail__send_message")
    memory = None if ENV.get("CLAUDE_CODE_DISABLE_AUTO_MEMORY") else {"auto": str(Path.home() / ".claude" / "projects" / "x" / "memory")}
    emit({"type": "system", "subtype": "init", "cwd": str(cwd), "tools": offered, "mcp_servers": servers, "model": model,
          "permissionMode": flag(args, "--permission-mode", "default"), "apiKeySource": "none",
          "claude_code_version": "2.1.310", "skills": skills, "memory_paths": memory,
          "plugins": [{"name": "cc-plugin-telemetry", "path": "builtin", "source": "cc-plugin-telemetry@builtin"}]})
    if ENV.get("FAKE_CLAUDE_LOGGED_OUT"):
        emit({"type": "result", "subtype": "success", "is_error": True, "result": "Not logged in · Please run /login"})
        return 1
    if ENV.get("FAKE_CLAUDE_HANG") and ENV["FAKE_CLAUDE_HANG"] in prompt:
        time.sleep(120)
    time.sleep(float(ENV.get("FAKE_CLAUDE_DELAY", "0")))
    if ENV.get("FAKE_CLAUDE_FAIL") and ENV["FAKE_CLAUDE_FAIL"] in prompt:
        emit({"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "something went wrong"})
        return 1
    if all(w in prompt for w in ("PASS", "FAIL", "UNKNOWN")):
        return suite_test(prompt, model)
    if "## Left" in prompt and "## Right" in prompt:
        return judge(prompt, model)
    if "probe word" in prompt:
        m = re.search(r"probe word is (\w+)", (cwd / "CLAUDE.md").read_text()) if (cwd / "CLAUDE.md").exists() else None
        word = m.group(1) if m else "I don't know"
        emit({"type": "result", "subtype": "success", "is_error": False, "result": word, "total_cost_usd": 0.0004, "num_turns": 1})
        return 0
    return assistant(prompt, model, cwd, tools)


def tool(n, name, inp, result, is_error=False):
    tid = f"toolu_{n:04d}"
    emit({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]}})
    emit({"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": result, "is_error": is_error}]}})


def assistant(prompt, model, cwd, tools):
    n = 0
    for f in re.findall(r"input/[\w.-]+\.md", prompt):
        n += 1
        p = cwd / f
        tool(n, "Read", {"file_path": str(p)}, p.read_text() if p.exists() else "File does not exist.", not p.exists())
    facts = []
    for name in ("Dana", "Priya", "Sam", "Ellis"):
        if name in prompt and "Bash" in tools:
            n += 1
            cmd = f"kb/kb search {name}"
            r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
            tool(n, "Bash", {"command": cmd, "description": "Search the knowledge graph"}, (r.stdout + r.stderr).strip() or "(no output)", r.returncode != 0)
            if r.returncode == 0 and name in ("Dana", "Priya"):
                facts.append("The Hale renewal is 120,000 over two years.")
    voice = cwd / ".claude" / "identity" / "voice.md"
    tag = hashlib.sha1(voice.read_bytes()).hexdigest()[:8] if voice.exists() else "none"
    board = voice.exists() and "Derived from four Riverside board memos" in voice.read_text()
    first = prompt.strip().splitlines()[0]
    lines = [f"Draft for: {first}", ""] + facts + ["", "Graph: " + ("yes" if (cwd / "kb").exists() else "no"),
             "Board register: " + ("first quarter" if board else "Q1"), f"Voice file {tag}.", f"(Looked in {Path.home()}/Documents.)", "", "Morgan"]
    draft = "\n".join(lines) + "\n"
    folder = next((d for d in ("drafts", "notes") if d + "/" in prompt), None)
    if folder:
        n += 1
        path = cwd / folder / (re.sub(r"[^a-z]+", "-", first.lower())[:30].strip("-") + ".md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(draft)
        tool(n, "Write", {"file_path": str(path), "content": draft}, f"File created successfully at: {path}")
        final = f"Saved it to {folder}/{path.name}. Contact morgan" + "@" + f"realmail.com if needed."
    else:
        final = draft
    emit({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": final}]}})
    emit({"type": "result", "subtype": "success", "is_error": False, "result": final, "total_cost_usd": 0.0123,
          "duration_ms": 1500, "num_turns": n + 1, "permission_denials": [], "modelUsage": {model: {"costUSD": 0.0123}}})
    return 0


def suite_test(prompt, model):
    """A Personal I LLM test: FAIL on a date the notes don't have, on a lookup
    that found nothing, or on a brief written before any lookup."""
    steps = re.findall(r"^\d+\. (\w+): (.*)$", prompt, re.M)
    first_write = next((k for k, (tool, _) in enumerate(steps) if tool == "Write"), None)
    first_look = next((k for k, (tool, d) in enumerate(steps) if "kb/kb" in d or "knowledge-graph" in d), None)
    bad = ["17 November" in prompt, "10 December" in prompt, "No such file" in prompt or "not found" in prompt,
           steps and (first_look is None or (first_write is not None and first_write < first_look))]
    verdict = "FAIL" if any(bad) else "PASS"
    text = ("Something in the case does not hold up." if verdict == "FAIL" else "Everything checks out.") + "\n" + verdict
    emit({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}})
    emit({"type": "result", "subtype": "success", "is_error": False, "result": text, "total_cost_usd": 0.003,
          "duration_ms": 300, "num_turns": 1, "modelUsage": {model: {"costUSD": 0.003}}})
    return 0


def judge(prompt, model):
    left = prompt.split("## Left", 1)[1].split("## Right", 1)[0]
    right = prompt.split("## Right", 1)[1]
    a, b = "120,000" in left, "120,000" in right
    verdict = "LEFT" if a and not b else "RIGHT" if b and not a else "TIE"
    text = f"One draft names the renewal amount from the graph and the other doesn't.\n{verdict}" if verdict != "TIE" else "They are much the same.\nTIE"
    emit({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}})
    emit({"type": "result", "subtype": "success", "is_error": False, "result": text, "total_cost_usd": 0.002,
          "duration_ms": 400, "num_turns": 1, "modelUsage": {model: {"costUSD": 0.002}}})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

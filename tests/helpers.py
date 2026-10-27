"""Shared fixtures for Skill Eval Lite's tests: a small stand-in for the
assistant template (a local git repository, so that `setup` runs offline), the
class assistant set up from it, and runs made with the fake `claude`."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUN_AB = REPO / "run_ab.py"
FAKE = REPO / "tests" / "fake_claude.py"
FAKE_CODEX = REPO / "tests" / "fake_codex.py"
EXAMPLES = REPO / "examples"

KB_PY = '''import json, os, sys
KB = os.path.dirname(os.path.abspath(__file__))
WIKI = os.path.join(KB, "wiki")
cmd = sys.argv[1] if len(sys.argv) > 1 else ""
if cmd == "build":
    os.makedirs(os.path.join(KB, "build"), exist_ok=True)
    open(os.path.join(KB, "build", "graph.json"), "w").write("{}")
    print("RESULT: PASS")
elif cmd == "search":
    words = " ".join(sys.argv[2:]).lower()
    hits = [f for f in sorted(os.listdir(WIKI)) if any(w in f.lower() for w in words.split())] if os.path.isdir(WIKI) else []
    print("\\n".join(hits) or "nothing in the graph matches.")
'''

EXAMPLE = "<!-- FICTIONAL. A worked example for the template's reader. -->\n\n# {name}\n\nThe example's {name}.\n"


def git(*args, cwd):
    return subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *args],
                          cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def make_template(root: Path) -> tuple[Path, str]:
    """A local repository shaped like the assistant template, enough for setup."""
    t = root / "template"
    ids = t / ".claude" / "identity"
    (ids / "examples").mkdir(parents=True)
    for name in ("soul", "persona", "operating", "user", "voice"):
        (ids / f"{name}.md").write_text(f"# {name}\n\n(blank: run /setup)\n")
        (ids / "examples" / f"{name}.example.md").write_text(EXAMPLE.format(name=name))
    (ids / "examples" / "CLAUDE.example.md").write_text(
        EXAMPLE.format(name="CLAUDE.md") + "\nSearch before answering: `kb/kb search <words>`.\n\n## Voice\n\n@.claude/identity/voice.md\n")
    (t / "CLAUDE.md").write_text("# CLAUDE.md\n\n(blank: run /setup)\n")
    for skill in ("knowledge-graph", "knowledge-graph-maintain"):
        (t / ".claude" / "skills" / skill).mkdir(parents=True)
        (t / ".claude" / "skills" / skill / "SKILL.md").write_text(f"---\nname: {skill}\ndescription: test\n---\n")
    (t / "kb" / "seed").mkdir(parents=True)
    (t / "kb" / "seed" / "Using the knowledge graph.md").write_text("# Using the knowledge graph\n")
    (t / "kb" / "kb.py").write_text(KB_PY)
    (t / "kb" / "kb").write_text('#!/bin/sh\nexec python3 "$(cd "$(dirname "$0")" && pwd)/kb.py" "$@"\n')
    os.chmod(t / "kb" / "kb", 0o755)
    (t / ".gitignore").write_text("drafts/\nnotes/\nkb/build/\nkb/wiki/\n")
    git("init", "-q", "-b", "main", cwd=t)
    git("add", "-A", cwd=t)
    git("commit", "-q", "-m", "template", cwd=t)
    return t, git("rev-parse", "HEAD", cwd=t)


def run_ab(*args, env=None, cwd=None) -> subprocess.CompletedProcess:
    e = dict(os.environ)
    for k in list(e):
        if k.startswith(("FAKE_CLAUDE_", "FAKE_CODEX_")):
            del e[k]
    e.update(env or {})
    return subprocess.run([sys.executable, str(RUN_AB), *map(str, args)], capture_output=True, text=True, env=e,
                          cwd=cwd or REPO, timeout=300)


def class_assistant(root: Path) -> Path:
    t, sha = make_template(root)
    dest = root / "class-assistant"
    r = run_ab("setup", dest, "--from", t, "--commit", sha)
    if r.returncode != 0:
        raise RuntimeError(r.stdout + r.stderr)
    return dest


def fake_run(experiment: Path, assistant: Path, out: Path, env=None, *extra) -> subprocess.CompletedProcess:
    return run_ab("run", experiment, "--assistant", assistant, "--out", out, "--claude", FAKE, "--jobs", "4", *extra, env=env)


def tmpdir() -> Path:
    return Path(tempfile.mkdtemp(prefix="sel-test-"))


def fake_codex_run(experiment: Path, assistant: Path, out: Path, env=None, *extra) -> subprocess.CompletedProcess:
    return run_ab("run", experiment, "--assistant", assistant, "--out", out, "--runner", "codex", "--codex", FAKE_CODEX,
                  "--jobs", "4", *extra, env=env)


def fake_codex_env(root: Path, **more) -> dict:
    """A person's own Codex folder with things in it that must not reach a run
    (a config with an MCP server and developer instructions, a global
    AGENTS.md, a skill), a login file, an API key in the environment, and a
    cache folder of its own, so that the temporary Codex homes can be found."""
    real = root / "my-codex"
    if not real.exists():
        (real / "skills" / "my-skill").mkdir(parents=True)
        (real / "skills" / "my-skill" / "SKILL.md").write_text("---\nname: my-skill\ndescription: mine\n---\n")
        (real / "AGENTS.md").write_text("MY GLOBAL INSTRUCTIONS\n")
        (real / "config.toml").write_text('developer_instructions = "MY DEVELOPER INSTRUCTIONS"\n'
                                          '[mcp_servers.mine]\ncommand = "true"\n')
        (real / "auth.json").write_text('{"tokens": "FAKE-LOGIN-TOKEN-0451"}\n')
    env = {"CODEX_HOME": str(real), "OPENAI_API_KEY": "fake-openai-key-0451", "XDG_CACHE_HOME": str(root / "cache"),
           "FAKE_CODEX_LOG": str(root / "codex-log.jsonl")}
    env.update(more)
    return env

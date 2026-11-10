#!/usr/bin/env python3
"""run_ab.py: Skill Eval Lite's runner.

Runs an assistant (a folder of Claude Code instructions, such as the AI 5100
assistant template) on the prompts of an experiment, once per round and
repeat, in a fresh copy each time, with Claude Code in print mode; keeps every
output, run record and trace; runs the experiment's program checks
(CHECKS.md) on the outputs; writes a bundle that the wizard (wizard.html)
loads; and runs an LLM judge on blind pairs.

    python3 run_ab.py setup ../class-assistant          the class assistant, from GitHub
    python3 run_ab.py doctor                            Python, git, Claude Code, login, isolation
    python3 run_ab.py check examples/demo-graph-removed.toml
    python3 run_ab.py plan  examples/demo-graph-removed.toml
    python3 run_ab.py run   examples/demo-graph-removed.toml --assistant ../class-assistant --jobs 4
    python3 run_ab.py judge runs/demo-graph-removed
    python3 run_ab.py score examples/demo-program-check.toml   program checks (CHECKS.md), on runs made
    python3 run_ab.py suite my-suites/suites.yaml       Personal I: run a packet's suites

Every run leaves out the person's own Claude Code settings, memory, plugins,
MCP servers and claude.ai connectors, and refuses to go on if one appears
(SAFETY.md says how, and what was verified).

With --runner codex, each run is `codex exec` instead, with a temporary
CODEX_HOME holding only the runner's config and a link to the person's
login, the assistant's CLAUDE.md written into the run's copy as AGENTS.md
(imports inlined) and its skills copied to .agents/skills; a check before
each run renders what Codex will load and stops if anything is the person's
(SAFETY.md, "Codex").

Python 3.11 or later, standard library only. Made for AI 5500 (Vanderbilt,
Fall 2026) by Claude (claude-opus-5-5), October 2026.
"""
from __future__ import annotations

import sys

if sys.version_info < (3, 11):
    sys.exit("Skill Eval Lite needs Python 3.11 or later (for tomllib); this is " + sys.version.split()[0] + ".\n"
             "In Claude, type /get-ready (in a terminal: install it from https://www.python.org/downloads/).")

import argparse
import datetime as dt
import fnmatch
import getpass
import hashlib
import json
import os
import random
import re
import shlex
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
try:
    VERSION = (HERE / "VERSION").read_text(encoding="utf-8").strip()
except OSError:
    VERSION = "unknown"
TOOL = "skill-eval-lite " + VERSION

SCHEMA = "skill-eval-lite/experiment@1"
BUNDLE_SCHEMA = "skill-eval-lite/bundle@1"
OVERLAY = HERE / "class-assistant" / "overlay"

HOWS = {"as-is", "blank", "removed", "revised", "someone-else's", "neutral-edit"}
ROLES = {"baseline", "improvement", "control-should-change", "control-should-not-change"}
# The built-in check kinds, which the wizard runs (and run_check below, for
# the suites); and the program check, a Python program of the group's own
# that the runner runs on each output (CHECKS.md).
CHECK_KINDS = {"contains", "not-contains", "matches", "word-count", "json-parses",
               "trace-ran-command", "trace-no-tool-outside"}
PROGRAM_KIND = "program"
PROGRAM_TIMEOUT = 60
# Tools that act on files: confined to the run's folder by the permission mode,
# so they are offered (--tools) but never allowed everywhere (--allowedTools).
FILE_TOOLS = {"Read", "Write", "Edit", "Glob", "Grep", "NotebookEdit", "LS"}

# --- Isolation ------------------------------------------------------------
# What keeps a person's own Claude Code out of every run. SAFETY.md explains
# each one and what was verified on Claude Code 2.1.310.
ISOLATION_SETTINGS = {"autoMemoryEnabled": False, "disableClaudeAiConnectors": True}
ISOLATION_ENV = {
    "ENABLE_CLAUDEAI_MCP_SERVERS": "false",   # no claude.ai connectors (Gmail, Calendar, Drive...)
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",   # no auto memory read or written
    "CLAUDE_CODE_DISABLE_BUNDLED_SKILLS": "1",  # the same small skill set on every machine
}
# Variables a Claude Code session sets for its own children; a run started
# from inside Claude Code must not inherit them.
_KEEP_CLAUDE_VARS = {"CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
                     "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_GIT_BASH_PATH", "CLAUDE_CONFIG_DIR"}


def isolation_flags(model: str | None, tools: list[str], allowed: list[str], budget: float | None) -> list[str]:
    """The Claude Code flags for one isolated print-mode run. The prompt goes
    on stdin, so --allowedTools (which takes several values) can come last."""
    flags = ["-p", "--output-format", "stream-json", "--verbose"]
    if model:
        flags += ["--model", model]
    flags += [
        "--setting-sources", "project",      # the run folder's settings only: no user or local settings
        "--strict-mcp-config",               # no MCP servers at all (none are passed)
        "--settings", json.dumps(ISOLATION_SETTINGS, separators=(",", ":")),
        "--tools", ",".join(tools),          # the only tools the model is offered
        "--permission-mode", "acceptEdits",  # edits inside the run folder only
        "--permission-prompts", "none",      # anything that would ask is refused
        "--no-session-persistence",          # no transcript saved under ~/.claude
    ]
    if budget:
        flags += ["--max-budget-usd", f"{budget:g}"]
    if allowed:
        flags += ["--allowedTools", ",".join(allowed)]
    return flags


def child_env() -> dict:
    env = {k: v for k, v in os.environ.items()
           if not (k == "CLAUDECODE" or k in ("CLAUDE_PID", "CLAUDE_EFFORT")
                   or (k.startswith("CLAUDE_CODE_") and k not in _KEEP_CLAUDE_VARS))}
    env.update(ISOLATION_ENV)
    return env


def user_skill_names() -> set[str]:
    """Names (only) of the person's own skills, so that a run can prove none loaded."""
    base = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "skills"
    try:
        return {p.name for p in base.iterdir() if p.is_dir()}
    except OSError:
        return set()


def check_init(init: dict, tools_offered: list[str], project_skills: set[str]) -> tuple[list[str], dict]:
    """Problems with a run's init event (an empty list when it is isolated),
    and a summary of it to keep in run.json."""
    problems = []
    servers = init.get("mcp_servers") or []
    if servers:
        problems.append("MCP servers or connectors loaded: " + ", ".join(str(s.get("name")) for s in servers))
    tools = init.get("tools") or []
    mcp_tools = [t for t in tools if t.startswith("mcp__")]
    if mcp_tools:
        problems.append(f"{len(mcp_tools)} connector or MCP tools offered, e.g. {mcp_tools[0]}")
    extra = [t for t in tools if not t.startswith("mcp__") and t not in tools_offered]
    if extra:
        problems.append("tools offered that the experiment did not allow: " + ", ".join(extra))
    plugins = [p for p in (init.get("plugins") or []) if not str(p.get("source", "")).endswith("@builtin")]
    if plugins:
        problems.append("plugins loaded: " + ", ".join(str(p.get("name")) for p in plugins))
    if init.get("memory_paths"):
        problems.append("auto memory is on")
    personal = sorted((set(init.get("skills") or []) & user_skill_names()) - project_skills)
    if personal:
        problems.append("personal skills loaded: " + ", ".join(personal))
    summary = {
        "claude_code_version": init.get("claude_code_version"),
        "model": init.get("model"),
        "permission_mode": init.get("permissionMode"),
        "mcp_servers": len(servers),
        "connector_tools": len(mcp_tools),
        "tools": tools,
        "skills": init.get("skills") or [],
        "plugins": [p.get("name") for p in (init.get("plugins") or [])],
        "auto_memory": "on" if init.get("memory_paths") else "off",
        "verified": not problems,
    }
    return problems, summary


# --- Small helpers --------------------------------------------------------

def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- The freeze's fingerprint ---------------------------------------------
#
# The wizard freezes an experiment by writing [frozen] date and hash into it.
# The hash is a fingerprint of the file without its [frozen] record, so that
# anyone can check it from the frozen file itself. wizard.html's fingerprint()
# gives the same; tests/fixtures/fingerprints.json holds what both must give.
# 0.1.0 wrote "sha256:" fingerprints of the text as loaded, which can't be
# checked from the file; they are read as frozen, with a note.

FINGERPRINT = "sha256c:"
OLD_FINGERPRINT = re.compile(r"sha256:[0-9a-f]{64}|fnv1a:[0-9a-f]{8}")   # what 0.1.0's wizard wrote
_TABLE = re.compile(r"[ \t]*\[")
_FROZEN_TABLE = re.compile(r"[ \t]*\[[ \t]*frozen[ \t]*\][ \t]*(?:#.*)?")


def _js_number(x: float) -> str:
    """A number as JavaScript's JSON.stringify writes it."""
    if x != x or x in (float("inf"), float("-inf")):
        return "null"
    if x == 0:
        return "0"
    m = re.fullmatch(r"(\d+)(?:\.(\d+))?(?:e([+-]\d+))?", repr(abs(x)))
    whole, frac, exp = m.group(1), m.group(2) or "", int(m.group(3) or 0)
    all_digits = whole + frac
    n = len(whole) - (len(all_digits) - len(all_digits.lstrip("0"))) + exp
    digits = all_digits.strip("0") or "0"
    k = len(digits)
    if k <= n <= 21:
        s = digits + "0" * (n - k)
    elif 0 < n <= 21:
        s = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        s = "0." + "0" * -n + digits
    else:
        s = digits[0] + ("." + digits[1:] if k > 1 else "") + "e" + ("+" if n - 1 >= 0 else "-") + str(abs(n - 1))
    return ("-" if x < 0 else "") + s


def canonical_json(o) -> str:
    """JSON with sorted keys and no spaces, as the wizard writes it for a fingerprint."""
    if isinstance(o, dict):
        return "{" + ",".join(json.dumps(str(k), ensure_ascii=False) + ":" + canonical_json(o[k]) for k in sorted(o)) + "}"
    if isinstance(o, list):
        return "[" + ",".join(canonical_json(x) for x in o) + "]"
    if isinstance(o, bool) or o is None or isinstance(o, str):
        return json.dumps(o, ensure_ascii=False)
    if isinstance(o, int):
        return str(o)
    return _js_number(float(o))


def design_text(text: str) -> str:
    """The experiment without its freeze: for TOML, the text with the
    [frozen] table (its header to the next table's header, or the end)
    taken out, line endings made \\n and trailing spaces trimmed; for JSON,
    the object without "frozen", with sorted keys."""
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    if t.lstrip(_WS).startswith("{"):
        o = json.loads(t)
        if isinstance(o, dict):
            o.pop("frozen", None)
        return canonical_json(o)
    out, skip = [], False
    for line in t.split("\n"):
        if _TABLE.match(line):
            skip = bool(_FROZEN_TABLE.fullmatch(line))
        if not skip:
            out.append(line.rstrip(" \t"))
    return "\n".join(out).rstrip("\n")


def fingerprint(text: str) -> str:
    return FINGERPRINT + hashlib.sha256(design_text(text).encode("utf-8")).hexdigest()


def say(*parts, err=False):
    print(*parts, file=sys.stderr if err else sys.stdout, flush=True)


class Fail(Exception):
    """A problem the person can fix; the message says how."""


# --- Next steps and fixes: Claude's way first -----------------------------
#
# Students work in Claude (the desktop app's Code tab), where Claude runs
# every command through the skills in .claude/skills/. So every message that
# says what to do next, or how to fix something, has one form: what to do,
# then the skill that does it, then the same for someone in a terminal:
#
#     Next, run the LLM judge. In Claude, type /run-experiment (in a terminal: python3 run_ab.py judge runs/x).
#
# status sets the two halves on two lines. The skills are Claude's, so a
# message for Codex (--runner codex) gives its own command alone.
# tests/test_messages.py holds every message to this.

PY = "py" if os.name == "nt" else "python3"
OPEN_WIZARD = {"nt": "start wizard.html"}.get(os.name, "open wizard.html" if sys.platform == "darwin" else "xdg-open wizard.html")
INSTALL_CLAUDE = ('powershell -NoProfile -Command "irm https://claude.ai/install.ps1 | iex"' if os.name == "nt"
                  else "curl -fsSL https://claude.ai/install.sh | bash")


def in_claude(skill: str | tuple, terminal: str | None = None) -> str:
    """The one form of a next step or a fix: "In Claude, type /skill (in a
    terminal: command)". `skill` is a skill's name, with any words typed after
    it ("experiment-intake ../<your assistant>"), or a tuple of names, one for
    each project ("shared-i", "personal-i")."""
    names = [skill] if isinstance(skill, str) else list(skill)
    text = "In Claude, type " + " or ".join("/" + n.lstrip("/") for n in names)
    return text + (f" (in a terminal: {terminal})" if terminal else "")


def installed_claude() -> str | None:
    """Where Anthropic's installer puts `claude` (~/.local/bin, on Windows
    %USERPROFILE%\\.local\\bin\\claude.exe). A desktop app or terminal opened
    before the install doesn't have that folder on its PATH until it is
    restarted, so the runner looks there too."""
    p = Path.home() / ".local" / "bin" / ("claude.exe" if os.name == "nt" else "claude")
    return str(p) if p.is_file() else None


def find_claude(explicit: str | None = None) -> str:
    exe = explicit or os.environ.get("SKILL_EVAL_LITE_CLAUDE") or shutil.which("claude") or installed_claude()
    if not exe:
        raise Fail("Claude Code's `claude` command isn't installed or isn't on your PATH.\n"
                   + in_claude("get-ready", "install it as https://code.claude.com/docs/en/setup shows, "
                                            "sign in once with `claude auth login`, then try again") + ".")
    return exe


def claude_version(exe: str) -> str:
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=60, env=child_env())
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Fail(f"Claude Code didn't answer `claude --version` ({e}).\n"
                   "Check that it is installed. " + in_claude("get-ready", "claude --version") + ".")
    m = re.search(r"\d+\.\d+\.\d+", out.stdout + out.stderr)
    return m.group(0) if m else (out.stdout.strip() or "unknown")


def login_state(exe: str) -> dict:
    """`claude auth status`, which reports the login without calling a model."""
    try:
        out = subprocess.run([exe, "auth", "status"], capture_output=True, text=True, timeout=60, env=child_env())
        return json.loads(out.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {}


NOT_LOGGED_IN = ("Claude Code is not logged in on this computer. The `claude` command signs in once, with your Claude account.\n"
                 + in_claude("get-ready", "claude auth login") + ". Then run this command again.")


def require_login(exe: str) -> dict:
    state = login_state(exe)
    if state and state.get("loggedIn") is False:
        raise Fail(NOT_LOGGED_IN)
    return state


# --- Reading an experiment ------------------------------------------------

class Experiment:
    def __init__(self, path: Path, text: str | None = None):
        self.path = Path(path)
        self.text = text if text is not None else self.path.read_text(encoding="utf-8")
        try:
            self.data = json.loads(self.text) if self.text.lstrip().startswith("{") else tomllib.loads(self.text)
        except (tomllib.TOMLDecodeError, ValueError) as e:
            raise Fail(f"{self.path.name} can't be read: {e}\n"
                       "Open it in a text editor and fix the line the message names, then try again.")
        d = self.data
        self.base = self.path.parent / d.get("files_from", ".") if isinstance(d.get("files_from", "."), str) else self.path.parent
        self.rounds = {r.get("id"): r for r in d.get("rounds", []) if isinstance(r, dict)}
        self.parts = {p.get("id"): p for p in d.get("system", {}).get("parts", []) if isinstance(p, dict)}
        self.prompts = {p.get("id"): p for p in d.get("prompt", []) if isinstance(p, dict)}
        pr = d.get("prompts", {}) if isinstance(d.get("prompts"), dict) else {}
        self.development = list(pr.get("development", []))
        self.held_out = list(pr.get("held_out", []))
        self.model = d.get("model", {}) if isinstance(d.get("model"), dict) else {}
        self.judge = d.get("judge", {}) if isinstance(d.get("judge"), dict) else {}
        self.seed = int(d.get("seed", 1) or 1)
        self.repeats = int(d.get("repeats", 1) or 1)

    @property
    def name(self) -> str:
        return self.path.stem if self.path.stem != "experiment" else self.path.parent.name

    def freeze_state(self) -> tuple[str, str]:
        """(state, date): "frozen" (its fingerprint matches the file),
        "changed" (the file has changed since it was frozen), "old" (frozen
        with 0.1.0, whose fingerprint can't be checked) or "unfrozen"."""
        fr = self.data.get("frozen") if isinstance(self.data.get("frozen"), dict) else {}
        h, date = str(fr.get("hash") or ""), str(fr.get("date") or "")
        if not h:
            return "unfrozen", ""
        if OLD_FINGERPRINT.fullmatch(h):
            return "old", date
        if not h.startswith(FINGERPRINT):
            return "unfrozen", ""
        try:
            same = h == fingerprint(self.text)
        except ValueError:
            same = False
        return ("frozen" if same else "changed"), date

    def part_paths(self, part_id: str) -> list[str]:
        p = self.parts.get(part_id, {})
        if isinstance(p.get("paths"), list):
            return [str(x) for x in p["paths"]]
        return [x for x in re.split(r"\s+and\s+|\s*,\s*", str(p.get("path", "")).strip()) if x]

    def prompt_file_source(self, prompt_id: str, dest: str) -> Path | None:
        base = self.base / "prompts" / prompt_id / "files"
        for cand in (base / dest, base / PurePosixPath(dest).name):
            if cand.is_file():
                return cand
        return None

    def round_file_dest(self, round_id: str, file: str) -> str:
        parts = PurePosixPath(file).parts
        if len(parts) > 2 and parts[0] == "rounds" and parts[1] == round_id:
            return str(PurePosixPath(*parts[2:]))
        return ""

    def problems(self) -> tuple[list[str], list[str]]:
        """(errors, warnings). Errors stop a run; warnings are what the
        wizard's freeze checklist would flag."""
        d, errors, warns = self.data, [], []
        if d.get("schema") != SCHEMA:
            errors.append(f'Add this line near the top of the file: schema = "{SCHEMA}"')
        for key, what in (("title", "a short name for the experiment"), ("criterion", "what makes an output good enough to use"),
                          ("judging_question", "the question every blind pair answers")):
            if not d.get(key):
                warns.append(f"Add {key}: {what}.")
        if len(self.rounds) < 2:
            errors.append("An experiment needs at least two [[rounds]]: round A (the assistant as it is) and a round that changes one part.")
        for rid, r in self.rounds.items():
            ch = r.get("change") or {}
            how = ch.get("how")
            if how not in HOWS:
                errors.append(f"Round {rid}: change.how is {how!r}, which isn't a kind of change Skill Eval Lite knows. "
                              f"Use one of: {', '.join(sorted(HOWS))}.")
                continue
            if r.get("role") and r["role"] not in ROLES:
                warns.append(f"Round {rid}: role {r['role']!r} isn't one Skill Eval Lite knows. Use one of: {', '.join(sorted(ROLES))}.")
            if how == "as-is":
                continue
            part = ch.get("part")
            if part not in self.parts:
                errors.append(f"Round {rid} changes the part {part!r}, but no [[system.parts]] entry has that id. "
                              "Add the part, or fix the id.")
                continue
            if not self.part_paths(part):
                errors.append(f"The part {part!r} has no path. Say which file or folder it is: path = \"...\".")
            if how in ("revised", "someone-else's", "neutral-edit"):
                f = ch.get("file")
                if not f:
                    errors.append(f"Round {rid} ({how}) needs change.file: the file with the new version of the part, "
                                  f"such as rounds/{rid}/.claude/identity/voice.md.")
                elif not (self.base / f).exists():
                    errors.append(f"Round {rid}: its file {f} isn't there (looked in {self.base}). Check the name.")
                elif (self.base / f).is_file() and not self.round_file_dest(rid, f) and len(self.part_paths(part)) != 1:
                    errors.append(f"Round {rid}: move its file into rounds/{rid}/, at the path of the file it replaces "
                                  f"(for example rounds/{rid}/.claude/identity/voice.md).")
            if how == "blank" and ch.get("file") and not (self.base / ch["file"]).exists():
                errors.append(f"Round {rid}: its file {ch['file']} isn't there (looked in {self.base}). Check the name.")
            if r.get("role") != "baseline" and not (r.get("expected") or {}).get("direction"):
                warns.append(f"Round {rid} doesn't say what you expect it to do. Add expected = {{ direction = \"better\" }} "
                             "(or \"worse\", or \"same\").")
        for c in d.get("comparisons", []):
            if c.get("baseline") not in self.rounds or c.get("new") not in self.rounds:
                errors.append(f"A [[comparisons]] entry names a round that doesn't exist ({c.get('baseline')} and {c.get('new')}). "
                              "Use the ids of your [[rounds]].")
        if not d.get("comparisons"):
            errors.append('Add a [[comparisons]] entry that says which two rounds to compare: baseline = "A", new = "B".')
        roles = {r.get("role") for r in self.rounds.values()}
        for role, what in (("control-should-change", "control round that should make things worse"),
                           ("control-should-not-change", "control round that should change nothing")):
            if role not in roles:
                warns.append(f"There is no {what} yet (a round with role = \"{role}\").")
        n_dev, n_held = len(self.development), len(self.held_out)
        if n_dev < 4:
            warns.append(f"There {'is' if n_dev == 1 else 'are'} {n_dev} development prompt{'' if n_dev == 1 else 's'}; the brief asks for at least four.")
        if n_held < 2:
            warns.append(f"There {'is' if n_held == 1 else 'are'} {n_held} held-out prompt{'' if n_held == 1 else 's'}; the brief asks for at least two.")
        for pid in self.development + self.held_out:
            p = self.prompts.get(pid)
            if not p or not str(p.get("text", "")).strip():
                errors.append(f'Prompt "{pid}" is listed under [prompts] but has no [[prompt]] entry with its text. '
                              'Add one, or take it off the list.')
                continue
            if not p.get("reference"):
                warns.append(f'Prompt "{pid}" has no reference: the output you would want. Add reference = """...""".')
            for f in p.get("files", []):
                if not self.prompt_file_source(pid, f):
                    errors.append(f'Prompt "{pid}": its starting file {f} is missing. Save it at {self.base / "prompts" / pid / "files" / f}.')
        if set(self.development) & set(self.held_out):
            errors.append("A prompt is on both lists, development and held_out. Take it off one of them.")
        ids = set()
        for c in d.get("checks", []):
            if c.get("kind") not in CHECK_KINDS | {PROGRAM_KIND}:
                errors.append(f"Check {c.get('id')!r} has a kind Skill Eval Lite doesn't know: {c.get('kind')!r}. "
                              f"Use one of: {', '.join(sorted(CHECK_KINDS | {PROGRAM_KIND}))}.")
            if c.get("object") not in ("product", "process"):
                warns.append(f"Check {c.get('id')!r}: set object = \"product\" (it checks the output) or \"process\" (it checks the steps).")
            if c.get("id") in ids:
                errors.append(f"Two checks are called {c.get('id')!r}. Give each its own id.")
            ids.add(c.get("id"))
            if c.get("kind") == "matches":
                errors += pattern_problems(c.get("id"), c.get("pattern"), c.get("flags", ""))
            if c.get("kind") == PROGRAM_KIND:
                e, w = self.program_problems(c)
                errors += e
                warns += w
        if not d.get("checks"):
            warns.append("There are no [[checks]] yet. Add two or three (the README's \"The experiment file\" lists the kinds).")
        runner = self.model.get("runner", "claude-code")
        if runner not in RUNNERS:
            errors.append(f'[model] runner is {runner!r}. It must be "claude-code" or "codex".')
        if not self.model.get("model"):
            warns.append("[model] does not name a model; the runner's default will be used, and recorded.")
        elif runner in RUNNERS and model_family(self.model.get("model")) != runner:
            errors.append(f"[model] model {self.model.get('model')!r} is not a {RUNNER_LABEL[runner]} model "
                          f"(runner = {runner!r}).")
        if not self.judge.get("prompt"):
            warns.append("[judge] has no prompt, so the LLM judge can't run. Add a [judge] prompt.")
        return errors, warns

    def program_checks(self) -> list[dict]:
        return [c for c in self.data.get("checks", []) if isinstance(c, dict) and c.get("kind") == PROGRAM_KIND]

    def program_path(self, c: dict) -> Path | None:
        """A program check's program, when its path is one the runner takes:
        checks/<folder>/<name>.py, in this experiment's folder (files_from)."""
        return self.base / c["program"] if program_path_ok(c.get("program")) else None

    def program_problems(self, c: dict) -> tuple[list[str], list[str]]:
        """What is wrong with a program check, without running it. The
        designer's copy of check (wizard.html) says the same, word for word."""
        errors, warns = [], []
        cid, prog = c.get("id"), c.get("program")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(cid or "")):
            errors.append(f"Check {cid!r}: a program check's id names the files of its results, so use small letters, "
                          "digits and dashes, such as looked-up-first.")
        if not prog:
            errors.append(f"Check {cid!r} is a program check: add program = \"checks/<id>/check.py\", the path of its program "
                          "(CHECKS.md says how to write one).")
            return errors, warns
        if not program_path_ok(prog):
            errors.append(f"Check {cid!r}: its program must be a Python file in a folder of its own under checks/, "
                          f"such as checks/{cid}/check.py, not {prog!r}.")
            return errors, warns
        f = self.base / prog
        if not f.is_file():
            errors.append(f"Check {cid!r}: its program {prog} isn't there (looked in {self.base}). Check the name.")
            return errors, warns
        digest = hashlib.sha256(f.read_bytes()).hexdigest()
        if not c.get("sha256"):
            errors.append(f"Check {cid!r}: add this line to it, so that the freeze covers its program: sha256 = \"{digest}\"")
        elif c["sha256"] != digest:
            errors.append(f"Check {cid!r}: its program has changed since its sha256 was written. If the change is meant, "
                          f"test it with check, then write the new one: sha256 = \"{digest}\". "
                          "A frozen experiment must then be frozen again.")
        if "params" in c and not isinstance(c["params"], dict):
            errors.append(f"Check {cid!r}: params must be a table, such as params = {{ amounts = [\"120,000\"] }}.")
        t = c.get("timeout_seconds")
        if "timeout_seconds" in c and (isinstance(t, bool) or not isinstance(t, (int, float)) or not 1 <= t <= 600):
            errors.append(f"Check {cid!r}: timeout_seconds must be a number of seconds, from 1 to 600.")
        if not any(e.get("expect") == "fail" for _, e in program_fixtures(f.parent)):
            folder = PurePosixPath(prog).parent.as_posix()
            warns.append(f"Check {cid!r}: add a fixture its program should fail: a folder in {folder}/fixtures/ with an "
                         "expect.json that says \"fail\" (CHECKS.md). It shows that the program catches what it is for.")
        return errors, warns

    def tool_lists(self) -> tuple[list[str], list[str]]:
        """(--tools, --allowedTools) from [model].allowed_tools."""
        tools, allowed = [], []
        for t in self.model.get("allowed_tools", ["Read", "Write", "Edit", "Glob", "Grep"]):
            t = str(t).strip()
            name, _, arg = t.partition(" ")
            name = name.strip()
            if "(" in name:
                name, arg = name.split("(", 1)[0], name.split("(", 1)[1].rstrip(")") + (" " + arg if arg else "")
            if name not in tools:
                tools.append(name)
            if arg:
                allowed.append(f"{name}({arg.strip()})")
            elif name not in FILE_TOOLS:
                allowed.append(name)
        return tools, allowed


# --- Working copies -------------------------------------------------------

# Never copied into a run: the assistant's history, machine-local settings,
# private samples, earlier outputs, and Skill Eval Lite's own skills.
EXCLUDE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "drafts", "notes", "research"}
EXCLUDE_FILES = {".claude/settings.local.json", "CLAUDE.local.md", ".claude/setup/answers.md", ".DS_Store"}
EXCLUDE_TREES = {".claude/skills/experiment-intake", ".claude/skills/skill-eval-helper", ".claude/skills/check-authoring",
                 "writing-samples"}
INTAKE_MARK = "skill-eval-lite experiment-intake"
HELPER_MARK = "skill-eval-lite helper"
CHECKS_MARK = "skill-eval-lite check-authoring"
# Every one of Skill Eval Lite's own skills carries this mark near the top of
# its SKILL.md ("<!-- skill-eval-lite get-ready, version 1 ... -->"), so a copy
# of one in an assistant's .claude/skills/, under any folder name, is left out
# of every run, as the three above are by name.
SKILL_MARK = "<!-- skill-eval-lite "


def is_tool_skill(folder: Path) -> bool:
    """A skill folder that is one of Skill Eval Lite's own skills, by its mark."""
    try:
        with open(folder / "SKILL.md", encoding="utf-8", errors="replace") as f:
            return SKILL_MARK in f.read(4000)
    except OSError:
        return False


def copy_assistant(src: Path, dst: Path, skip: set[Path] = frozenset()) -> None:
    src = src.resolve()
    for root, dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        keep = []
        for d in dirs:
            r = (rel / d).as_posix()
            if d in EXCLUDE_DIRS and rel == Path(".") or d == ".git" or r in EXCLUDE_TREES or (Path(root) / d).resolve() in skip:
                continue
            if rel.as_posix() == ".claude/skills" and is_tool_skill(Path(root) / d):
                continue
            if (Path(root) / d).is_symlink():
                continue
            keep.append(d)
        dirs[:] = keep
        for f in files:
            r = (rel / f).as_posix()
            p = Path(root) / f
            if r in EXCLUDE_FILES or p.resolve() in skip or p.is_symlink():
                continue
            if r == "AGENTS.md" and INTAKE_MARK in p.read_text(encoding="utf-8", errors="replace")[:400]:
                continue
            if r == "HELPER.md" and HELPER_MARK in p.read_text(encoding="utf-8", errors="replace")[:400]:
                continue
            if r == "CHECKS.md" and CHECKS_MARK in p.read_text(encoding="utf-8", errors="replace")[:400]:
                continue
            (dst / rel).mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst / rel / f)


def apply_change(exp: Experiment, rnd: dict, work: Path) -> list[str]:
    """Apply a round's change to a working copy; return what was done."""
    ch = rnd.get("change") or {}
    how = ch.get("how", "as-is")
    if how == "as-is":
        return []
    done, paths, rid = [], exp.part_paths(ch.get("part")), rnd.get("id")
    if how == "removed":
        for pattern in paths:
            hits = list(work.glob(pattern.rstrip("/"))) if any(c in pattern for c in "*?[") else [work / pattern.rstrip("/")]
            for h in hits:
                if h.is_dir():
                    shutil.rmtree(h)
                    done.append(f"removed {h.relative_to(work).as_posix()}/")
                elif h.exists():
                    h.unlink()
                    done.append(f"removed {h.relative_to(work).as_posix()}")
        return done
    src = exp.base / ch["file"] if ch.get("file") else None
    if src and src.is_dir():
        for p in sorted(src.rglob("*")):
            if p.is_file():
                rel = p.relative_to(src)
                (work / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, work / rel)
                done.append(f"{how}: {rel.as_posix()}")
        return done
    dest = exp.round_file_dest(rid, ch["file"]) if ch.get("file") else ""
    targets = [dest] if dest else [p for p in paths if not p.endswith("/")]
    for t in targets:
        (work / t).parent.mkdir(parents=True, exist_ok=True)
        if src:
            shutil.copyfile(src, work / t)
        else:
            (work / t).write_text("", encoding="utf-8")
        done.append(f"{how}: {t}")
    return done


def snapshot(work: Path) -> dict[str, str]:
    out = {}
    for p in work.rglob("*"):
        if p.is_file() and not p.is_symlink():
            try:
                out[p.relative_to(work).as_posix()] = hashlib.sha1(p.read_bytes()).hexdigest()
            except OSError:
                pass
    return out


def safe_temp_parent() -> Path:
    """A temporary folder with no CLAUDE.md or AGENTS.md above it, which
    Claude Code would otherwise load into every run."""
    base = Path(tempfile.gettempdir()).resolve()
    for d in [base, *base.parents]:
        for name in ("CLAUDE.md", "AGENTS.md", "CLAUDE.local.md"):
            if (d / name).exists():
                raise Fail(f"There is a {name} file at {d / name}, in a folder above your temporary folder ({base}).\n"
                           "Claude Code and Codex would read it in every run, so the runs wouldn't be clean.\n"
                           "Move or rename that file, or use another temporary folder.\n"
                           + in_claude("get-ready", "mkdir -p ~/skill-eval-tmp && export TMPDIR=~/skill-eval-tmp") + ".")
    return base


# --- Reading Claude Code's stream -----------------------------------------

UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}")
FICTIONAL_DOMAINS = (".example", ".invalid", ".test", "example.com", "example.org", "example.net")
DROP_KEYS = {"session_id", "uuid", "parent_uuid", "apiKeySource", "memory_paths", "messaging_socket_path",
             "request_id", "requestId", "analytics_disabled", "product_feedback_disabled", "fast_mode_state",
             "fast_mode_disabled_reason", "capabilities", "terminal_slash_commands", "additional_directories",
             "signature", "rate_limit_info", "wire_ingest_context", "wire_tool_inputs"}
LS_LONG_RE = re.compile(r"(?m)^([-dlcbps][rwxsStT-]{9}[@+.]?\s+\d+\s+)(\S+)(\s+)(\S+)")
# Events about the account rather than the run (its plan's usage limits).
DROP_EVENTS = {"rate_limit_event"}


class Redactor:
    """Takes out of a saved record what belongs to this machine or person:
    the run folder's path (written as "."), the home folder ("~"), the user
    and host names, session and message IDs, and real e-mail addresses."""

    def __init__(self, work: Path | None = None):
        self.subs = []
        if work:
            forms = {str(work), str(work.resolve())}
            forms |= {f[len("/private"):] for f in forms if f.startswith("/private/")}
            for w in sorted(forms, key=len, reverse=True):
                self.subs.append((w.rstrip("/\\") + os.sep, ""))
                self.subs.append((w.rstrip("/\\"), "."))
        home = str(Path.home())
        if len(home) > 1:
            self.subs.append((home, "~"))
        self.tmp = str(Path(tempfile.gettempdir()).resolve())
        try:
            self.user = getpass.getuser()
        except Exception:
            self.user = ""
        self.host = socket.gethostname().split(".")[0]
        self.owners = {self.user} if self.user else set()
        try:
            import grp
            self.owners.add(grp.getgrgid(os.getgid()).gr_name)
        except (ImportError, KeyError, AttributeError, OSError):
            pass
        self.owners.discard("")

    def _ls_owner(self, m) -> str:
        own = "<user>" if m.group(2) in self.owners else m.group(2)
        group = "<user>" if m.group(4) in self.owners else m.group(4)
        return m.group(1) + own + m.group(3) + group

    def text(self, s: str) -> str:
        for a, b in self.subs:
            s = s.replace(a, b)
        if self.user and len(self.user) > 1:
            homes = r"(/" + r"home/|/Users/|\\Users\\)"  # (split so the privacy test passes this line)
            s = re.sub(homes + re.escape(self.user) + r"\b", r"\1<user>", s)
            # The owner and group columns of `ls -l` (Codex runs list folders that way).
            s = LS_LONG_RE.sub(self._ls_owner, s)
        if self.host and len(self.host) > 2:
            s = re.sub(r"\b" + re.escape(self.host) + r"\b", "<host>", s)
        s = UUID_RE.sub("<id>", s)
        return EMAIL_RE.sub(lambda m: m.group(0) if m.group(0).lower().endswith(FICTIONAL_DOMAINS) else "<email>", s)

    def obj(self, o):
        if isinstance(o, dict):
            out = {}
            for k, v in o.items():
                if k in DROP_KEYS or (k == "id" and isinstance(v, str) and v.startswith(("msg_", "req_"))):
                    continue
                if k in ("cwd", "original_cwd"):
                    out[k] = "."
                elif k == "plugins" and isinstance(v, list):
                    out[k] = [{"name": p.get("name"), "source": p.get("source")} if isinstance(p, dict) else p for p in v]
                else:
                    out[k] = self.obj(v)
            return out
        if isinstance(o, list):
            return [self.obj(v) for v in o]
        if isinstance(o, str):
            return self.text(o)
        return o


def step_detail(name: str, inp: dict, red: Redactor) -> str:
    if not isinstance(inp, dict):
        return red.text(str(inp))[:300]
    if name == "Bash":
        d = inp.get("command") or ""
    elif name in ("Read", "Write", "Edit", "NotebookEdit"):
        d = inp.get("file_path") or inp.get("notebook_path") or ""
    elif name in ("Glob", "Grep"):
        d = str(inp.get("pattern") or "") + (" in " + str(inp["path"]) if inp.get("path") else "")
    elif name == "Skill":
        d = inp.get("skill") or inp.get("command") or json.dumps(inp)
    else:
        d = json.dumps(inp, ensure_ascii=False)
    d = red.text(str(d))
    return d[2:] if d.startswith("./") else d


# How Claude Code answers a step it refused to run (in a run, one that would
# have asked for a permission nobody can give) or that the person rejected
# (in a saved interactive session): such a step never ran.
DENIED = "Permission for this tool use was denied"
REJECTED = "The user doesn't want to proceed with this tool use"
REFUSALS = (DENIED, REJECTED)


def trace_of(events: list[dict], red: Redactor, results: bool = False) -> list[dict]:
    """The steps of a session: tool, detail and whether it failed, and
    "refused": True for a step Claude Code refused to run; with
    results=True, also the first 400 characters of what each step returned.
    A Codex stream is read by codex_steps (a refusal there is not marked)."""
    if is_codex_stream(events):
        return codex_steps(events, red, results)
    steps, by_id = [], {}
    for e in events:
        if not isinstance(e, dict):
            continue
        msg = e.get("message") or {}
        content = msg.get("content") if isinstance(msg, dict) else None
        if e.get("type") == "assistant" and isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    st = {"tool": c.get("name", "?"), "detail": step_detail(c.get("name", ""), c.get("input") or {}, red), "error": False}
                    by_id[c.get("id")] = st
                    steps.append(st)
        elif e.get("type") == "user" and isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") in by_id:
                    st = by_id[c["tool_use_id"]]
                    st["error"] = bool(c.get("is_error"))
                    body = c.get("content")
                    if isinstance(body, list):
                        body = " ".join(b.get("text", "") for b in body if isinstance(b, dict))
                    body = str(body or "")
                    if st["error"] and body.startswith(REFUSALS):
                        st["refused"] = True
                    else:
                        st.pop("refused", None)
                    if results:
                        st["result"] = red.text(body)[:400]
    return steps


class ClaudeRun:
    """One print-mode run of Claude Code, its stream read as it arrives. The
    init event is checked first, and the run is stopped at once if it shows
    anything of the person's own (a connector, an MCP server, a plugin)."""

    def __init__(self, cmd, cwd, prompt, timeout, tools_offered, project_skills, registry):
        self.cmd, self.cwd, self.prompt, self.timeout = cmd, cwd, prompt, timeout
        self.tools_offered, self.project_skills, self.registry = tools_offered, project_skills, registry
        self.events, self.stderr, self.init, self.result = [], "", None, None
        self.breach, self.isolation, self.timed_out, self.returncode = [], {}, False, None

    def run(self):
        kw = dict(cwd=self.cwd, env=child_env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                  stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        if os.name == "nt":
            kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kw["start_new_session"] = True
        t0 = time.monotonic()
        try:
            self.proc = subprocess.Popen(self.cmd, **kw)
        except OSError as e:
            self.stderr = f"could not start Claude Code: {e}"
            self.returncode = -1
            self.seconds = 0.0
            return self
        self.registry.add(self.proc)
        err_chunks = []
        t_err = threading.Thread(target=lambda: err_chunks.append(self.proc.stderr.read()), daemon=True)
        t_out = threading.Thread(target=self._read, daemon=True)
        t_err.start(), t_out.start()
        try:
            self.proc.stdin.write(self.prompt)
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            self.timed_out = True
            kill(self.proc)
            self.proc.wait()
        t_out.join(10), t_err.join(10)
        self.registry.discard(self.proc)
        self.stderr = "".join(err_chunks)
        self.returncode = self.proc.returncode
        self.seconds = round(time.monotonic() - t0, 1)
        return self

    def _read(self):
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            self.events.append(e)
            if e.get("type") == "system" and e.get("subtype") == "init" and self.init is None:
                self.init = e
                self.breach, self.isolation = check_init(e, self.tools_offered, self.project_skills)
                if self.breach:
                    kill(self.proc)
            elif e.get("type") == "result":
                self.result = e

    @property
    def final(self) -> str:
        return (self.result or {}).get("result") or ""

    @property
    def not_logged_in(self) -> bool:
        return "not logged in" in (self.final + self.stderr).lower() or "/login" in self.final

    # The same questions a CodexRun answers, so that run, judge and suite can use either.
    @property
    def ok(self) -> bool:
        r = self.result or {}
        return bool(r) and r.get("subtype") == "success" and not r.get("is_error") and not self.timed_out and not self.breach

    @property
    def failure(self) -> str:
        r = self.result or {}
        if r:
            return (r.get("subtype") or "") + (": " + self.final[:300] if self.final else "")
        return f"Claude Code exited with code {self.returncode} and no result" + (
            ": " + self.stderr.strip()[-300:] if self.stderr.strip() else "")

    @property
    def cost_usd(self):
        return (self.result or {}).get("total_cost_usd")

    @property
    def usage(self) -> dict:
        return {}

    @property
    def model_seen(self) -> str:
        return (self.init or {}).get("model") or ""

    @property
    def models_used(self) -> list:
        u = (self.result or {}).get("modelUsage") or {}
        return sorted(u) if isinstance(u, dict) else []

    def steps(self, red, results: bool = False) -> list[dict]:
        return trace_of(self.events, red, results)


def kill(proc):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        try:
            proc.kill()
        except OSError:
            pass


# --- Codex ----------------------------------------------------------------
# A Codex run is `codex exec --json` in the same fresh copy, with CODEX_HOME
# set to a temporary folder that holds only a config.toml written here and a
# link to the person's login (auth.json). Nothing else of theirs is in it, so
# their config, MCP servers, profiles, global AGENTS.md, skills, plugins,
# rules, hooks and memories can't load. Before each run the runner renders
# what the model will be given (`codex debug prompt-input`, which calls no
# model) and stops if anything of the person's is in it. SAFETY.md ("Codex")
# explains each setting and what was verified on Codex 0.164.0.

CODEX_TESTED = "0.164.0"
CODEX_DEFAULT_MODEL = "gpt-6.1-sol"      # the runs' and the judge's model unless the experiment names one
CODEX_PROBE_MODEL = "gpt-6-luna"         # doctor's probe: "fast and affordable"
CODEX_PROFILE = "skill-eval-lite"        # the permissions profile written into the config
# Features that would bring in something of the person's (apps are ChatGPT
# connectors; plugins, hooks, memories, the shell snapshot) or reach beyond
# the run's folder (browsers, computer use, image generation, view_image).
CODEX_FEATURES_OFF = ("apps", "plugins", "remote_plugin", "recommended_plugins", "tool_suggest", "hooks",
                      "memories", "shell_snapshot", "multi_agent", "image_generation", "browser_use",
                      "browser_use_external", "computer_use", "in_app_browser", "view_image", "goals",
                      "skill_mcp_dependency_install", "daemon_auto_start")
# For the judge and LLM tests: no shell at all.
CODEX_NO_SHELL = ("shell_tool", "unified_exec")
# Variables through which Codex can take a login other than the plan's, or
# that a Codex session sets for its own children.
CODEX_AUTH_VARS = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_FEDERATION_RULE_ID", "OPENAI_IDENTITY_TOKEN_FILE")
CODEX_NOTE = ("A Codex run evaluates the assistant's instructions as Codex reads them: AGENTS.md is written from "
              "CLAUDE.md with its @ imports inlined, and .claude/skills/ is copied to .agents/skills/. Codex and "
              "Claude Code results are not interchangeable: compare rounds run with the same runner.")
RUNNERS = ("claude-code", "codex")
RUNNER_LABEL = {"claude-code": "Claude Code", "codex": "Codex"}
CLAUDE_ALIASES = {"sonnet", "opus", "haiku", "opusplan", "default", "best", "fable"}


def model_family(model: str | None) -> str | None:
    """Which runner a model name belongs to: claude-code, codex, or None."""
    m = (model or "").strip().lower()
    if not m:
        return None
    return "claude-code" if "claude" in m or m.split("[")[0] in CLAUDE_ALIASES else "codex"


def find_codex(explicit: str | None = None) -> str:
    exe = explicit or os.environ.get("SKILL_EVAL_LITE_CODEX") or shutil.which("codex")
    if not exe:
        raise Fail("Codex is not installed, or `codex` is not on your PATH.\n"
                   "Install it (https://developers.openai.com/codex/cli), then run `codex login` once and sign in\n"
                   "with your ChatGPT account. Then try this command again.")
    return exe


def codex_version(exe: str, env: dict | None = None) -> str:
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=60, env=env)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Fail(f"Codex didn't answer `codex --version` ({e}).\n"
                   "Check that it is installed: type `codex --version` in a terminal.")
    m = re.search(r"\d+\.\d+\.\d+", out.stdout + out.stderr)
    return m.group(0) if m else (out.stdout.strip() or "unknown")


def real_codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def cache_base() -> Path:
    """Where the temporary Codex homes go: the person's cache folder. Not the
    system's temporary folder: Codex refuses to put its helper programs there."""
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Caches"
    else:
        root = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return root / "skill-eval-lite"


def _pid_alive(pid: int) -> bool:
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


def clean_stale_codex_homes(base: Path):
    """Remove temporary Codex homes left by a runner that was killed."""
    for d in base.glob("codex-home-*") if base.is_dir() else []:
        m = re.match(r"codex-home-(\d+)-", d.name)
        if m and not _pid_alive(int(m.group(1))):
            shutil.rmtree(d, ignore_errors=True)


def codex_read_paths(exe: str, home: Path) -> list[Path]:
    """What a sandboxed command may read besides Codex's minimal system paths
    and the run's folder: Codex's own installation (the sandbox runs it),
    the temporary home's helper folder, and Python's installation (kb/kb
    runs python3)."""
    cands = [Path(exe).resolve().parent.parent, home / "tmp", Path(sys.base_prefix), Path(sys.executable).resolve().parent.parent]
    for name in ("python3", "python"):
        w = shutil.which(name)
        if w:
            cands.append(Path(w).resolve().parent.parent)
    out = []
    for c in cands:
        if len(c.parts) > 1 and c not in out:
            out.append(c)
    return [c for c in out if not any(o != c and o in c.parents for o in out)]


def codex_config_text(read_paths: list[Path], skills_off: list[Path]) -> str:
    q = json.dumps
    lines = ["# Written by Skill Eval Lite (run_ab.py) for isolated Codex runs; deleted when the command ends.",
             'approval_policy = "never"', f'default_permissions = "{CODEX_PROFILE}"', "allow_login_shell = false",
             'web_search = "disabled"', "check_for_update_on_startup = false", "project_doc_max_bytes = 1048576",
             "project_root_markers = []", "", "[history]", 'persistence = "none"', "",
             "[memories]", "use_memories = false", "generate_memories = false", "",
             "[analytics]", "enabled = false", "", "[shell_environment_policy]", 'inherit = "core"', "", "[features]"]
    lines += [f"{f} = false" for f in CODEX_FEATURES_OFF]
    for p in skills_off:
        lines += ["", "[[skills.config]]", f"path = {q(str(p))}", "enabled = false"]
    lines += ["", f"[permissions.{CODEX_PROFILE}.filesystem]", '":minimal" = "read"', '":workspace_roots" = "write"']
    lines += [f'{q(str(p))} = "read"' for p in read_paths]
    lines += ["", f"[permissions.{CODEX_PROFILE}.network]", "enabled = false", ""]
    return "\n".join(lines)


def codex_login_text(exe: str, env: dict) -> tuple[bool | None, str]:
    """`codex login status`: (logged in?, how). It calls no model."""
    try:
        out = subprocess.run([exe, "login", "status"], capture_output=True, text=True, timeout=60, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None, ""
    text = (out.stdout + "\n" + out.stderr).strip()
    line = next((l.strip() for l in text.splitlines() if "logged in" in l.lower()), "")
    if "not logged in" in line.lower():
        return False, line
    if line:
        return True, "ChatGPT plan" if "chatgpt" in line.lower() else ("API key" if "api key" in line.lower() else line)
    return None, text[:200]


class CodexHome:
    """The temporary CODEX_HOME for one command. Its config.toml is written
    here; auth.json is a link to the person's own, so that Codex keeps one
    login file however many runs share it (Codex rereads that file before it
    renews a login, so parallel runs don't clash). If Codex replaces the link
    with a renewed login, the renewed file is copied back over the person's
    own before the folder is deleted. Nothing in it is ever saved in a record."""

    def __init__(self, exe: str, use_api_key: bool = False, config_maker=None):
        self.exe, self.use_api_key = exe, use_api_key
        self.config_maker = config_maker or codex_config_text
        self.path = None
        self.real = real_codex_home()
        self.auth = "none"
        self.auth_hash = None
        self.lock = threading.Lock()
        self.skills_off_personal: list[Path] = []
        self.skills_off_builtin: list[Path] = []
        self.read_paths: list[Path] = []

    def __enter__(self):
        base = cache_base()
        base.mkdir(parents=True, exist_ok=True)
        clean_stale_codex_homes(base)
        self.path = Path(tempfile.mkdtemp(prefix=f"codex-home-{os.getpid()}-", dir=base))
        try:
            os.chmod(self.path, 0o700)
        except OSError:
            pass
        (self.path / "tmp").mkdir()
        if not self.use_api_key:
            src = self.real / "auth.json"
            if src.is_file():
                try:
                    os.symlink(src, self.path / "auth.json")
                    self.auth = "link"
                except OSError:
                    shutil.copy2(src, self.path / "auth.json")
                    self.auth = "copy"
                    self.auth_hash = hashlib.sha256((self.path / "auth.json").read_bytes()).hexdigest()
        self.read_paths = codex_read_paths(self.exe, self.path)
        for root in (Path.home() / ".agents" / "skills", Path("/etc/codex/skills")):
            if root.is_dir():
                self.skills_off_personal += sorted(p for p in root.glob("*/SKILL.md"))
        self.write()
        # Codex installs its own small set of skills into a new home when it
        # starts; render once (no model is called) and switch those off too.
        empty = Path(tempfile.mkdtemp(prefix="skill-eval-lite-codex-", dir=safe_temp_parent()))
        try:
            subprocess.run([self.exe, "debug", "prompt-input", "probe"], cwd=empty, env=self.env(),
                           capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired):
            pass
        finally:
            shutil.rmtree(empty, ignore_errors=True)
        self.skills_off_builtin = sorted((self.path / "skills").glob(".system/*/SKILL.md"))
        self.write()
        return self

    def write(self):
        (self.path / "config.toml").write_text(
            self.config_maker(self.read_paths, self.skills_off_personal + self.skills_off_builtin), encoding="utf-8")

    def record_config(self) -> str:
        """The config as it can be shared: paths in the home folder written as ~,
        and the personal skills switched off counted, not named."""
        text = codex_config_text(self.read_paths, [])
        text = text.replace(str(self.path), "<the temporary CODEX_HOME>")
        n_p, n_b = len(self.skills_off_personal), len(self.skills_off_builtin)
        note = (f"\n# Also switched off by path: {n_b} of Codex's own skills"
                + (f" and {n_p} personal skill{'s' if n_p != 1 else ''} from ~/.agents/skills" if n_p else "") + ".\n")
        return Redactor(None).text(text) + note

    def env(self) -> dict:
        e = {k: v for k, v in os.environ.items()
             if not (k.startswith("CODEX_") or k in CODEX_AUTH_VARS or k == "CLAUDECODE" or k.startswith("CLAUDE_CODE_"))}
        if self.use_api_key:
            for k in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL"):
                if k in os.environ:
                    e[k] = os.environ[k]
            if "CODEX_API_KEY" not in e and "OPENAI_API_KEY" in e:
                e["CODEX_API_KEY"] = e["OPENAI_API_KEY"]
        e["CODEX_HOME"] = str(self.path)
        return e

    def sync_auth(self):
        """If Codex renewed the login in the temporary home, put the renewed
        file back in the person's own Codex folder (never printed or saved)."""
        if not self.path:
            return
        with self.lock:
            p, real = self.path / "auth.json", self.real / "auth.json"
            renewed = (self.auth == "link" and p.is_file() and not p.is_symlink()) or \
                      (self.auth == "copy" and p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() != self.auth_hash)
            if not renewed:
                return
            tmp = real.with_name(real.name + ".skill-eval-lite-tmp")
            shutil.copyfile(p, tmp)
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, real)
            if self.auth == "link":
                p.unlink()
                os.symlink(real, p)
            else:
                self.auth_hash = hashlib.sha256(p.read_bytes()).hexdigest()

    def close(self):
        if not self.path:
            return
        try:
            self.sync_auth()
        finally:
            shutil.rmtree(self.path, ignore_errors=True)
            self.path = None

    def __exit__(self, *exc):
        self.close()
        return False


def codex_features(exe: str, env: dict) -> dict:
    """`codex features list`, as {name: enabled}."""
    try:
        out = subprocess.run([exe, "features", "list"], capture_output=True, text=True, timeout=60, env=env).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    feats = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1] in ("true", "false"):
            feats[parts[0]] = parts[-1] == "true"
    return feats


def codex_mcp_servers(exe: str, env: dict) -> list:
    try:
        out = subprocess.run([exe, "mcp", "list", "--json"], capture_output=True, text=True, timeout=60, env=env).stdout
        servers = json.loads(out or "[]")
        return [s for s in servers if isinstance(s, dict) and s.get("enabled", True)]
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return []


# Mapping a Claude Code assistant to what Codex reads.

IMPORT_RE = re.compile(r"(?:(?<=\s)|^)@((?:~/|/|\.{1,2}/)?[^\s`'\"()<>\[\]{}]+)")


def inline_imports(path: Path, root: Path, log: dict, depth: int = 0, seen: frozenset = frozenset()) -> str:
    """A CLAUDE.md (or a file it imports) with its @path imports replaced by
    the files' text, as Claude Code reads them: relative to the importing
    file, not inside code, at most five deep. An import alone on its line
    takes the line's place; one inside a sentence is kept and the file's text
    follows the line. Paths outside the assistant's folder are left as they are."""
    text = path.read_text(encoding="utf-8", errors="replace")
    out, fence = [], None
    for line in text.splitlines(keepends=True):
        s = line.strip()
        fm = re.match(r"(`{3,}|~{3,})", s)
        if fence:
            if fm and fm.group(1)[0] == fence[0] and len(fm.group(1)) >= len(fence):
                fence = None
            out.append(line)
            continue
        if fm:
            fence = fm.group(1)
            out.append(line)
            continue
        scan = re.sub(r"`[^`]*`", lambda m: " " * len(m.group(0)), line)
        found = []
        for m in IMPORT_RE.finditer(scan):
            ref = m.group(1).rstrip(".,;:!?")
            if ref.startswith("~/") or (ref.startswith("/") and not Path(ref).resolve().is_relative_to(root)):
                log["unresolved"].append(f"@{ref} (outside the assistant's folder; left as written)")
                continue
            target = (Path(ref) if ref.startswith("/") else path.parent / ref).resolve()
            if not target.is_file() or not target.is_relative_to(root):
                continue
            rel = target.relative_to(root).as_posix()
            if depth >= 5 or target in seen:
                log["unresolved"].append(f"@{rel} (more than five imports deep, or a loop; left as written)")
                continue
            found.append((ref, target, rel))
        if not found:
            out.append(line)
            continue
        bodies = []
        for ref, target, rel in found:
            log["imports"].append(rel)
            bodies.append(inline_imports(target, root, log, depth + 1, seen | {path.resolve(), target}).rstrip("\n") + "\n")
        if len(found) == 1 and s == "@" + found[0][0]:
            out.append(bodies[0])
        else:
            out.append(line if line.endswith("\n") else line + "\n")
            out += bodies
    return "".join(out)


def map_for_codex(work: Path) -> dict:
    """Write into a run's fresh copy what Codex reads: AGENTS.md from
    CLAUDE.md with its imports inlined (after the assistant's own AGENTS.md,
    if it has one), and each .claude/skills/<name>/ as .agents/skills/<name>/.
    The assistant's own files are left as they are."""
    root = work.resolve()
    log = {"imports": [], "unresolved": []}
    rec = {"agents_md": "", "imports": [], "unresolved": [], "skills": [], "not_mapped": [], "note": CODEX_NOTE}
    own = work / "AGENTS.md"
    claude_md = work / "CLAUDE.md"
    parts = []
    if own.is_file():
        parts.append(own.read_text(encoding="utf-8", errors="replace").rstrip("\n") + "\n")
    if claude_md.is_file():
        parts.append(inline_imports(claude_md, root, log))
    if claude_md.is_file():
        own_note = "the assistant's own AGENTS.md, then " if own.is_file() else ""
        own.write_text("\n".join(parts), encoding="utf-8")
        rec["agents_md"] = (f"AGENTS.md written from {own_note}CLAUDE.md with {len(log['imports'])} @ import"
                            f"{'s' if len(log['imports']) != 1 else ''} inlined ({own.stat().st_size} bytes)")
    elif own.is_file():
        rec["agents_md"] = "the assistant's own AGENTS.md (there is no CLAUDE.md)"
    else:
        rec["agents_md"] = "none: the assistant has no CLAUDE.md or AGENTS.md"
    rec["imports"], rec["unresolved"] = log["imports"], log["unresolved"]
    skills = work / ".claude" / "skills"
    for d in sorted(skills.iterdir()) if skills.is_dir() else []:
        if d.is_dir() and (d / "SKILL.md").is_file():
            dest = work / ".agents" / "skills" / d.name
            if dest.exists():
                rec["skills"].append(f"{d.name} (the assistant's own .agents/skills/{d.name} kept)")
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(d, dest)
            rec["skills"].append(d.name)
    for p, what in ((".claude/settings.json", "project settings (permissions, hooks, environment): Codex's sandbox and "
                                              "settings apply instead"),
                    (".claude/commands", "slash commands (Codex has no project commands; a run doesn't type them)"),
                    (".claude/agents", "subagent definitions"),
                    (".mcp.json", "MCP servers (neither runner loads any)")):
        if (work / p).exists():
            rec["not_mapped"].append(f"{p}: {what}")
    return rec


# What Codex will give the model, checked before each run.

def codex_prompt_check(items: list, work: Path, home: Path, mcp_servers: int, feature_problems: list[str]) -> tuple[list[str], dict]:
    problems = list(feature_problems)
    if mcp_servers:
        problems.append(f"{mcp_servers} MCP server{'s' if mcp_servers != 1 else ''} configured")
    work_r = work.resolve()
    tools, dev, user = [], [], []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        if it.get("type") == "additional_tools":
            for ns in it.get("tools") or []:
                for t in ns.get("tools") or []:
                    name = t.get("name") or ""
                    tools.append(name)
                    if name == "exec" and isinstance(t.get("description"), str):
                        tools += re.findall(r"^### `([^`]+)`", t["description"], re.M)
            continue
        for c in it.get("content") or []:
            if isinstance(c, dict) and isinstance(c.get("text"), str):
                (dev if it.get("role") == "developer" else user if it.get("role") == "user" else []).append(c["text"])
    mcp = [t for t in tools if t.startswith("mcp__")]
    if mcp:
        problems.append(f"{len(mcp)} MCP or connector tools offered, e.g. {mcp[0]}")
    if "request_plugin_install" in tools:
        problems.append("plugin installation offered")
    for tag in ("<recommended_plugins>", "<apps_instructions>", "<plugins_instructions>", "<memories>", "<memory_summary>"):
        if any(tag in t for t in dev):
            problems.append(f"plugins, apps or memories offered ({tag})")
    skills, builtin, personal = [], [], []
    for t in dev:
        if "<skills_instructions>" not in t:
            continue
        roots = dict(re.findall(r"^- `(r\d+)` = `([^`]+)`", t, re.M))
        for name, r, rel in re.findall(r"^- ([^:\n]+): .*\(file: (r\d+)/([^)]+)\)\s*$", t, re.M):
            p = Path(roots.get(r, "/")) / rel
            if p.resolve().is_relative_to(work_r):
                skills.append(name)
            elif p.resolve().is_relative_to((home / "skills" / ".system").resolve()):
                builtin.append(name)
            else:
                personal.append(name)
    if personal:
        problems.append("skills from outside the assistant loaded: " + ", ".join(personal))
    instructions = []
    for t in user:
        if t.startswith("# AGENTS.md instructions"):
            m = re.match(r"# AGENTS\.md instructions for (.+)", t.splitlines()[0])
            if m and Path(m.group(1).strip()).resolve().is_relative_to(work_r):
                instructions.append("AGENTS.md in the run's folder")
            else:
                problems.append("instructions from an AGENTS.md outside the run's folder (a global AGENTS.md?)")
    extra = [t for t in dev[1:] if not t.lstrip().startswith("<")]
    if extra:
        problems.append("extra developer instructions (from a config outside the run): " + " ".join(extra[0].split())[:80])
    summary = {"mcp_servers": mcp_servers, "connector_tools": len(mcp), "tools": sorted(set(tools)), "skills": skills,
               "codex_builtin_skills": builtin, "plugins": [], "instructions": instructions,
               "auto_memory": "off", "network": "off",
               "files": "read: Codex's minimal system paths, the run's folder, Codex and Python; write: the run's folder",
               "verified": not problems}
    return problems, summary


def codex_preflight(exe: str, env: dict, work: Path, home: Path, model: str, extra: list[str],
                    mcp_servers: int, feature_problems: list[str]) -> tuple[list[str], dict]:
    cmd = [exe, "debug", "prompt-input", "-c", f"model={json.dumps(model)}", *extra, "probe"]
    try:
        out = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True, timeout=120)
        items = json.loads(out.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:
        return [f"could not render what Codex would load (`codex debug prompt-input`): {str(e)[:120]}"], {"verified": False}
    return codex_prompt_check(items, work, home, mcp_servers, feature_problems)


class CodexRun:
    """One `codex exec --json` run, its stream read as it arrives. The
    isolation check (preflight) comes first and the run doesn't start if it
    found anything; during the run, an MCP tool call or a web search stops it."""

    def __init__(self, cmd, cwd, prompt, timeout, env, registry, preflight, model):
        self.cmd, self.cwd, self.prompt, self.timeout, self.env = cmd, cwd, prompt, timeout, env
        self.registry, self.model = registry, model
        problems, self.isolation = preflight
        self.breach = list(problems)
        self.events, self.stderr, self.messages, self.errors = [], "", [], []
        self.completed, self.failed_msg, self._usage = False, "", {}
        self.timed_out, self.returncode, self.seconds = False, None, 0.0
        self.init = None

    def run(self):
        if self.breach:
            self.isolation["verified"] = False
            return self
        kw = dict(cwd=self.cwd, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                  stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        if os.name == "nt":
            kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kw["start_new_session"] = True
        t0 = time.monotonic()
        try:
            self.proc = subprocess.Popen(self.cmd, **kw)
        except OSError as e:
            self.stderr, self.returncode = f"could not start Codex: {e}", -1
            return self
        self.registry.add(self.proc)
        err_chunks = []
        t_err = threading.Thread(target=lambda: err_chunks.append(self.proc.stderr.read()), daemon=True)
        t_out = threading.Thread(target=self._read, daemon=True)
        t_err.start(), t_out.start()
        try:
            self.proc.stdin.write(self.prompt)
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            self.timed_out = True
            kill(self.proc)
            self.proc.wait()
        t_out.join(10), t_err.join(10)
        self.registry.discard(self.proc)
        self.stderr = "".join(err_chunks)
        self.returncode = self.proc.returncode
        self.seconds = round(time.monotonic() - t0, 1)
        if self.breach:
            self.isolation["verified"] = False
        return self

    def _read(self):
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            self.events.append(e)
            t = e.get("type")
            item = e.get("item") if isinstance(e.get("item"), dict) else {}
            if t in ("item.started", "item.completed"):
                kind = item.get("type")
                if kind == "mcp_tool_call" and not self.breach and not codex_builtin_mcp(item):
                    self.breach.append(f"an MCP tool was called: {item.get('server')}/{item.get('tool')}")
                    kill(self.proc)
                elif kind == "web_search" and not self.breach:
                    self.breach.append("a web search was made")
                    kill(self.proc)
                elif t == "item.completed" and kind == "agent_message":
                    self.messages.append(item.get("text") or "")
            elif t == "turn.completed":
                self.completed, self._usage = True, e.get("usage") or {}
            elif t == "turn.failed":
                self.failed_msg = ((e.get("error") or {}).get("message") or "the turn failed")
            elif t == "error":
                self.errors.append(str(e.get("message") or ""))

    @property
    def final(self) -> str:
        return self.messages[-1] if self.messages else ""

    @property
    def not_logged_in(self) -> bool:
        text = " ".join(self.errors) + " " + self.failed_msg + " " + self.stderr
        return not self.completed and ("401 Unauthorized" in text or "not logged in" in text.lower())

    @property
    def ok(self) -> bool:
        return self.completed and not self.failed_msg and self.returncode == 0 and not self.timed_out and not self.breach

    @property
    def failure(self) -> str:
        if self.failed_msg:
            return "the turn failed: " + self.failed_msg[:300]
        if self.errors:
            return "Codex reported an error: " + self.errors[-1][:300]
        return f"Codex exited with code {self.returncode} and no answer" + (
            ": " + self.stderr.strip()[-300:] if self.stderr.strip() else "")

    @property
    def cost_usd(self):
        return None

    @property
    def usage(self) -> dict:
        return {k: v for k, v in self._usage.items() if isinstance(v, (int, float))}

    @property
    def model_seen(self) -> str:
        return self.model

    @property
    def models_used(self) -> list:
        return [self.model] if self.completed else []

    def steps(self, red, results: bool = False) -> list[dict]:
        return codex_steps(self.events, red, results)


# Codex's own tools for MCP resources, reported as MCP calls to a server
# called "codex". With no MCP server configured they find nothing; they are
# named in a trace as Claude Code names its equivalents.
CODEX_BUILTIN_MCP = {"list_mcp_resources": "ListMcpResources", "list_mcp_resource_templates": "ListMcpResourceTemplates",
                     "read_mcp_resource": "ReadMcpResource"}


def codex_builtin_mcp(item: dict) -> bool:
    return item.get("server") == "codex" and item.get("tool") in CODEX_BUILTIN_MCP


SHELLS = {"bash", "zsh", "sh", "dash", "fish", "ksh", "pwsh", "powershell", "cmd"}
READ_PROGS = {"cat", "head", "tail", "nl", "less", "more", "wc"}
GLOB_PROGS = {"ls", "find", "tree", "fd"}
GREP_PROGS = {"rg", "grep", "egrep", "fgrep", "ag"}


def unwrap_shell(cmd: str) -> str:
    """`/usr/bin/zsh -c 'kb/kb search Dana'` -> `kb/kb search Dana`."""
    try:
        argv = shlex.split(cmd)
    except ValueError:
        return cmd
    if len(argv) >= 3 and Path(argv[0]).name.lower().removesuffix(".exe") in SHELLS and \
            argv[-2] in ("-c", "-lc", "-ic", "-lic", "/c", "-Command"):
        return argv[-1]
    return cmd


def classify_command(script: str) -> tuple[str, str]:
    """A shell command as the tool Claude Code would have used for it, so that
    the same checks read both runners' traces: a single read-only command is
    Read, Glob or Grep (reading a SKILL.md under .agents/skills is Skill);
    anything else is Bash. The detail keeps the command."""
    if re.search(r"[|;&<>`\n]|\$\(", script):
        return "Bash", script
    try:
        argv = shlex.split(script)
    except ValueError:
        return "Bash", script
    if not argv:
        return "Bash", script
    prog = Path(argv[0]).name
    if prog in READ_PROGS or (prog == "sed" and "-n" in argv and not any(a.startswith("-i") for a in argv)):
        m = re.search(r"(?:^|/)\.agents/skills/([^/]+)/SKILL\.md$", argv[-1])
        return ("Skill", m.group(1)) if m else ("Read", script)
    if prog in GLOB_PROGS or (prog == "rg" and "--files" in argv):
        return "Glob", script
    if prog in GREP_PROGS:
        return "Grep", script
    return "Bash", script


def codex_steps(events: list[dict], red: Redactor, results: bool = False) -> list[dict]:
    """The steps of a Codex session, in the shape trace_of gives for Claude Code."""
    steps, done = [], set()
    started = {}
    for e in events:
        item = e.get("item") if isinstance(e.get("item"), dict) else None
        if not item:
            continue
        if e.get("type") == "item.started":
            started[item.get("id")] = item
            continue
        if e.get("type") != "item.completed":
            continue
        done.add(item.get("id"))
        steps += _codex_item_steps(item, red, results, False)
    for iid, item in started.items():
        if iid not in done:
            steps += _codex_item_steps(item, red, results, True)
    return steps


def _codex_item_steps(item: dict, red: Redactor, results: bool, unfinished: bool) -> list[dict]:
    kind = item.get("type")
    failed = unfinished or item.get("status") in ("failed", "declined")
    out = []
    if kind == "command_execution":
        tool, detail = classify_command(unwrap_shell(str(item.get("command") or "")))
        code = item.get("exit_code")
        st = {"tool": tool, "detail": red.text(detail), "error": failed or (code not in (0, None))}
        if results:
            st["result"] = red.text(str(item.get("aggregated_output") or ""))[:400]
        out.append(st)
    elif kind == "file_change":
        changes = item.get("changes")
        for ch in changes if isinstance(changes, list) else []:
            ch = ch if isinstance(ch, dict) else {}
            kind_of = ch.get("kind")
            kind_of = kind_of.get("type") if isinstance(kind_of, dict) else kind_of
            tool = {"add": "Write", "update": "Edit", "delete": "Delete"}.get(kind_of, "Edit")
            d = red.text(str(ch.get("path") or ""))
            out.append({"tool": tool, "detail": d[2:] if d.startswith("./") else d, "error": failed})
    elif kind == "mcp_tool_call" and codex_builtin_mcp(item):
        out.append({"tool": CODEX_BUILTIN_MCP[item["tool"]], "detail": red.text(json.dumps(item.get("arguments"))), "error": failed})
    elif kind == "mcp_tool_call":
        out.append({"tool": f"mcp__{item.get('server')}__{item.get('tool')}", "detail": red.text(json.dumps(item.get("arguments"))), "error": failed})
    elif kind == "web_search":
        out.append({"tool": "WebSearch", "detail": red.text(str(item.get("query") or "")), "error": failed})
    elif kind not in ("agent_message", "reasoning", "todo_list", "error", None):
        out.append({"tool": "Agent" if "agent" in str(kind) or "collab" in str(kind) else str(kind),
                    "detail": red.text(json.dumps({k: v for k, v in item.items() if k not in ("id", "type", "status")}))[:300],
                    "error": failed})
    return out


def is_codex_stream(events: list) -> bool:
    return any(isinstance(e, dict) and str(e.get("type", "")).startswith(("thread.", "item.", "turn.")) for e in events)


# --- Runners: the same interface for Claude Code and Codex -----------------

class ClaudeRunner:
    name, label = "claude-code", "Claude Code"

    def __init__(self, exe: str):
        self.exe = exe
        self.version = claude_version(exe)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def require_login(self):
        require_login(self.exe)

    def pick_model(self, *cands) -> str | None:
        return next((c for c in cands if model_family(c) == self.name), None)

    def run(self, work: Path, prompt: str, *, model, timeout, tools, allowed, budget, project_skills, registry,
            shell=True, effort=None):
        flags = isolation_flags(model, tools, allowed, budget)
        r = ClaudeRun([self.exe, *flags], work, prompt, timeout, tools, project_skills, registry).run()
        r.command = ["claude", *flags]
        return r

    def command_shown(self, model, tools, allowed, budget) -> str:
        return "claude " + " ".join(shown(f) for f in isolation_flags(model, tools, allowed, budget)) + "  < prompt"

    def describe(self, model, tools, allowed, budget) -> dict:
        return {"name": self.name, "claude_code_version": self.version,
                "flags": isolation_flags(model, tools, allowed, budget), "env": ISOLATION_ENV}

    def record(self) -> dict:
        return {"runner": self.name, "claude_code_version": self.version}


class CodexRunner:
    name, label = "codex", "Codex"

    def __init__(self, exe: str, use_api_key: bool = False):
        self.exe, self.use_api_key = exe, use_api_key
        self.version = codex_version(exe)
        self.home = None
        self.feature_problems: list[str] = []
        self.mcp: list = []

    def __enter__(self):
        safe_temp_parent()
        self.home = CodexHome(self.exe, self.use_api_key).__enter__()
        env = self.home.env()
        feats = codex_features(self.exe, env)
        on = [f for f in CODEX_FEATURES_OFF if feats.get(f)]
        self.feature_problems = [f"Codex features still on: {', '.join(on)}"] if on else []
        self.mcp = codex_mcp_servers(self.exe, env)
        return self

    def __exit__(self, *exc):
        if self.home:
            self.home.close()
        return False

    def login(self) -> tuple[bool | None, str]:
        if self.use_api_key:
            key = os.environ.get("CODEX_API_KEY") or os.environ.get("OPENAI_API_KEY")
            return (True, "API key") if key else (False, "--use-api-key, but neither OPENAI_API_KEY nor CODEX_API_KEY is set")
        return codex_login_text(self.exe, self.home.env())

    def require_login(self):
        ok, how = self.login()
        if ok is False:
            if self.use_api_key:
                raise Fail("You asked to use an API key (--use-api-key), but OPENAI_API_KEY is not set.\n"
                           "Leave out --use-api-key to use your ChatGPT plan's login instead.")
            raise Fail(CODEX_NOT_LOGGED_IN)

    def pick_model(self, *cands) -> str:
        return next((c for c in cands if model_family(c) == "codex"), CODEX_DEFAULT_MODEL)

    def flags(self, model, shell=True, effort=None) -> list[str]:
        f = ["exec", "--json", "--ephemeral", "--skip-git-repo-check", "-m", model]
        if effort:
            f += ["-c", f"model_reasoning_effort={json.dumps(effort)}"]
        if not shell:
            for feat in CODEX_NO_SHELL:
                f += ["--disable", feat]
        return f + ["-"]

    def run(self, work: Path, prompt: str, *, model, timeout, tools=None, allowed=None, budget=None,
            project_skills=None, registry, shell=True, effort=None):
        self.home.sync_auth()
        flags = self.flags(model, shell, effort)
        extra = [x for f in CODEX_NO_SHELL for x in ("--disable", f)] if not shell else []
        pre = codex_preflight(self.exe, self.home.env(), work, self.home.path, model, extra, len(self.mcp), self.feature_problems)
        pre[1].update({"codex_version": self.version, "model": model})
        r = CodexRun([self.exe, *flags], work, prompt, timeout, self.home.env(), registry, pre, model).run()
        r.command = ["codex", *flags]
        return r

    def command_shown(self, model, tools=None, allowed=None, budget=None) -> str:
        return ("codex " + " ".join(shown(f) for f in self.flags(model)) + "  < prompt"
                "\n  (CODEX_HOME is a temporary folder with only the runner's config.toml and a link to your login; SAFETY.md)")

    def describe(self, model, tools=None, allowed=None, budget=None) -> dict:
        return {"name": self.name, "codex_version": self.version, "flags": self.flags(model),
                "codex_home": "a temporary folder holding only config.toml (below) and a link to the login",
                "config_toml": self.home.record_config() if self.home else "",
                "env_left_out": list(CODEX_AUTH_VARS) + ["CODEX_* (every variable)"] if not self.use_api_key else ["CODEX_* except CODEX_API_KEY"],
                "login": "API key" if self.use_api_key else "the ChatGPT plan's login", "note": CODEX_NOTE}

    def record(self) -> dict:
        return {"runner": self.name, "codex_version": self.version}


CODEX_NOT_LOGGED_IN = ("Codex is not logged in on this computer.\n"
                       "Run `codex login` in a terminal and sign in with your ChatGPT account (the one with your paid plan).\n"
                       "Then run this command again.")


def open_runner(name: str, a) -> ClaudeRunner | CodexRunner:
    if name == "codex":
        return CodexRunner(find_codex(getattr(a, "codex", None)), getattr(a, "use_api_key", False))
    if name != "claude-code":
        raise Fail(f"There is no runner called {name!r}. Use --runner claude-code or --runner codex.")
    return ClaudeRunner(find_claude(getattr(a, "claude", None)))


# --- setup ----------------------------------------------------------------

_COMMENT_RE = re.compile(r"^[ \t]*<!--(?:(?!-->).)*-->[ \t]*\n(?:[ \t]*\n)?", re.S | re.M)


def git(*args, cwd=None, check=True) -> subprocess.CompletedProcess:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise Fail(f"This git command didn't work: git {' '.join(args)}\n"
                   f"git said: {(p.stderr or p.stdout).strip()}")
    return p


def cmd_setup(a) -> int:
    dest = Path(a.folder).expanduser()
    if dest.exists() and any(dest.iterdir()):
        raise Fail(f"{dest} already exists and is not empty, so setup won't write over it.\n"
                   "Choose a new folder name, or delete that folder first.")
    if not shutil.which("git"):
        raise Fail("git is not installed. " + in_claude("get-ready", "install it from https://git-scm.com/downloads, "
                                                                 "then run this again") + ".")
    m = tomllib.loads((OVERLAY / "overlay.toml").read_text(encoding="utf-8"))
    source = a.source or m["template"]
    commit = a.commit or m["commit"]
    say(f"Cloning the assistant template from {source}")
    git("clone", "--quiet", source, str(dest))
    git("-c", "advice.detachedHead=false", "checkout", "--quiet", "-b", m.get("branch", "class-assistant"), commit, cwd=dest)
    say(f"  at commit {commit[:7]}, on a new branch {m.get('branch', 'class-assistant')}")
    for c in m.get("copy", []):
        src, dst = dest / c["from"], dest / c["to"]
        if c["from"].endswith("/"):
            if not src.is_dir():
                raise Fail(f"The template has no folder {c['from']} at {commit[:7]}.")
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            if not src.is_file():
                raise Fail(f"The template has no file {c['from']} at {commit[:7]}.")
            dst.parent.mkdir(parents=True, exist_ok=True)
            text = src.read_text(encoding="utf-8")
            dst.write_text(_COMMENT_RE.sub("", text) if c.get("strip_comments") else text, encoding="utf-8")
        say(f"  copied {c['from']} to {c['to']}")
    files = OVERLAY / "files"
    added = 0
    for p in sorted(files.rglob("*")):
        if p.is_file():
            rel = p.relative_to(files)
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dest / rel)
            added += 1
    say(f"  added {added} knowledge-graph pages for the fictional example (kb/wiki/)")
    kb_py = (dest / "kb" / "kb.py").resolve()
    if kb_py.exists():
        b = subprocess.run([sys.executable, str(kb_py), "build"], cwd=dest.resolve(), capture_output=True, text=True)
        ok = "RESULT: PASS" in b.stdout
        say("  built the knowledge graph (kb/kb build): " + ("RESULT: PASS" if ok else "did not pass; the assistant will rebuild it when it searches"))
    git("add", "-A", cwd=dest)
    git("add", "-f", "kb/wiki", cwd=dest, check=False)
    git("-c", "user.name=Skill Eval Lite", "-c", "user.email=skill-eval-lite@users.noreply.example",
        "commit", "--quiet", "-m", f"The class assistant: Wren, for Morgan Reyes (fictional), set up by {TOOL}", cwd=dest)
    head = git("rev-parse", "--short", "HEAD", cwd=dest).stdout.strip()
    say(f"\nThe class assistant is ready in {dest} (commit {head}).")
    say("Wren and Morgan Reyes are the template's fictional example; nobody in it is real.")
    say("Next, check your setup if you haven't yet. " + in_claude("get-ready", f"{PY} run_ab.py doctor") + ".")
    say("Then see the whole cycle once, with the first demonstration. "
        + in_claude("skill-eval-helper", f"{PY} run_ab.py run examples/demo-one-line.toml --assistant {a.folder} --jobs 6") + ".")
    return 0


# --- check and plan -------------------------------------------------------

def load(path: str) -> Experiment:
    p = Path(path)
    if not p.is_file():
        raise Fail(f"There is no experiment file at {path}. Check the path: status lists the experiments there are.\n"
                   + in_claude("shared-i", f"{PY} run_ab.py status") + ".")
    return Experiment(p)


def fix_then_check(path, what: str = "these") -> str:
    """After an experiment's problems: fix them, then check it again."""
    return f"Fix {what}, then check it again. " + in_claude("skill-eval-helper", f"{PY} run_ab.py check {path}") + "."


def changed_since_frozen(date: str) -> str:
    return (f"The file has changed since it was frozen on {date}. Freeze it again in the wizard, keep the earlier file, "
            "dated, and say in your report what you changed and why.")


FROZEN_LINE = {"frozen": "yes, {date}", "old": "yes, {date} (frozen with 0.1.0; the fingerprint can't be checked)",
               "changed": "no: it has changed since it was frozen on {date}",
               "unfrozen": "not yet (the wizard's step 2 freezes it)"}


def experiment_slow_patterns(exp: "Experiment") -> list[str]:
    """Each matches check timed on long made-up outputs and on the references, stretched."""
    refs = [p.get("reference", "") for p in exp.data.get("prompt", []) if isinstance(p, dict)]
    samples = pattern_samples(refs)
    out = []
    for c in exp.data.get("checks", []):
        if isinstance(c, dict) and c.get("kind") == "matches" and not pattern_problems(c.get("id"), c.get("pattern"), c.get("flags", "")):
            out += slow_pattern_problems(c.get("id"), c["pattern"], c.get("flags", ""), samples)
    return out


def cmd_check(a) -> int:
    exp = load(a.experiment)
    errors, warns = exp.problems()
    # Program checks are run here on the references and on their fixtures,
    # which the wizard can't do: it doesn't run programs.
    st_errors, notes = program_selftest(exp)
    errors += st_errors
    errors += experiment_slow_patterns(exp)
    state, date = exp.freeze_state()
    if state == "changed":
        errors.append(changed_since_frozen(date))
    say(f"{exp.path}: {exp.data.get('title', '(no title)')}")
    for e in errors:
        say("  must fix:  " + e)
    for w in warns:
        say(("  (demo)    " if exp.data.get("demo") else "  to do:     ") + w)
    for n in notes:
        say("  program:   " + n)
    if not errors and not warns:
        say("  Nothing is missing.")
    if exp.data.get("demo") and warns:
        say("  This file is a demonstration (demo = true); the (demo) lines are what a full experiment would also need.")
    frozen = state in ("frozen", "old")
    say("  Frozen: " + FROZEN_LINE[state].format(date=date))
    if errors:
        say("\n" + fix_then_check(a.experiment, 'the lines marked "must fix"'))
    elif exp.data.get("demo") or frozen:
        folder = str((exp.data.get("system") or {}).get("folder") or "../class-assistant")
        say("\nNext, run it. " + in_claude("skill-eval-helper" if exp.data.get("demo") else "run-experiment",
                                           f"{PY} run_ab.py run {a.experiment} --assistant {folder} --jobs 4") + ".")
    else:
        say("\nNext, freeze it in the wizard: load it in step 1, press Freeze in step 2, then press 'Export the frozen "
            f"experiment' (now in step 2) and save the file over {a.experiment}. " + in_claude("wizard", OPEN_WIZARD) + ".")
    return 1 if errors else 0


def baseline_round(exp: Experiment) -> str | None:
    """The experiment's baseline: the round whose role is baseline, else the
    first comparison's baseline, else the first round."""
    for rid, r in exp.rounds.items():
        if r.get("role") == "baseline":
            return rid
    comps = [c for c in exp.data.get("comparisons", []) if isinstance(c, dict)]
    return comps[0].get("baseline") if comps else next(iter(exp.rounds), None)


def held_out_comparisons(exp: Experiment, outputs) -> list[dict]:
    """The held-out confirmation (Shared I's fourth step: "run A and your
    final version on them, judge them blind as before"): the baseline round
    against each other round that has run on a held-out prompt, in the
    experiment's order. It needs no comparison in the experiment file, which
    is frozen by then. Empty until the baseline itself has run on one.
    outputs: keys (prompt, round, repeat), as in a bundle."""
    held = {r for (p, r, _k) in outputs if p in exp.held_out}
    base = baseline_round(exp)
    if base not in held:
        return []
    return [{"baseline": base, "new": rid} for rid in exp.rounds if rid in held and rid != base]


def select_runs(exp: Experiment, a) -> list[tuple[str, str, int]]:
    rounds = [r.strip() for r in a.rounds.split(",")] if a.rounds else list(exp.rounds)
    for r in rounds:
        if r not in exp.rounds:
            raise Fail(f"There is no round {r} in {exp.path.name}. Its rounds are: {', '.join(exp.rounds)}.")
    if a.prompts:
        prompts = [p.strip() for p in a.prompts.split(",")]
        for p in prompts:
            if p not in exp.prompts:
                raise Fail(f"There is no prompt {p} in {exp.path.name}. Its prompts are: {', '.join(exp.prompts)}.")
            if p in exp.held_out and not a.held_out:
                raise Fail(f"{p} is a held-out prompt: it stays sealed until your group's changes are final, so that it can test them fairly.\n"
                           "When you are ready to unseal it, add --held-out.")
    else:
        prompts = exp.development + (exp.held_out if a.held_out else [])
    repeats = a.repeats or exp.repeats
    runs = [(p, r, k) for p in prompts for r in rounds for k in range(1, repeats + 1)]
    random.Random(exp.seed).shuffle(runs)
    return runs


def cmd_plan(a) -> int:
    exp = load(a.experiment)
    errors, _ = exp.problems()
    runs = select_runs(exp, a)
    tools, allowed = exp.tool_lists()
    say(f"{exp.path.name}: {len(runs)} runs ({len({r[0] for r in runs})} prompts x {len({r[1] for r in runs})} rounds x "
        f"{max(r[2] for r in runs) if runs else 0} repeats), in this order (shuffled with seed {exp.seed}):")
    for i, (p, r, k) in enumerate(runs, 1):
        say(f"  {i:3}. {p:28} round {r}  repeat {k}")
    jobs = max(1, a.jobs or 1)
    say(f"\nWith --jobs {jobs}, about {max(1, round(len(runs) / jobs * 1.0))} to {max(2, round(len(runs) / jobs * 2.0))} minutes.")
    name = runner_name(a, exp.model.get("runner", "claude-code"))
    if name == "codex":
        model = CodexRunner.pick_model(None, getattr(a, "model", None), exp.model.get("codex_model"), exp.model.get("model"))
        say("Each run: codex " + " ".join(shown(f) for f in CodexRunner.flags(None, model, True, exp.model.get("reasoning_effort")))
            + "  < prompt\n  (CODEX_HOME is a temporary folder with only the runner's config.toml and a link to your login;"
            " Codex has no cost cap, so the time limit is the only limit; SAFETY.md)")
    else:
        say("Each run: claude " + " ".join(shown(f) for f in isolation_flags(exp.model.get("model"), tools, allowed,
                                                                             exp.model.get("max_budget_usd"))) + "  < prompt")
    if errors:
        say("\n" + fix_then_check(a.experiment, "these first"))
        for e in errors:
            say("  " + e)
        return 1
    return 0


def shown(arg: str) -> str:
    return arg if re.fullmatch(r"[\w@%+=:,./-]+", arg) else "'" + arg.replace("'", "'\\''") + "'"


# --- run ------------------------------------------------------------------

def folders_named(text: str) -> list[str]:
    names = re.findall(r"(?<![\w./-])([A-Za-z][\w-]*)/", text)
    return [n for n in dict.fromkeys(names) if n not in ("input", "kb", ".claude")]


def pick_output(written: list[str], prompt_text: str) -> list[str]:
    named = folders_named(prompt_text)
    in_named = [w for w in written if w.split("/", 1)[0] in named]
    return in_named or written


class Out:
    """The run folder: what the wizard and the packet need, nothing personal."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.bundle_path = path / "bundle.json"
        self.bundle = json.loads(self.bundle_path.read_text(encoding="utf-8")) if self.bundle_path.exists() else None

    def existing(self) -> dict:
        return {(o["prompt"], o["round"], o["repeat"]): o for o in (self.bundle or {}).get("outputs", [])}

    def save(self):
        """Write bundle.json. Callers that share the bundle between threads
        hold self.lock while they change it and while they save it."""
        tmp = self.bundle_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.bundle, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(self.bundle_path)


def write_packet_parts(exp: Experiment, out: Path, rounds: list[str], prompts: list[str]):
    """versions/, prompts/ and the experiment, as the packet lays them out."""
    (out / "experiment.toml" if exp.path.suffix != ".json" else out / "experiment.json").write_text(exp.text, encoding="utf-8")
    for rid in rounds:
        rnd = exp.rounds[rid]
        ch = rnd.get("change") or {}
        v = out / "versions" / rid
        v.mkdir(parents=True, exist_ok=True)
        lines = [f"# Round {rid}: {rnd.get('label', '')}", "", f"Role: {rnd.get('role', '')}", f"Change: {ch.get('how', 'as-is')}"
                 + (f" to part {ch['part']} ({', '.join(exp.part_paths(ch['part']))})" if ch.get("part") else "")]
        if ch.get("file"):
            lines.append(f"File: {ch['file']}")
            src = exp.base / ch["file"]
            if src.is_file():
                dest = exp.round_file_dest(rid, ch["file"]) or PurePosixPath(ch["file"]).name
                (v / "files" / dest).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, v / "files" / dest)
        if rnd.get("why"):
            lines += ["", rnd["why"]]
        (v / "CHANGE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for pid in prompts:
        p = exp.prompts[pid]
        d = out / "prompts" / pid
        d.mkdir(parents=True, exist_ok=True)
        (d / "prompt.md").write_text(str(p.get("text", "")).strip() + "\n", encoding="utf-8")
        if p.get("reference"):
            (d / "reference.md").write_text(str(p["reference"]).strip() + "\n", encoding="utf-8")
        for f in p.get("files", []):
            src = exp.prompt_file_source(pid, f)
            (d / "files" / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, d / "files" / f)


def project_skill_names(work: Path) -> set[str]:
    d = work / ".claude" / "skills"
    return {p.name for p in d.iterdir() if p.is_dir()} if d.is_dir() else set()


def one_run(exp: Experiment, assistant: Path, skip: set[Path], p: str, r: str, k: int, runner, model, out: Out,
            registry: set, keep_work: bool, unfrozen: bool = False) -> dict:
    started = now()
    prompt = exp.prompts[p]
    rnd = exp.rounds[r]
    tools, allowed = exp.tool_lists()
    tmp = Path(tempfile.mkdtemp(prefix="skill-eval-lite-", dir=safe_temp_parent()))
    work = tmp / "work"
    work.mkdir()
    codex = runner.name == "codex"
    try:
        copy_assistant(assistant, work, skip)
        changes = apply_change(exp, rnd, work)
        for f in prompt.get("files", []):
            (work / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(exp.prompt_file_source(p, f), work / f)
        mapping = map_for_codex(work) if codex else None
        before = snapshot(work)
        text = str(prompt.get("text", "")).strip() + "\n"
        run = runner.run(work, text, model=model, timeout=int(exp.model.get("timeout_seconds", 300)), tools=tools,
                         allowed=allowed, budget=exp.model.get("max_budget_usd"), project_skills=project_skill_names(work),
                         registry=registry, effort=exp.model.get("reasoning_effort") if codex else None)
        after = snapshot(work)
        red = Redactor(work)
        parts = (".claude/", ".agents/") if codex else (".claude/",)
        written = sorted(f for f, h in after.items() if before.get(f) != h
                         and not f.startswith(("kb/build/", "kb/state/", "input/") + parts) and not (codex and f == "AGENTS.md"))
        changed_parts = sorted(f for f, h in after.items() if before.get(f) != h
                               and (f.startswith(parts) or (codex and f == "AGENTS.md")))
        chosen = pick_output(written, text)
        if run.breach:
            status, reason = "failed", "stopped: the run was not isolated (" + "; ".join(run.breach) + ")"
        elif run.timed_out:
            status, reason = "timeout", f"no result after {exp.model.get('timeout_seconds', 300)} seconds"
        elif run.not_logged_in:
            status, reason = "failed", f"{runner.label} is not logged in"
        elif run.ok:
            status, reason = "ok", ""
        else:
            status, reason = "failed", red.text(run.failure)
        if status == "ok" and chosen:
            pieces = []
            for f in chosen:
                body = (work / f).read_text(encoding="utf-8", errors="replace")
                pieces.append(body if len(chosen) == 1 else f"--- {f} ---\n{body}")
            output = red.text("\n\n".join(pieces).strip() + "\n")
            output_from = "files: " + ", ".join(chosen)
        elif status == "ok":
            output, output_from = red.text(run.final.strip() + "\n"), "the final message"
        else:
            output, output_from = "", ""
        folder = out.path / "outputs" / p / r / str(k)
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        (folder / "output.md").write_text(output, encoding="utf-8")
        (folder / "message.md").write_text(red.text(run.final.strip() + "\n") if run.final else "", encoding="utf-8")
        for f in written:
            (folder / "files" / f).parent.mkdir(parents=True, exist_ok=True)
            (folder / "files" / f).write_text(red.text((work / f).read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
        steps = run.steps(red)
        with open(folder / "trace.jsonl", "w", encoding="utf-8") as fh:
            for st in steps:
                fh.write(json.dumps(st, ensure_ascii=False) + "\n")
        tname = f"{p}__{r}__{k}.jsonl"
        (out.path / "transcripts").mkdir(exist_ok=True)
        with open(out.path / "transcripts" / tname, "w", encoding="utf-8") as fh:
            for e in run.events:
                if e.get("type") not in DROP_EVENTS:
                    fh.write(json.dumps(red.obj(e), ensure_ascii=False) + "\n")
        seen_model = run.model_seen or model or exp.model.get("model") or ""
        record = {
            "prompt": p, "round": r, "repeat": k, "status": status, "reason": reason,
            "model": seen_model, "models_used": run.models_used, **runner.record(),
            "started": started, "seconds": run.seconds,
            "cost_usd": run.cost_usd, "num_turns": (getattr(run, "result", None) or {}).get("num_turns"),
            "permission_denials": len((getattr(run, "result", None) or {}).get("permission_denials") or []),
            "output_from": output_from, "written": written, "parts_changed_by_the_run": changed_parts,
            "round_change": changes, "starting_files": prompt.get("files", []),
            "command": run.command, "stdin": "the prompt's text (prompts/" + p + "/prompt.md)", "cwd": ".",
            "transcript": "transcripts/" + tname, "isolation": run.isolation,
            "tool": TOOL,
        }
        if unfrozen:
            record["frozen"] = False
        if codex:
            record["usage"] = run.usage
            record["reasoning_effort"] = exp.model.get("reasoning_effort") or "the model's default"
            record["codex_mapping"] = mapping
        (folder / "run.json").write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        entry = {"prompt": p, "round": r, "repeat": k, "status": status, "reason": reason, "output": output,
                 "message": red.text(run.final) if run.final else "", "output_from": output_from,
                 "trace": [[s["tool"], s["detail"], step_mark(s)] if s["error"] else [s["tool"], s["detail"]] for s in steps],
                 "model": seen_model, "seconds": run.seconds, "cost_usd": run.cost_usd, "when": started,
                 "runner": runner.name}
        if unfrozen:
            entry["frozen"] = False
        if codex:
            entry["usage"] = run.usage
        if exp.program_checks():
            # The program checks as they were when this run was made: a result
            # for a check that isn't here, at this version, was added after it.
            entry["program_checks"] = {c["id"]: program_version(c) for c in exp.program_checks()}
            record["program_checks"] = entry["program_checks"]
            (folder / "run.json").write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        return {"entry": entry, "breach": run.breach, "not_logged_in": run.not_logged_in and status == "failed"}
    finally:
        if keep_work:
            say(f"  kept the working copy: {work}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


def runner_name(a, configured: str | None) -> str:
    name = getattr(a, "runner", None) or configured or "claude-code"
    if name not in RUNNERS:
        raise Fail(f'There is no runner called {name!r}. Use "claude-code" or "codex".')
    return name


def run_model(runner, a, cfg: dict) -> str | None:
    """The model for a runner: --model, then the experiment's model for that
    runner ([model].codex_model or .claude_model, then .model), then the
    runner's default."""
    explicit = getattr(a, "model", None)
    if explicit and model_family(explicit) != runner.name:
        raise Fail(f"--model {explicit} is not a {runner.label} model. "
                   + ("Leave --model out to use " + CODEX_DEFAULT_MODEL + ", or name a Codex model."
                      if runner.name == "codex" else "Leave --model out, or name a Claude model such as claude-sonnet-5-5."))
    key = "codex_model" if runner.name == "codex" else "claude_model"
    return runner.pick_model(explicit, cfg.get(key), cfg.get("model"))


def bundle_runner(bundle: dict | None) -> str | None:
    """Which runner made the runs in a bundle (None for an empty one); a
    bundle that mixes runners is refused."""
    if not bundle:
        return None
    names = {o.get("runner") or (bundle.get("runner") or {}).get("name") or "claude-code" for o in bundle.get("outputs", [])}
    if len(names) > 1:
        raise Fail("This run folder mixes runs made with Claude Code and with Codex. Their results can't be compared:\n"
                   "a Codex run evaluates the assistant's instructions as Codex reads them. Keep each runner's runs in\n"
                   "its own folder (run with --out runs/<name>-codex).")
    return names.pop() if names else None


def cmd_run(a) -> int:
    exp = load(a.experiment)
    errors, warns = exp.problems()
    configured = exp.model.get("runner", "claude-code")
    name = runner_name(a, configured)
    if name != configured:
        errors = [e for e in errors if not e.startswith("[model] model ")]
    if not errors and exp.program_checks():
        errors, _ = program_selftest(exp)
    if errors:
        say("This experiment can't be run yet:")
        for e in errors:
            say("  " + e)
        say(fix_then_check(a.experiment))
        return 1
    state, date = exp.freeze_state()
    unfrozen = not exp.data.get("demo") and state not in ("frozen", "old")
    if unfrozen and not a.unfrozen:
        anyway = ("To run it as it is anyway, add --unfrozen: the runs are then marked as made before the experiment was frozen,\n"
                  "which the wizard shows.")
        if state == "changed":
            raise Fail(f"{a.experiment} has changed since it was frozen on {date}, so it can't be run as the frozen experiment.\n"
                       "Freeze it again in the wizard (load it in step 1, press Freeze in step 2, then 'Export the frozen experiment'),\n"
                       "save it over the old file and keep the earlier file, dated, for your report.\n"
                       + in_claude("wizard", OPEN_WIZARD) + ".\n" + anyway)
        raise Fail(f"{a.experiment} isn't frozen yet, so it can't be run: an experiment is frozen before anyone sees an output.\n"
                   "Freeze it in the wizard: load it in step 1, press Freeze in step 2, then press 'Export the frozen experiment'\n"
                   f"(now in step 2) and save the file over {a.experiment}.\n"
                   + in_claude("wizard", OPEN_WIZARD) + ". Then run this again.\n" + anyway)
    assistant = Path(a.assistant).expanduser()
    if not assistant.is_dir():
        raise Fail(f"There is no assistant folder at {a.assistant}. For the class assistant, set it up first.\n"
                   + in_claude("get-ready", f"{PY} run_ab.py setup {a.assistant}") + ".")
    if not (assistant / "CLAUDE.md").exists():
        say(f"Note: {assistant} has no CLAUDE.md. Is it the assistant's folder?")
    safe_temp_parent()
    runs = select_runs(exp, a)
    default_out = Path("runs") / (exp.name if name == configured else f"{exp.name}-{name}")
    out = Out(Path(a.out) if a.out else default_out)
    made_by = bundle_runner(out.bundle)
    if made_by and made_by != name and out.bundle.get("outputs"):
        raise Fail(f"{out.path} holds runs made with {RUNNER_LABEL[made_by]}. Runs made with {RUNNER_LABEL[name]} can't be\n"
                   f"judged against them. Put them in their own folder: add --out {out.path}-{name}")
    with open_runner(name, a) as runner:
        runner.require_login()
        model = run_model(runner, a, exp.model)
        out.path.mkdir(parents=True, exist_ok=True)
        have = out.existing()
        if out.bundle and out.bundle.get("experiment", {}).get("sha256") not in (None, sha256(exp.text)):
            say(f"Note: {out.path} holds runs of a different version of this experiment file; new runs are added beside them.")
        todo = [x for x in runs if a.again or x not in have]
        # A run made again makes its pairs' old LLM verdicts stale: drop them, so that judge asks again.
        redone = {(p, k) for (p, r, k) in todo if (p, r, k) in have}
        if redone and out.bundle and out.bundle.get("judge"):
            stale = [j for j in out.bundle["judge"] if (j.get("prompt"), j.get("repeat")) in redone]
            out.bundle["judge"] = [j for j in out.bundle["judge"] if (j.get("prompt"), j.get("repeat")) not in redone]
            for j in stale:
                (out.path / "judge" / str(j.get("comparison", "")).replace("|", "-") / f"{j.get('prompt')}__{j.get('repeat')}.json").unlink(missing_ok=True)
            if stale:
                say(f"Dropped {len(stale)} LLM verdicts on the runs made again; run judge again afterwards.")
        # ...and its program checks' results, which are made again at the end.
        again_runs = {x for x in todo if x in have}
        if again_runs and out.bundle and out.bundle.get("program_results"):
            out.bundle["program_results"] = [r for r in out.bundle["program_results"]
                                             if (r.get("prompt"), r.get("round"), r.get("repeat")) not in again_runs]
        skipped = len(runs) - len(todo)
        # Leave the experiment's own files out of the copies if they sit inside the assistant.
        skip = set()
        for folder in {exp.path.parent.resolve(), exp.base.resolve()}:
            try:
                folder.relative_to(assistant.resolve())
            except ValueError:
                continue
            if folder == assistant.resolve():
                skip |= {exp.path.resolve(), folder / "rounds", folder / "prompts"}
            else:
                skip.add(folder)
        # The program checks' folders too: the assistant must never see what grades it.
        for c in exp.program_checks():
            skip.add((exp.base / PurePosixPath(c["program"]).parent).resolve())
        git_state = {}
        if (assistant / ".git").exists():
            h = git("rev-parse", "--short", "HEAD", cwd=assistant, check=False).stdout.strip()
            dirty = bool(git("status", "--porcelain", cwd=assistant, check=False).stdout.strip())
            git_state = {"commit": h, "uncommitted_changes": dirty}
        if out.bundle is None:
            out.bundle = {"schema": BUNDLE_SCHEMA, "tool": TOOL, "made_up": False, "outputs": [], "judge": [], "files": {}}
        out.bundle.update({
            "experiment": {"name": exp.path.name, "text": exp.text, "sha256": sha256(exp.text), "freeze": state},
            "assistant": {"name": assistant.resolve().name, "git": git_state},
            "runner": runner.describe(model, *exp.tool_lists(), exp.model.get("max_budget_usd")),
            "updated": now(),
        })
        for pid in {x[0] for x in runs}:
            for f in exp.prompts[pid].get("files", []):
                out.bundle["files"][f"{pid}:{f}"] = exp.prompt_file_source(pid, f).read_text(encoding="utf-8")
        write_packet_parts(exp, out.path, sorted({x[1] for x in runs}), sorted({x[0] for x in runs}))
        if exp.data.get("demo"):
            say("This file is a demonstration (demo = true), not a full experiment.")
        if unfrozen:
            say("Note: " + ("this file has changed since it was frozen" if state == "changed" else "this experiment is not frozen")
                + "; with --unfrozen, these runs are marked as made before the freeze.")
        elif state == "old":
            say("Note: this experiment was frozen with Skill Eval Lite 0.1.0, whose fingerprint can't be checked.")
        say(f"{len(todo)} runs of {exp.path.name} on {assistant.resolve().name}, {a.jobs} at a time, with {runner.label} "
            f"{runner.version}" + (f" and the model {model}" if model else "")
            + (f" ({skipped} already in {out.path}; add --again to redo them)" if skipped else "") + ".")
        if name == "codex":
            say("Codex reads the assistant through AGENTS.md (written from CLAUDE.md for each run), so these results\n"
                "can't be compared with Claude Code runs. Your own Codex settings, skills and connectors are left out (SAFETY.md).")
        else:
            say("Your own settings, memory, plugins, MCP servers and connectors are left out of every run (SAFETY.md).")
        if not todo:
            say(f"Nothing to run. The bundle is {out.bundle_path}")
            out.save()
            if exp.program_checks():
                done = score_programs(exp, out, jobs=a.jobs)
                if done["outputs"] or done["references"]:
                    say(f"\nRan the program checks where they had no result yet: {results_text(done)}.")
                    say_program_results(exp, out)
            return 0
        registry: set = set()
        stop = threading.Event()
        stop_reason = []
        done = [0]
        lock = out.lock

        def worker(item):
            if stop.is_set():
                return None
            p, r, k = item
            res = one_run(exp, assistant, skip, p, r, k, runner, model, out, registry, a.keep_work, unfrozen)
            e = res["entry"]
            with lock:
                have[(p, r, k)] = e
                out.bundle["outputs"] = sorted(have.values(), key=lambda o: (o["prompt"], o["round"], o["repeat"]))
                if any(o.get("frozen") is False for o in out.bundle["outputs"]):
                    out.bundle["frozen"] = False
                else:
                    out.bundle.pop("frozen", None)
                out.bundle["updated"] = now()
                done[0] += 1
                cost = f"  ${e['cost_usd']:.3f}" if isinstance(e.get("cost_usd"), (int, float)) else ""
                if e.get("usage"):
                    cost = f"  {e['usage'].get('input_tokens', 0):,} tokens in, {e['usage'].get('output_tokens', 0):,} out"
                say(f"[{done[0]}/{len(todo)}] {e['status']:7} {p:28} round {r}  repeat {k}  {e['seconds']:5.0f} s{cost}"
                    + (f"  ({e['reason'][:90]})" if e["status"] != "ok" and e["reason"] else ""))
                out.save()
            if res["breach"]:
                stop_reason.append("STOPPED: a run was not isolated: " + "; ".join(res["breach"]) +
                                   f"\nSomething of yours loaded into a run, so no more runs were started. Please report this,\n"
                                   f"with your {runner.label} version ({runner.version}), before you run again.")
                stop.set()
                for pr in list(registry):
                    kill(pr)
            elif res["not_logged_in"]:
                stop_reason.append(CODEX_NOT_LOGGED_IN if name == "codex" else NOT_LOGGED_IN)
                stop.set()
            return e

        t0 = time.monotonic()
        pool = ThreadPoolExecutor(max_workers=max(1, a.jobs))
        try:
            list(pool.map(worker, todo))
        except KeyboardInterrupt:
            stop.set()
            for pr in list(registry):
                kill(pr)
            pool.shutdown(wait=True, cancel_futures=True)
            with out.lock:
                out.save()
            say(f"\nStopped. The runs that finished are saved in {out.bundle_path}.")
            return 130
        pool.shutdown(wait=True)
    with out.lock:
        out.save()
    total = time.monotonic() - t0
    if stop_reason:
        say("\n" + stop_reason[0], err=True)
        return 3
    outs = [have[x] for x in todo if x in have]
    n_ok = sum(1 for o in outs if o["status"] == "ok")
    cost = sum(o["cost_usd"] for o in outs if isinstance(o.get("cost_usd"), (int, float)))
    toks = [o["usage"] for o in outs if o.get("usage")]
    usage = (f"; {sum(u.get('input_tokens', 0) for u in toks):,} tokens in ({sum(u.get('cached_input_tokens', 0) for u in toks):,} "
             f"of them cached) and {sum(u.get('output_tokens', 0) for u in toks):,} out, as Codex reports them") if toks else ""
    say(f"\n{n_ok} of {len(outs)} runs finished; {len(outs) - n_ok} failed or timed out (kept as failures). "
        f"{total / 60:.1f} minutes" + (f"; ${cost:.2f} as Claude Code reports it" if cost else "") + usage + ".")
    if exp.program_checks():
        done = score_programs(exp, out, jobs=a.jobs)
        say(f"Ran the program checks (CHECKS.md): {results_text(done)}.")
        say_program_results(exp, out)
    say(f"The bundle for the wizard: {out.bundle_path}")
    if name == "codex":
        say(f"Next, run the LLM judge:  {PY} run_ab.py judge {out.path}")
        say("Then open wizard.html and load the bundle in step 1.")
    else:
        say("Next, run the LLM judge. " + in_claude("skill-eval-helper" if exp.data.get("demo") else "run-experiment",
                                                    f"{PY} run_ab.py judge {out.path}") + ".")
        say("Then load the bundle in the wizard's step 1. " + in_claude("wizard", OPEN_WIZARD) + ".")
    return 0


# --- Program checks -------------------------------------------------------
#
# A program check is a Python program of the group's own, for what the
# built-in kinds can't see (CHECKS.md). The runner runs it: on every output
# at the end of `run` (or later, with `score`), and on each reference and
# fixture in `check`. Each time it gets a fresh folder holding only what it
# may read, never the round, the repeat or the run's folder, so that it can't
# tell which version of the assistant wrote what it checks. The sha256 in the
# experiment file puts the program under the freeze; the wizard shows the
# results, which the bundle carries.

def program_path_ok(prog) -> bool:
    """checks/<folder>/<name>.py, and nothing that climbs out of the folder."""
    if not isinstance(prog, str):
        return False
    parts = prog.split("/")
    return (len(parts) == 3 and parts[0] == "checks" and parts[2].endswith(".py") and len(parts[2]) > 3
            and not any(p in ("", ".", "..") for p in parts) and not re.search(r"[\\:]", prog))


def program_fixtures(folder: Path) -> list[tuple[Path, dict]]:
    """A program's fixtures: the folders in its fixtures/, each with what its
    expect.json says ({} when there is none, or it can't be read)."""
    fx = folder / "fixtures"
    out = []
    for d in sorted(p for p in fx.iterdir() if p.is_dir()) if fx.is_dir() else []:
        try:
            e = json.loads((d / "expect.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            e = None
        out.append((d, e if isinstance(e, dict) else {}))
    return out


def program_version(c: dict) -> str:
    """A program check's version, from its program's sha256 and its params:
    a result counts for the check as it is only if it has this version.
    wizard.html's programVersion gives the same."""
    params = c.get("params") if isinstance(c.get("params"), dict) else {}
    key = canonical_json({"program": c.get("program") or "", "sha256": c.get("sha256") or "", "params": params})
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def program_current(c: dict, o: dict, old: dict | None) -> bool:
    """Whether a kept result is for this output (made at its time) and this version of the check."""
    return bool(old) and old.get("version") == program_version(c) and old.get("output_when") == o.get("when")


def check_applies(c: dict, prompt: dict) -> bool:
    """Whether a check applies to a prompt (its prompts, else its tags, else every prompt), as the wizard's applies()."""
    if c.get("prompts") is not None:
        return prompt.get("id") in c["prompts"]
    if c.get("tags") is not None:
        return any(t in c["tags"] for t in prompt.get("tags", []))
    return True


def program_verdict(stdout: str, stderr: str) -> tuple[str, str]:
    """A program's first line: pass, fail or n/a, then its reason. Anything
    else is n/a, with what it printed."""
    first = (stdout.strip().splitlines() or [""])[0]
    word, _, why = first.partition(" ")
    err = stderr.strip()[-200:]
    if word.lower() in ("pass", "fail", "n/a"):
        return word.lower(), why.strip() or (err if word.lower() == "n/a" else "")
    if not first:
        return "n/a", "the program printed nothing" + (": " + err if err else "")
    return "n/a", f"the program printed {first!r}, not pass, fail or n/a" + (": " + err if err else "")


def program_env() -> dict:
    """A program check's environment: the runs' own, without API keys or
    tokens (a check calls no model)."""
    return {k: v for k, v in child_env().items() if not re.search(r"API_KEY|TOKEN|SECRET|PASSWORD", k, re.I)}


def run_program(prog: Path, folder: Path, timeout: float, cwd: Path, isolated: bool = False) -> tuple[str, str]:
    """Run a check's program on a folder: (result, reason). An experiment's
    program (isolated) runs with Python's isolated mode (-I: no user site,
    no PYTHON* variables, nothing imported from the folder it reads), in
    UTF-8, with no API keys; a suite's runs as it always has."""
    if prog.suffix == ".py":
        cmd = [sys.executable] + (["-I", "-B", "-X", "utf8"] if isolated else []) + [str(prog)]
    else:
        cmd = [str(prog)]
    extra = {"encoding": "utf-8", "errors": "replace", "env": program_env()} if isolated else {}
    try:
        p = subprocess.run(cmd + [str(folder)], capture_output=True, text=True, timeout=timeout, cwd=cwd, **extra)
    except subprocess.TimeoutExpired as e:
        return "n/a", (f"the program took longer than {timeout:g} second{'' if timeout == 1 else 's'}, so it gave no result"
                       if isolated else f"the program did not run: {e}")
    except OSError as e:
        return "n/a", f"the program did not run: {e}"
    return program_verdict(p.stdout, p.stderr)


def starting_files(exp: Experiment, prompt: dict | None, files: dict | None = None) -> dict:
    """A prompt's starting files, by the path they take in a run."""
    out = {}
    for f in (prompt or {}).get("files", []):
        if files and f"{prompt['id']}:{f}" in files:
            out[f] = files[f"{prompt['id']}:{f}"]
        else:
            src = exp.prompt_file_source(prompt["id"], f)
            if src:
                out[f] = src.read_text(encoding="utf-8", errors="replace")
    return out


def write_case(case: Path, c: dict, kind: str, prompt: dict | None, output: str | None = None, trace=None,
               transcript: Path | None = None, files: Path | None = None, starting: dict | None = None,
               fixture: Path | None = None, runner: str | None = None):
    """The folder a program reads: output.md, reference.md, trace.jsonl,
    transcript.jsonl, files/ (what the run wrote), starting/ (the prompt's
    starting files) and context.json; for a fixture, its own files."""
    case.mkdir(parents=True)
    if fixture:
        for p in sorted(fixture.rglob("*")):
            rel = p.relative_to(fixture).as_posix()
            if p.is_file() and rel != "expect.json" and "__pycache__" not in p.parts:
                (case / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, case / rel)
    if output is not None:
        (case / "output.md").write_text(output, encoding="utf-8")
    if prompt and prompt.get("reference") and not (case / "reference.md").exists():
        (case / "reference.md").write_text(str(prompt["reference"]).strip() + "\n", encoding="utf-8")
    if isinstance(trace, list):
        with open(case / "trace.jsonl", "w", encoding="utf-8") as fh:
            for st in trace:
                fh.write(json.dumps(st, ensure_ascii=False) + "\n")
    elif trace and Path(trace).is_file():
        shutil.copyfile(trace, case / "trace.jsonl")
    if transcript and transcript.is_file():
        shutil.copyfile(transcript, case / "transcript.jsonl")
    if files and files.is_dir():
        shutil.copytree(files, case / "files")
    for path, text in (starting or {}).items():
        (case / "starting" / path).parent.mkdir(parents=True, exist_ok=True)
        (case / "starting" / path).write_text(text, encoding="utf-8")
    written = sorted(p.relative_to(case / "files").as_posix() for p in (case / "files").rglob("*") if p.is_file()) \
        if (case / "files").is_dir() else []
    ctx = {"check": c.get("id"), "case": kind, "object": c.get("object"),
           "params": c.get("params") if isinstance(c.get("params"), dict) else {},
           "prompt": {k: prompt.get(k) for k in ("id", "title", "tags", "text")} if prompt else None,
           "output": "output.md" if (case / "output.md").is_file() else None,
           "reference": "reference.md" if (case / "reference.md").is_file() else None,
           "trace": "trace.jsonl" if (case / "trace.jsonl").is_file() else None,
           "transcript": "transcript.jsonl" if (case / "transcript.jsonl").is_file() else None,
           "runner": runner, "files": written, "starting_files": sorted(starting or {}), "tool": TOOL}
    (case / "context.json").write_text(json.dumps(ctx, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def program_result(exp: Experiment, c: dict, kind: str, prompt: dict | None, **case) -> tuple[str, str]:
    """Run a program check on one case, in a fresh folder that is deleted afterwards."""
    prog = exp.program_path(c)
    tmp = Path(tempfile.mkdtemp(prefix="skill-eval-lite-check-", dir=safe_temp_parent()))
    try:
        folder = tmp / "case"
        write_case(folder, c, kind, prompt, **case)
        timeout = c.get("timeout_seconds") or PROGRAM_TIMEOUT
        result, reason = run_program(prog.resolve(), folder, timeout=timeout, cwd=folder, isolated=True)
        return result, Redactor(folder).text(reason)[:500]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def program_selftest(exp: Experiment) -> tuple[list[str], list[str]]:
    """Each program check on every reference it applies to (a product check)
    and on each of its fixtures: (errors, a note for each check)."""
    errors, notes = [], []
    prompts = [exp.prompts[p] for p in exp.development + exp.held_out if p in exp.prompts]
    for c in exp.program_checks():
        prog, cid = exp.program_path(c), c.get("id")
        if not prog or not prog.is_file():
            continue
        refs = passed = 0
        if c.get("object") == "product":
            for p in prompts:
                if not p.get("reference") or not check_applies(c, p):
                    continue
                refs += 1
                r, why = program_result(exp, c, "reference", p, output=str(p["reference"]).strip() + "\n", starting=starting_files(exp, p))
                if r == "pass":
                    passed += 1
                else:
                    errors.append(f"Check {cid!r} gives {r} on the reference of {p.get('id')} ({why or 'no reason given'}). "
                                  "A check that fails a known-good output is set up wrong: fix its program, or the reference.")
        fixtures, good = program_fixtures(prog.parent), 0
        for d, e in fixtures:
            want = e.get("expect")
            if want not in ("pass", "fail", "n/a"):
                errors.append(f"Check {cid!r}: fixture {d.name} needs an expect.json that says what its program should give: "
                              '{"expect": "fail", "note": "..."} (or "pass", or "n/a").')
                continue
            p = exp.prompts.get(e.get("prompt")) if e.get("prompt") else None
            if e.get("prompt") and not p:
                errors.append(f"Check {cid!r}: fixture {d.name} names the prompt {e['prompt']!r}, which the experiment doesn't have.")
                continue
            r, why = program_result(exp, c, "fixture", p, fixture=d, starting=starting_files(exp, p) if p else None)
            if r == want:
                good += 1
            else:
                errors.append(f"Check {cid!r}: fixture {d.name} should give {want}, but its program gave {r} ({why or 'no reason given'}).")
        s = lambda n, w: f"{n} {w}" + ("" if n == 1 else "s")  # noqa: E731
        notes.append(f"{cid}: " + (f"passes {passed} of {s(refs, 'reference')}; " if c.get("object") == "product"
                                   else "a process check, so it isn't run on the references (they have no trace); ")
                     + f"{good} of {s(len(fixtures), 'fixture')} as expected.")
    return errors, notes


def bundle_steps(o: dict) -> list[dict]:
    """A bundle output's trace as trace.jsonl's steps, for a run folder that has lost its files."""
    out = []
    for st in o.get("trace") or []:
        mark = st[2] if len(st) > 2 else ""
        out.append({"tool": st[0], "detail": st[1] if len(st) > 1 else "", "error": mark in ("error", "refused"),
                    **({"refused": True} if mark == "refused" else {})})
    return out


def score_programs(exp: Experiment, out: Out, again: bool = False, only: set | None = None, jobs: int = 4) -> dict:
    """Run the experiment's program checks on each output in a run folder
    that has no result for the check as it is now (or on all, with again),
    and on the references; keep the results in the bundle and beside each
    output, and the programs in the run folder's checks/. A failed or
    timed-out run is not given to the program: the wizard fails every check
    on it, as it does the built-in ones."""
    checks = [c for c in exp.program_checks() if not only or c.get("id") in only]
    done = {"outputs": 0, "references": 0, "checks": len(checks)}
    if not checks or not out.bundle:
        return done
    for folder in sorted({PurePosixPath(c["program"]).parent.as_posix() for c in checks}):
        dst = out.path / folder
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(exp.base / folder, dst, ignore=shutil.ignore_patterns("__pycache__"))
    files = out.bundle.get("files", {})
    have = {(r["check"], r["prompt"], r["round"], r["repeat"]): r for r in out.bundle.get("program_results", [])}
    refs = {(r["check"], r["prompt"]): r for r in out.bundle.get("program_reference_results", [])}
    tasks = []
    for o in out.bundle.get("outputs", []):
        p = exp.prompts.get(o["prompt"])
        if not p or o.get("status") != "ok":
            continue
        for c in checks:
            if check_applies(c, p) and (again or not program_current(c, o, have.get((c["id"], o["prompt"], o["round"], o["repeat"])))):
                tasks.append(("output", c, p, o))
    for pid in exp.development + exp.held_out:
        p = exp.prompts.get(pid)
        if not p or not p.get("reference"):
            continue
        for c in checks:
            old = refs.get((c["id"], pid))
            if c.get("object") == "product" and check_applies(c, p) and (again or not old or old.get("version") != program_version(c)):
                tasks.append(("reference", c, p, None))

    def work(t):
        kind, c, p, o = t
        v = program_version(c)
        if kind == "reference":
            r, why = program_result(exp, c, "reference", p, output=str(p["reference"]).strip() + "\n", starting=starting_files(exp, p))
            return kind, {"check": c["id"], "version": v, "prompt": p["id"], "result": r, "reason": why, "when": now()}
        folder = out.path / "outputs" / o["prompt"] / o["round"] / str(o["repeat"])
        output = (folder / "output.md").read_text(encoding="utf-8", errors="replace") if (folder / "output.md").is_file() else o.get("output", "")
        trace = folder / "trace.jsonl" if (folder / "trace.jsonl").is_file() else bundle_steps(o)
        r, why = program_result(exp, c, "output", p, output=output, trace=trace,
                                transcript=out.path / "transcripts" / f"{o['prompt']}__{o['round']}__{o['repeat']}.jsonl",
                                files=folder / "files", starting=starting_files(exp, p, files), runner=o.get("runner"))
        e = {"check": c["id"], "version": v, "prompt": o["prompt"], "round": o["round"], "repeat": o["repeat"], "result": r,
             "reason": why, "when": now(), "output_when": o.get("when"),
             "added_after_run": (o.get("program_checks") or {}).get(c["id"]) != v}
        if folder.is_dir():
            (folder / "checks").mkdir(exist_ok=True)
            (folder / "checks" / f"{c['id']}.json").write_text(json.dumps(
                {**e, "program": c["program"], "sha256": c.get("sha256"), "params": c.get("params") or {}, "tool": TOOL},
                indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        return kind, e

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        for kind, e in pool.map(work, tasks):
            if kind == "reference":
                refs[(e["check"], e["prompt"])] = e
                done["references"] += 1
            else:
                have[(e["check"], e["prompt"], e["round"], e["repeat"])] = e
                done["outputs"] += 1
    with out.lock:
        out.bundle["program_results"] = sorted(have.values(), key=lambda r: (r["check"], r["prompt"], r["round"], r["repeat"]))
        out.bundle["program_reference_results"] = sorted(refs.values(), key=lambda r: (r["check"], r["prompt"]))
        out.save()
    return done


def results_text(done: dict) -> str:
    return (f"{done['outputs']} result{'s' if done['outputs'] != 1 else ''} on the outputs and "
            f"{done['references']} on the references")


def say_program_results(exp: Experiment, out: Out, only: set | None = None):
    """Each program check's results in a run folder, round by round."""
    for c in exp.program_checks():
        if only and c["id"] not in only:
            continue
        v = program_version(c)
        by_round: dict = {}
        for r in out.bundle.get("program_results", []):
            if r["check"] == c["id"] and r.get("version") == v:
                n = by_round.setdefault(r["round"], {})
                n[r["result"]] = n.get(r["result"], 0) + 1
        parts = [f"{rd}: " + ", ".join(f"{n} {w}" for w, n in sorted(cnt.items())) for rd, cnt in sorted(by_round.items())]
        rf = [r for r in out.bundle.get("program_reference_results", []) if r["check"] == c["id"] and r.get("version") == v]
        say(f"  {c['id']:28} " + (" · ".join(parts) or "no outputs it applies to yet")
            + (f"  (references: {sum(r['result'] == 'pass' for r in rf)} of {len(rf)} pass)" if rf else ""))


def cmd_score(a) -> int:
    exp = load(a.experiment)
    errors, _ = exp.problems()
    if errors:
        say("This experiment's checks can't be run yet:")
        for e in errors:
            say("  " + e)
        say(fix_then_check(a.experiment))
        return 1
    if not exp.program_checks():
        say(f"{exp.path.name} has no program checks (kind = \"program\"), so there is nothing to score here.\n"
            "The wizard runs the other checks itself when you load the bundle.")
        return 0
    only = {x.strip() for x in a.checks.split(",")} if a.checks else None
    unknown = sorted((only or set()) - {c["id"] for c in exp.program_checks()})
    if unknown:
        raise Fail(f"{exp.path.name} has no program check called {', '.join(unknown)}. "
                   f"Its program checks are: {', '.join(c['id'] for c in exp.program_checks())}.")
    folder = Path(a.out) if a.out else Path("runs") / exp.name
    if folder.is_file() and folder.name == "bundle.json":
        folder = folder.parent
    out = Out(folder)
    if not out.bundle:
        raise Fail(f"There is no bundle.json in {folder}, so there are no outputs to score yet.\n"
                   "Run the experiment first, or name its run folder. "
                   + in_claude("run-experiment", f"{PY} run_ab.py score {a.experiment} --out runs/<name>") + ".")
    st_errors, _ = program_selftest(exp)
    if st_errors:
        say("A program check doesn't pass its own tests, so its results on the outputs couldn't be trusted:")
        for e in st_errors:
            say("  " + e)
        say("Fix it, then check it again. " + in_claude("check-authoring", f"{PY} run_ab.py check {a.experiment}") + ".")
        return 1
    done = score_programs(exp, out, again=a.again, only=only, jobs=a.jobs)
    if done["outputs"] or done["references"]:
        say(f"Ran the program checks in {out.path} where they had no result for the check as it is now: {results_text(done)}.")
    else:
        say(f"Every output in {out.path} already has a result from each program check as it is now "
            "(add --again to run them again).")
    say_program_results(exp, out, only)
    v = {c["id"]: program_version(c) for c in exp.program_checks()}
    added = sorted({r["check"] for r in out.bundle.get("program_results", []) if r.get("added_after_run") and v.get(r["check"]) == r.get("version")})
    if added:
        say(f"\nThe runs were made without {', '.join(added)} as it is now: it was added or changed after the runs. "
            "The wizard marks its results. Your report should call them exploratory: they were not part of the test "
            "you froze.")
    as_run = (out.bundle.get("experiment") or {}).get("text")
    if as_run is not None and design_text(as_run) != design_text(exp.text):
        say(f"\n{a.experiment} is not the experiment file these runs were made with. In the wizard, load {a.experiment} "
            f"in step 1 (freeze it again if it asks), then {out.bundle_path} in step 3. " + in_claude("wizard", OPEN_WIZARD) + ".")
    else:
        say(f"\nNext, load {out.bundle_path} in the wizard's step 1. " + in_claude("wizard", OPEN_WIZARD) + ".")
    return 0


# --- judge ----------------------------------------------------------------

# The words a verdict may end on: an LLM test's, and the judge's.
VERDICT_WORDS = ("PASS", "FAIL", "UNKNOWN")
DECISION_WORDS = ("LEFT", "RIGHT", "TIE", "UNKNOWN")
_LABEL = re.compile(r"(?:final answer|verdict|decision|answer|result)\s*[:=\u2013\u2014-]\s*([A-Za-z]+)", re.I)
_NEGATION = re.compile(r"\bnot\b|n't\b|\bnever\b", re.I)


def last_line_word(text: str, words: tuple[str, ...]) -> tuple[str, str]:
    """The word a response ends on, and a note on how it was read. The last
    line that isn't blank, with Markdown emphasis, backticks, heading marks
    and trailing punctuation taken off, is read, in this order:
    1. exactly one of the words (in any case): that word;
    2. a label and one of the words (Verdict: PASS, Final answer - FAIL):
       that word, "read from a labelled last line";
    3. exactly one of the words, as a whole word, with no negation (not,
       n't, never) before it: that word, "read from the last line";
    4. otherwise UNKNOWN, "the last line was not ...".
    The suites' LLM tests and the judge both use it."""
    unknown = words[-1]
    lines = [l for l in (text or "").strip().split("\n") if l.strip() and not re.fullmatch(r"\s*(?:```|~~~)[\w-]*\s*", l)]
    line = lines[-1] if lines else ""
    line = re.sub(r"^\s*#+\s*", "", line)
    line = re.sub(r"[*_`]+", "", line).strip()
    line = re.sub(r"[.!?,;:]+$", "", line).strip()
    upper = {w.upper(): w for w in words}
    if line.upper() in upper:
        return upper[line.upper()], ""
    m = _LABEL.fullmatch(line)
    if m and m.group(1).upper() in upper:
        return upper[m.group(1).upper()], "read from a labelled last line"
    found = {}
    for w in words:
        for hit in re.finditer(r"\b" + w + r"\b", line, re.I):
            found.setdefault(w, hit.start())
    if len(found) == 1:
        w, at = next(iter(found.items()))
        if not _NEGATION.search(line[:at]):
            return w, "read from the last line"
    return unknown, "the last line was not " + ", ".join(words[:-1]) + " or " + words[-1]


def parse_decision(text: str) -> tuple[str, str]:
    return last_line_word(text, DECISION_WORDS)


def judge_text(exp: Experiment, files: dict, p: str, left: dict, right: dict) -> str:
    prompt = exp.prompts.get(p, {})
    parts = [str(exp.judge.get("prompt", "")).strip(), "", "## The request", "", str(prompt.get("text", "")).strip()]
    for f in prompt.get("files", []):
        body = files.get(f"{p}:{f}")
        if body is not None:
            parts += ["", f"## Starting file: {f}", "", body.strip()]

    def draft(o):
        if not o or o.get("status") != "ok":
            return "(No output: the run " + ("timed out" if o and o.get("status") == "timeout" else "failed") + ".)"
        return o.get("output", "").strip() or "(empty)"
    parts += ["", "## Left", "", draft(left), "", "## Right", "", draft(right), ""]
    return "\n".join(parts)


def cmd_judge(a) -> int:
    folder = Path(a.folder)
    if folder.is_file() and folder.name == "bundle.json":
        folder = folder.parent
    out = Out(folder)
    if not out.bundle:
        raise Fail(f"There is no bundle.json in {folder}, so there is nothing to judge yet.\n"
                   "Run the experiment first. "
                   + in_claude("run-experiment", f"{PY} run_ab.py run <experiment file> --assistant <folder>") + ".")
    exp = Experiment(Path(out.bundle["experiment"]["name"]), out.bundle["experiment"]["text"])
    if not exp.judge.get("prompt"):
        raise Fail("The experiment has no [judge] prompt, so the LLM judge has nothing to ask.\n"
                   "Add a [judge] prompt to the experiment file (the README's \"The experiment file\" shows how).")
    made_by = bundle_runner(out.bundle) or "claude-code"
    name = runner_name(a, made_by)
    with open_runner(name, a) as runner:
        runner.require_login()
        if name == "codex":
            model = run_model(runner, a, {"codex_model": exp.judge.get("codex_model"), "model": exp.judge.get("model")})
        else:
            model = run_model(runner, a, {"claude_model": exp.judge.get("claude_model"), "model": exp.judge.get("model") or exp.model.get("model")})
        outputs = {(o["prompt"], o["round"], o["repeat"]): o for o in out.bundle["outputs"]}
        have = {(j["comparison"], j["prompt"], j["repeat"], j.get("requested_model", j.get("model"))): j for j in out.bundle.get("judge", [])}
        pairs = []
        wanted = a.comparisons.split(",") if a.comparisons else None
        # The development prompts are judged on the experiment's comparisons;
        # the held-out prompts, with --held-out, on the confirmation (the
        # baseline against each round run on them), as the wizard pairs them.
        sets = [(c, exp.development) for c in exp.data.get("comparisons", [])]
        if a.held_out:
            sets += [(c, exp.held_out) for c in held_out_comparisons(exp, outputs)]
        for c, prompts in sets:
            cfg = f"{c['baseline']}|{c['new']}"
            if wanted and cfg.replace("|", "-") not in wanted and cfg not in wanted:
                continue
            for (p, r, k), o in sorted(outputs.items()):
                if r != c["baseline"] or (p, c["new"], k) not in outputs or p not in prompts:
                    continue
                if (cfg, p, k, model) in have and not a.again:
                    continue
                rng = random.Random(f"{exp.seed}:{cfg}:{p}:{k}")
                left = c["baseline"] if rng.random() < 0.5 else c["new"]
                pairs.append((cfg, c, p, k, left))
        if not pairs:
            say(f"Every pair is already judged by {model} (add --again to judge them again).")
            return 0
        (folder / "judge").mkdir(exist_ok=True)
        (folder / "judge" / "prompt.md").write_text(str(exp.judge["prompt"]).strip() + "\n", encoding="utf-8")
        say(f"Judging {len(pairs)} blind pairs with {model}, {a.jobs} at a time ({runner.label} {runner.version}). "
            "Which side each draft is on is chosen at random and recorded.")
        if name != made_by:
            say(f"Note: the runs were made with {RUNNER_LABEL[made_by]}; the judge runs on {runner.label}.")
        registry: set = set()
        lock = out.lock
        done = [0]
        stop = threading.Event()
        problems = []

        def work(item):
            cfg, c, p, k, left = item
            if stop.is_set():
                return
            right = c["new"] if left == c["baseline"] else c["baseline"]
            text = judge_text(exp, out.bundle.get("files", {}), p, outputs[(p, left, k)], outputs[(p, right, k)])
            tmp = Path(tempfile.mkdtemp(prefix="skill-eval-lite-judge-", dir=safe_temp_parent()))
            try:
                when = now()
                run = runner.run(tmp, text, model=model, timeout=a.timeout, tools=[], allowed=[], budget=a.budget,
                                 project_skills=set(), registry=registry, shell=False)
                red = Redactor(tmp)
                response = red.text(run.final.strip())
                if run.breach:
                    problems.append("STOPPED: the judge's run was not isolated: " + "; ".join(run.breach))
                    stop.set()
                    return
                if run.not_logged_in:
                    problems.append(CODEX_NOT_LOGGED_IN if name == "codex" else NOT_LOGGED_IN)
                    stop.set()
                    return
                ok = run.ok
                decision, note = parse_decision(response) if ok else ("UNKNOWN", "the judge's run " + ("timed out" if run.timed_out else "failed"))
                winner = {"LEFT": left, "RIGHT": right, "TIE": "tie"}.get(decision, "unknown")
                entry = {"comparison": cfg, "prompt": p, "repeat": k, "shown_left": left, "decision": decision, "winner": winner,
                         "note": note, "response": response, "model": run.model_seen or model, "when": when,
                         "seconds": run.seconds, "cost_usd": run.cost_usd,
                         "status": "ok" if ok else ("timeout" if run.timed_out else "failed"), "requested_model": model,
                         "runner": runner.name}
                if run.usage:
                    entry["usage"] = run.usage
                d = folder / "judge" / cfg.replace("|", "-")
                d.mkdir(parents=True, exist_ok=True)
                (d / f"{p}__{k}.json").write_text(json.dumps({**entry, "input": red.text(text), "command": run.command,
                                                              "isolation": run.isolation, **runner.record(), "tool": TOOL},
                                                             indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
                with lock:
                    have[(cfg, p, k, model)] = entry
                    out.bundle["judge"] = sorted(have.values(), key=lambda j: (j["comparison"], j["prompt"], j["repeat"]))
                    done[0] += 1
                    # The verdict isn't shown (0.2.1): people judge the same pairs blind,
                    # often with this window open. It is in the bundle and the pair's file.
                    say(f"[{done[0]}/{len(pairs)}] {cfg.replace('|', ' vs '):8} {p:28} repeat {k}  "
                        + ("judged" if ok and decision != "UNKNOWN" else "no verdict") + (f"  {run.seconds:.0f} s" if run.seconds else ""))
                    out.save()
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

        with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as pool:
            list(pool.map(work, pairs))
    with out.lock:
        out.save()
    if problems:
        say("\n" + problems[0], err=True)
        return 3
    say(f"\nThe judge's verdicts are saved in {out.bundle_path} (and one file per pair in {folder / 'judge'}). "
        "They aren't shown here, so that everyone can judge the same pairs blind first: the wizard's step 5 sets them "
        "beside yours.")
    say("Next: open wizard.html and load the bundle in step 1." if name == "codex" else
        "Next, load the bundle in the wizard's step 1. " + in_claude("wizard", OPEN_WIZARD) + ".")
    return 0


# --- doctor ---------------------------------------------------------------

PROBE_WORD = "heliotrope"
# The public repository's VERSION, which doctor and status compare with this
# one. SKILL_EVAL_LITE_UPDATE_URL changes where they look; "off" turns it off.
UPDATE_URL = "https://raw.githubusercontent.com/vanderbilt-ms-ai/skill-eval-lite/main/VERSION"


def _version_key(v: str):
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", (v or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def fetch(url: str, timeout: float = 3.0, limit: int = 64) -> tuple[int | None, bytes | None]:
    """GET one address: (status, body), (404, None) when it isn't there, and
    (None, None) offline or past the time-out. In a thread of its own, so that
    a slow name lookup can't hold anything up. It sends nothing but the
    request itself."""
    import urllib.error
    import urllib.request
    got: list[tuple[int | None, bytes | None]] = []

    def go():
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "skill-eval-lite/" + VERSION})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                got.append((getattr(r, "status", None) or 200, r.read(limit)))
        except urllib.error.HTTPError as e:
            got.append((e.code, None))
        except Exception:
            got.append((None, None))
    th = threading.Thread(target=go, daemon=True)
    th.start()
    th.join(timeout + 1)
    return got[0] if got else (None, None)


def remote_version(timeout: float = 3.0) -> str | None:
    """The public repository's VERSION; None when it can't be read (offline,
    say) or the check is turned off. One small request, which sends nothing
    but the version asked for."""
    url = os.environ.get("SKILL_EVAL_LITE_UPDATE_URL", UPDATE_URL)
    if url.strip().lower() in ("", "off"):
        return None
    code, body = fetch(url, timeout)
    text = (body or b"").decode("utf-8", "replace").strip()
    return text if code == 200 and _version_key(text) else None


def newer_version(timeout: float = 3.0) -> str | None:
    """The public repository's version when it is newer than this one; None
    when it isn't, or when it can't be read."""
    remote = remote_version(timeout)
    mine, theirs = _version_key(VERSION), _version_key(remote or "")
    return remote if mine and theirs and theirs > mine else None


# --- updates --------------------------------------------------------------
#
# Skill Eval Lite and the course's brief folders beside it, against what is
# published (Simon, 2026-11-07: "check whether the Shared I and Personal I
# folders are up to date (and that skill-eval-lite is up to date) ... so if
# we push further changes, students can pull them in and keep running").
# A brief folder made since 0.2.0 holds pack.json, which the course site
# also publishes beside its ZIP as <id>-for-ai.json (the course's
# tools/project_pack.py); an older one is known by its SKILL.md.

PACK_SCHEMA = "ai5500-project-pack/1"
ZIP_URL = "https://github.com/vanderbilt-ms-ai/skill-eval-lite/archive/refs/heads/main.zip"
OLD_REVISION = re.compile(r"This copy holds revision (\d+)")
OLD_PAGE = re.compile(r"The project's page: (https?://\S+?\.html)")
# What an update never touches: the student's work in Skill Eval Lite's
# folder or in a brief folder.
SELF_KEEP = ("experiments/", "runs/", ".state/", ".git/", ".git", ".claude/settings.local.json")
BRIEF_KEEP = ("progress.md", "ai-use-log.md", "notes.md", "notes/", "previous/")
ONE_DAY = 24 * 3600
NEWER = ("newer", "changed", "old-copy")


def state_dir() -> Path:
    """Where Skill Eval Lite keeps its own small state (git ignores it)."""
    return Path(os.environ.get("SKILL_EVAL_LITE_STATE") or HERE / ".state")


def workspace_dir(given: str | None = None) -> Path:
    """The folder that holds Skill Eval Lite and the brief folders."""
    return Path(given or os.environ.get("SKILL_EVAL_LITE_WORKSPACE") or HERE.parent).resolve()


def _beside(url: str, ext: str) -> str:
    """A project page's address -> its pack's ZIP or manifest beside it."""
    base, name = url.rsplit("/", 1)
    return f"{base}/{name.rsplit('.', 1)[0]}-for-ai{ext}"


def brief_folders(workspace: Path) -> list[dict]:
    """The course's brief folders beside Skill Eval Lite."""
    out = []
    try:
        kids = sorted(d for d in workspace.iterdir() if d.is_dir())
    except OSError:
        return out
    for d in kids:
        if d.resolve() == HERE:
            continue
        try:
            pack = json.loads((d / "pack.json").read_text(encoding="utf-8")) if (d / "pack.json").is_file() else None
        except (OSError, ValueError):
            pack = None
        if isinstance(pack, dict) and pack.get("schema") == PACK_SCHEMA:
            urls = pack.get("urls") or {}
            out.append({"folder": d, "pack": pack, "name": pack.get("name") or d.name,
                        "revision": (pack.get("revision") or {}).get("n"), "made": pack.get("made"),
                        "manifest": urls.get("manifest"), "zip": urls.get("zip"), "page": urls.get("page")})
            continue
        skill = d / "SKILL.md"
        try:
            text = skill.read_text(encoding="utf-8", errors="replace") if skill.is_file() else ""
        except OSError:
            text = ""
        rev, page = OLD_REVISION.search(text), OLD_PAGE.search(text)
        if rev and page and re.search(r"^name: ai5500-", text[:400], re.M):
            title = re.search(r"^# ([^:\n]+)", text, re.M)
            url = page.group(1)
            out.append({"folder": d, "pack": None, "name": title.group(1).strip() if title else d.name,
                        "revision": int(rev.group(1)), "made": None,
                        "manifest": _beside(url, ".json"), "zip": _beside(url, ".zip"), "page": url})
    return out


def check_brief(b: dict, timeout: float = 3.0) -> dict:
    """One brief folder against the course site's manifest."""
    res = {"folder": b["folder"].name, "name": b["name"], "revision": b["revision"], "made": b["made"],
           "pack": b["pack"] is not None, "page": b["page"], "zip": b["zip"]}
    if not b["manifest"]:
        return {**res, "status": "unknown", "reason": "its pack.json names no manifest"}
    code, body = fetch(b["manifest"], timeout, limit=4_000_000)
    if code == 404:
        return {**res, "status": "unknown", "reason": "the course site publishes no manifest for it yet"}
    try:
        pub = json.loads(body or b"")
        if not isinstance(pub, dict) or pub.get("schema") != PACK_SCHEMA:
            raise ValueError
    except ValueError:
        why = "couldn't reach the course site" if code is None else f"the course site answered {code}"
        return {**res, "status": "unknown", "reason": why}
    rev = pub.get("revision") or {}
    res["published"] = {"revision": rev.get("n"), "date": rev.get("date"), "made": pub.get("made")}
    res["zip"] = (pub.get("urls") or {}).get("zip") or b["zip"]
    have, now = int(b["revision"] or 0), int(rev.get("n") or 0)
    if now > have:
        return {**res, "status": "newer"}
    if b["pack"] is None:
        return {**res, "status": "old-copy"}
    mine, theirs = b["pack"].get("files") or {}, pub.get("files") or {}
    changed = sorted(f for f in set(mine) | set(theirs) if mine.get(f) != theirs.get(f))
    if changed:
        return {**res, "status": "changed", "changed": changed}
    return {**res, "status": "current"}


def check_self(timeout: float = 3.0) -> dict:
    """Skill Eval Lite against GitHub's VERSION."""
    res = {"version": VERSION, "kind": "git" if (HERE / ".git").exists() else "zip"}
    if os.environ.get("SKILL_EVAL_LITE_UPDATE_URL", UPDATE_URL).strip().lower() in ("", "off"):
        return {**res, "status": "unknown", "reason": "the check is turned off"}
    remote = remote_version(timeout)
    if remote is None:
        return {**res, "status": "unknown", "reason": "couldn't reach GitHub"}
    mine, theirs = _version_key(VERSION), _version_key(remote)
    return {**res, "published": remote, "status": "newer" if mine and theirs > mine else "current"}


def local_key(workspace: Path) -> dict:
    """What a cached check depends on: this version and the brief folders as
    they are, so that a check made before an update isn't reused after it."""
    return {"workspace": str(workspace), "version": VERSION,
            "briefs": {b["folder"].name: [b["revision"], (b["pack"] or {}).get("sha256")] for b in brief_folders(workspace)}}


def check_updates(workspace: Path, timeout: float = 3.0) -> dict:
    briefs = brief_folders(workspace)
    with ThreadPoolExecutor(max_workers=1 + len(briefs)) as pool:
        me = pool.submit(check_self, timeout)
        theirs = [pool.submit(check_brief, b, timeout) for b in briefs]
        report = {"checked": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                  "skill_eval_lite": me.result(), "briefs": [f.result() for f in theirs]}
    report["key"] = local_key(workspace)
    return report


def cached_updates(workspace: Path) -> dict | None:
    """The last check, if it was made in the last day for things as they are."""
    try:
        r = json.loads((state_dir() / "updates.json").read_text(encoding="utf-8"))
        when = dt.datetime.fromisoformat(r["checked"])
        age = (dt.datetime.now().astimezone() - when).total_seconds()
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return r if 0 <= age < ONE_DAY and r.get("key") == local_key(workspace) else None


def save_updates(report: dict) -> None:
    try:
        state_dir().mkdir(parents=True, exist_ok=True)
        (state_dir() / "updates.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def update_lines(r: dict) -> list[str]:
    me = r["skill_eval_lite"]
    lines = []
    if me["status"] == "newer":
        lines.append(f"Skill Eval Lite: {me['published']} is out. This copy is {me['version']}.")
    elif me["status"] == "current":
        lines.append(f"Skill Eval Lite {me['version']}: up to date.")
    else:
        lines.append(f"Skill Eval Lite {me['version']}: couldn't check ({me.get('reason')}).")
    for b in r["briefs"]:
        label, pub = f"{b['folder']} ({b['name']})", b.get("published") or {}
        if b["status"] == "newer":
            lines.append(f"{label}: revision {pub.get('revision')} ({pub.get('date')}) is out. This copy is revision {b['revision']}.")
        elif b["status"] == "changed":
            few = ", ".join(b["changed"][:4]) + (f" and {len(b['changed']) - 4} more" if len(b["changed"]) > 4 else "")
            lines.append(f"{label}: revision {b['revision']}, with {len(b['changed'])} of the course's files changed "
                         f"since this copy ({few}).")
        elif b["status"] == "old-copy":
            lines.append(f"{label}: revision {b['revision']}, in the older form of the folder with no pack.json, so its "
                         "files can't be compared. Bringing in the course site's copy is safe: your own files stay.")
        elif b["status"] == "current":
            lines.append(f"{label}: up to date (revision {b['revision']}).")
        else:
            lines.append(f"{label}: couldn't check ({b.get('reason')}).")
    if not r["briefs"]:
        lines.append(f"No brief folders beside Skill Eval Lite (it looked in {r['key']['workspace']}).")
    return lines


def update_needed(r: dict) -> list[str]:
    """What is newer, in a few words each."""
    out = []
    me = r["skill_eval_lite"]
    if me["status"] == "newer":
        out.append(f"Skill Eval Lite {me['published']} is out (this copy is {me['version']})")
    for b in r["briefs"]:
        if b["status"] == "newer":
            out.append(f"{b['folder']} ({b['name']}) has revision {(b.get('published') or {}).get('revision')}")
        elif b["status"] in ("changed", "old-copy"):
            out.append(f"{b['folder']} ({b['name']}) has a newer copy")
    return out


def cmd_updates(a) -> int:
    workspace = workspace_dir(a.workspace)
    if a.hook:
        # For Claude Code's SessionStart hook: at most one check a day, a line
        # for Claude when something is newer, nothing otherwise, and never a
        # failure that could get in the way of a session.
        try:
            r = None if a.again else cached_updates(workspace)
            if r is None:
                r = check_updates(workspace, timeout=2.5)
                save_updates(r)
            needed = update_needed(r)
            if needed:
                print("Skill Eval Lite's update check: " + "; ".join(needed) + ". Before anything else, tell the "
                      "student this in a line and offer /check-updates, which brings it in and keeps their own work.")
        except Exception:
            pass
        return 0
    r = None if a.again else cached_updates(workspace)
    fresh = r is None
    if fresh:
        r = check_updates(workspace)
        save_updates(r)
    if a.json:
        print(json.dumps(r, indent=2))
        return 0
    for line in update_lines(r):
        say(line)
    if update_needed(r):
        say("Bringing them in keeps your own work. "
            + in_claude("check-updates", f"{PY} run_ab.py update --self for Skill Eval Lite, "
                                         f"{PY} run_ab.py update --brief ../<folder> for a brief folder") + ".")
    if not fresh:
        say(f"(Checked {r['checked'][:16].replace('T', ' ')}. --again checks now.)")
    return 0


def _zip_files(body: bytes, where: str) -> tuple[str, dict[str, bytes]]:
    """A downloaded ZIP's files under its one top folder: (top, {path: bytes})."""
    import io
    import zipfile
    try:
        z = zipfile.ZipFile(io.BytesIO(body))
    except zipfile.BadZipFile:
        raise Fail(f"What came from {where} isn't a ZIP file.")
    names = [n for n in z.namelist() if not n.endswith("/")]
    tops = {n.split("/", 1)[0] for n in names}
    if len(tops) != 1 or any("/" not in n for n in names):
        raise Fail(f"The ZIP from {where} doesn't hold one folder.")
    top = tops.pop()
    files = {}
    for n in names:
        rel = n.split("/", 1)[1]
        parts = PurePosixPath(rel).parts
        if not rel or rel.startswith("/") or ".." in parts or ":" in rel or "\\" in rel:
            raise Fail(f"The ZIP from {where} has a file outside its folder: {n}")
        files[rel] = z.read(n)
    return top, files


def _kept(rel: str, keep: tuple[str, ...]) -> bool:
    return any(rel == k.rstrip("/") or (k.endswith("/") and rel.startswith(k)) for k in keep)


def _apply(root: Path, files: dict[str, bytes], keep: tuple[str, ...], backup: Path, dry: bool,
           gone: list[str] = ()) -> dict[str, list[str]]:
    """Write `files` into root, never touching what `keep` names; each file it
    replaces or takes away is copied into `backup` first. Nothing is deleted
    without a copy kept."""
    done = {"replaced": [], "added": [], "same": [], "kept": [], "moved": []}
    for rel in sorted(files):
        if _kept(rel, keep):
            done["kept"].append(rel)
            continue
        target = root / rel
        if target.is_file() and target.read_bytes() == files[rel]:
            done["same"].append(rel)
            continue
        done["replaced" if target.exists() else "added"].append(rel)
        if dry:
            continue
        if target.exists():
            (backup / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup / rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(files[rel])
    for rel in gone:
        target = root / rel
        if _kept(rel, keep) or rel in files or not target.is_file():
            continue
        done["moved"].append(rel)
        if not dry:
            (backup / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target), str(backup / rel))
    return done


def _few(names: list[str], n: int = 5) -> str:
    return ", ".join(names[:n]) + (f" and {len(names) - n} more" if len(names) > n else "")


def update_self(dry: bool) -> None:
    if (HERE / ".git").exists():
        if not shutil.which("git"):
            raise Fail("This copy of Skill Eval Lite is a git copy, but git isn't installed. "
                       + in_claude("get-ready", "install it from https://git-scm.com/downloads") + ".")
        dirty = subprocess.run(["git", "-C", str(HERE), "status", "--porcelain", "--untracked-files=no"],
                               capture_output=True, text=True).stdout.strip()
        if dirty:
            raise Fail("Skill Eval Lite's own files have changes in this copy, so `git pull` would stop:\n" + dirty
                       + "\nKeep a copy of anything you changed, then put each file back and update again. "
                       + in_claude("check-updates", f"git checkout -- <file> for each file, then {PY} run_ab.py update --self") + ".")
        if dry:
            say("Would run `git pull --ff-only` in this folder. Your experiments/ and runs/ aren't in git, so they stay.")
            return
        r = subprocess.run(["git", "-C", str(HERE), "pull", "--ff-only"], capture_output=True, text=True)
        say((r.stdout + r.stderr).strip())
        if r.returncode:
            raise Fail("`git pull` didn't finish. Its message is above.")
        new = (HERE / "VERSION").read_text(encoding="utf-8").strip() if (HERE / "VERSION").is_file() else "?"
        say(f"Skill Eval Lite is now {new}. RELEASE.md says what changed.")
        return
    url = os.environ.get("SKILL_EVAL_LITE_ZIP_URL", ZIP_URL)
    code, body = fetch(url, timeout=60, limit=200_000_000)
    if code != 200 or not body:
        raise Fail(f"Couldn't download Skill Eval Lite from {url}"
                   + (" (offline?)." if code is None else f" (the site answered {code})."))
    _, files = _zip_files(body, url)
    if "run_ab.py" not in files or "VERSION" not in files:
        raise Fail(f"The ZIP from {url} isn't Skill Eval Lite: it has no run_ab.py or VERSION.")
    new = files["VERSION"].decode("utf-8", "replace").strip()
    backup = state_dir() / f"before-update-{VERSION}"
    done = _apply(HERE, files, SELF_KEEP, backup, dry)
    head = f"Skill Eval Lite {VERSION} -> {new}"
    if dry:
        say(f"{head}: would replace {len(done['replaced'])} files and add {len(done['added'])}. "
            "experiments/, runs/ and .claude/settings.local.json would stay as they are.")
        return
    say(f"{head}: replaced {len(done['replaced'])} files and added {len(done['added'])}. Your experiments/, runs/ "
        "and .claude/settings.local.json are as they were.")
    if done["replaced"]:
        say(f"The files it replaced are kept in {backup}.")
    say("RELEASE.md says what changed.")


def update_brief(folder: Path, dry: bool) -> None:
    folder = folder.resolve()
    found = [b for b in brief_folders(folder.parent) if b["folder"].resolve() == folder]
    if not found:
        raise Fail(f"{folder} isn't one of the course's brief folders: it has no pack.json, and no SKILL.md naming "
                   "its revision and its page.")
    b = found[0]
    st = check_brief(b, timeout=10)
    if st["status"] == "current":
        say(f"{folder.name} is up to date (revision {b['revision']}). Nothing to do.")
        return
    url = st.get("zip") or b["zip"]
    code, body = fetch(url, timeout=60, limit=200_000_000)
    if code != 200 or not body:
        raise Fail(f"Couldn't download {url}" + (" (offline?)." if code is None else f" (the course site answered {code})."))
    _, files = _zip_files(body, url)
    try:
        pack = json.loads(files["pack.json"]) if "pack.json" in files else None
    except ValueError:
        pack = None
    old_rev = b["revision"]
    new_rev = ((pack or {}).get("revision") or {}).get("n") or (st.get("published") or {}).get("revision") or old_rev
    gone = sorted(set((b["pack"] or {}).get("files") or {}) - set(files))
    label = f"r{old_rev}-{b['made'] or dt.date.today().isoformat()}"
    backup = folder / "previous" / label
    # pack.json last, so that a copy stopped halfway still says it is the old one.
    course = {k: v for k, v in files.items() if k != "pack.json"}
    done = _apply(folder, course, BRIEF_KEEP, backup, dry, gone)
    if not dry and "pack.json" in files:
        (folder / "pack.json").write_bytes(files["pack.json"])
    tops = {n.split("/", 1)[0] for n in set(course) | set(gone) if not _kept(n, BRIEF_KEEP)}
    theirs = sorted(p.name + ("/" if p.is_dir() else "") for p in folder.iterdir()
                    if p.name not in tops and p.name not in ("previous", "pack.json"))
    head = (f"{folder.name}: revision {old_rev} -> {new_rev}" if new_rev != old_rev
            else f"{folder.name}: revision {old_rev}, brought up to date")
    rep_, add_, set_ = ("would replace", "add", "set aside") if dry else ("replaced", "added", "set aside")
    say(f"{head}: {rep_} {len(done['replaced'])} of the course's files, {add_} {len(done['added'])}"
        + (f" and {set_} {len(done['moved'])} it no longer has" if done["moved"] else "") + ".")
    if done["replaced"] or done["added"]:
        say(f"  Changed: {_few(done['replaced'] + done['added'])}.")
    if theirs:
        say(f"  Your own files {'would stay' if dry else 'stay'} as they are: {_few(theirs)}.")
    if not dry and (done["replaced"] or done["moved"]):
        say(f"  The course's files it replaced are kept in {folder.name}/previous/{label}/.")
    if not dry and new_rev != old_rev:
        say(f"  What changed is in revisions.md, under \"What changed in revision {new_rev}\". The course's rule on "
            "revisions lets you go by an earlier revision where it is better for you: say which, and for what, in "
            "progress.md.")


def cmd_update(a) -> int:
    if not a.self and not a.brief:
        raise Fail("Say what to update: --self for Skill Eval Lite, or --brief ../ai5500-shared-1 for a brief folder.")
    if a.self:
        update_self(a.dry_run)
    for f in a.brief or []:
        update_brief(Path(f), a.dry_run)
    return 0


def update_text(remote: str, codex: bool = False) -> str:
    update = f"{PY} run_ab.py update --self"
    return f"Skill Eval Lite {remote} is out; you have {VERSION}. " + (f"In this folder, run {update}." if codex else
                                                                       in_claude("check-updates", update) + ".")


def cmd_doctor(a) -> int:
    ok = True

    def line(good, what, detail=""):
        nonlocal ok
        ok = ok and good is not False
        mark = {True: "ok  ", False: "FIX ", None: "--  "}[good]
        say(f"  {mark} {what}" + (f": {detail}" if detail else ""))

    def fix_them() -> int:
        say("\nFix the lines marked FIX, then run this again. " + in_claude("get-ready", f"{PY} run_ab.py doctor") + ".")
        return 1

    codex = runner_name(a, None) == "codex"
    say(f"Skill Eval Lite {VERSION}")
    remote = newer_version()
    if remote:
        say("  NEW  " + update_text(remote, codex))
    line(True, "Python", sys.version.split()[0])
    g = shutil.which("git")
    line(bool(g), "git", git("--version", check=False).stdout.strip() if g else "not found: install git")
    if codex:
        ok = doctor_codex(a, line) and ok
        say("\nReady. To see where you are and what to do next:  python3 run_ab.py status" if ok else
            "\nFix the lines marked FIX, then run this again:  python3 run_ab.py doctor --runner codex")
        return 0 if ok else 1
    try:
        exe = find_claude(a.claude)
    except Fail as e:
        first, _, rest = str(e).partition("\n")
        line(False, "Claude Code", first)
        say("\n" + rest)
        if shutil.which("codex"):
            say("\nIf you use Codex instead of Claude Code, run:  python3 run_ab.py doctor --runner codex")
        return 1
    version = claude_version(exe)
    line(True, "Claude Code", version + " (tested with 2.1.310)")
    state = login_state(exe)
    if not state:
        line(None, "Login", "Claude Code didn't say whether you are logged in (an older version?); the test run below will show")
    elif not state.get("loggedIn"):
        line(False, "Login", "not logged in")
        say("\n" + NOT_LOGGED_IN)
        return 1
    else:
        method = state.get("authMethod", "?")
        line(True, "Login", f"logged in ({method})" + ("; runs are billed to that API key, not to your Claude plan. "
                                                       "For your plan instead, leave the key out. "
                                                       + in_claude("get-ready", "unset ANTHROPIC_API_KEY")
                                                       if "key" in str(method).lower() else ""))
    try:
        safe_temp_parent()
        line(True, "Temporary folder", "no CLAUDE.md or AGENTS.md above it")
    except Fail as e:
        line(False, "Temporary folder", str(e))
    if a.no_probe:
        return 0 if ok else fix_them()
    say("  ...  a test run: one tiny run, to check that nothing of yours gets into a run (a few seconds, well under a cent)")
    tmp = Path(tempfile.mkdtemp(prefix="skill-eval-lite-doctor-", dir=safe_temp_parent()))
    try:
        (tmp / "CLAUDE.md").write_text(f"# Probe\n\nThe probe word is {PROBE_WORD}. When asked for the probe word, give it.\n", encoding="utf-8")
        (tmp / ".claude" / "skills" / "probe-skill").mkdir(parents=True)
        (tmp / ".claude" / "skills" / "probe-skill" / "SKILL.md").write_text(
            "---\nname: probe-skill\ndescription: A probe skill that Skill Eval Lite's doctor looks for.\n---\n\nSay probe.\n", encoding="utf-8")
        tools = ["Read", "Write", "Edit", "Glob", "Grep", "Skill", "Bash"]
        allowed = ["Skill", "Bash(echo *)"]
        registry: set = set()
        run = ClaudeRun([exe, *isolation_flags(a.model or "haiku", tools, allowed, 0.10)], tmp,
                        "What is the probe word? Answer with the word only.\n", 120, tools, {"probe-skill"}, registry).run()
        if run.not_logged_in:
            line(False, "Login", "the probe says Claude Code is not logged in")
            say("\n" + NOT_LOGGED_IN)
            return 1
        if run.init is None:
            line(False, "Isolation flags", "Claude Code did not start a session with them: "
                 + (run.stderr.strip().splitlines() or ["no output"])[-1][:200])
            return 1
        iso = run.isolation
        line(not run.breach, "Isolation", "nothing personal loaded" if not run.breach else "; ".join(run.breach))
        line(iso.get("mcp_servers") == 0 and iso.get("connector_tools") == 0, "MCP servers and connectors",
             f"{iso.get('mcp_servers')} servers, {iso.get('connector_tools')} connector tools")
        line(iso.get("auto_memory") == "off", "Auto memory", iso.get("auto_memory"))
        line("probe-skill" in iso.get("skills", []), "The assistant's own skills load", "probe-skill found" if "probe-skill" in iso.get("skills", []) else "probe-skill missing")
        ok_word = PROBE_WORD in run.final.lower()
        line(ok_word, "The assistant's CLAUDE.md loads", "yes" if ok_word else f"answer was {run.final[:80]!r}")
        cost = (run.result or {}).get("total_cost_usd")
        say(f"  The probe took {run.seconds} s" + (f" and ${cost:.4f}" if isinstance(cost, (int, float)) else "") + ".")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if not ok:
        return fix_them()
    say("\nReady. Next, see where you are and what to do. " + in_claude(("shared-i", "personal-i"), f"{PY} run_ab.py status") + ".")
    return 0


def doctor_codex(a, line) -> bool:
    """doctor --runner codex: the version, the login, the settings that keep
    a run isolated (checked without calling a model), and one tiny probe run."""
    try:
        exe = find_codex(getattr(a, "codex", None))
    except Fail as e:
        line(False, "Codex", str(e).splitlines()[0])
        say("\n" + str(e))
        return False
    version = codex_version(exe)
    line(True, "Codex", f"{version} (tested with {CODEX_TESTED})")
    keys = [k for k in ("OPENAI_API_KEY", "CODEX_API_KEY") if os.environ.get(k)]
    if keys and not a.use_api_key:
        line(True, "API key", f"{keys[0]} is set, but runs leave it out and use your ChatGPT plan "
                              "(add --use-api-key to use the key, billed to it, instead)")
    if Path("/etc/codex").exists():
        line(None, "System settings", "/etc/codex exists. Settings there can reach every run; the check before each run "
                                     "stops one that loads anything")
    try:
        safe_temp_parent()
        line(True, "Temporary folder", "no CLAUDE.md or AGENTS.md above it")
    except Fail as e:
        line(False, "Temporary folder", str(e))
        return False
    good = True
    with CodexRunner(exe, a.use_api_key) as runner:
        logged, how = runner.login()
        if logged is False:
            line(False, "Login", "not logged in" if not a.use_api_key else how)
            say("\n" + (CODEX_NOT_LOGGED_IN if not a.use_api_key else "Set OPENAI_API_KEY, or leave out --use-api-key."))
            return False
        line(True if logged else None, "Login", (f"logged in with your {how}" if logged else "unknown: " + how)
             + ("; runs are billed to that API key, not to a ChatGPT plan" if how == "API key" else ""))
        line(not runner.feature_problems, "Codex features",
             "; ".join(runner.feature_problems) or "connectors (apps), plugins, hooks, memories, the shell snapshot, "
                                                   "browsers and image tools are off")
        line(not runner.mcp, "MCP servers", f"{len(runner.mcp)} configured")
        pers = len(runner.home.skills_off_personal)
        line(True, "Your own Codex folder", "not used: runs get a temporary one with only a link to your login"
             + (f"; {pers} skill{'s' if pers != 1 else ''} in ~/.agents/skills switched off" if pers else ""))
        if a.no_probe:
            return good and not runner.feature_problems and not runner.mcp
        say("  ...  a test run: one tiny Codex run, to check that nothing of yours gets into a run (a few seconds)")
        tmp = Path(tempfile.mkdtemp(prefix="skill-eval-lite-doctor-", dir=safe_temp_parent()))
        secret = "canary-" + hashlib.sha256(os.urandom(16)).hexdigest()[:16]
        canary = cache_base() / f"doctor-canary-{secret[-6:]}.txt"
        try:
            canary.write_text(secret + "\n", encoding="utf-8")
            (tmp / "CLAUDE.md").write_text("# Probe\n\n@./probe.md\n", encoding="utf-8")
            (tmp / "probe.md").write_text(f"The probe word is {PROBE_WORD}. When asked for the probe word, give it.\n", encoding="utf-8")
            (tmp / ".claude" / "skills" / "probe-skill").mkdir(parents=True)
            (tmp / ".claude" / "skills" / "probe-skill" / "SKILL.md").write_text(
                "---\nname: probe-skill\ndescription: A probe skill that Skill Eval Lite's doctor looks for.\n---\n\nSay probe.\n",
                encoding="utf-8")
            map_for_codex(tmp)
            prompt = (f"First run this shell command once: cat '{canary}'\n"
                      "Then answer this question: what is the probe word? Answer with the word only.\n")
            run = runner.run(tmp, prompt, model=getattr(a, "model", None) or CODEX_PROBE_MODEL, timeout=180,
                             registry=set(), shell=True, effort="low")
            if run.not_logged_in:
                line(False, "Login", "the probe says Codex is not logged in")
                say("\n" + CODEX_NOT_LOGGED_IN)
                return False
            iso = run.isolation
            good = not run.breach
            line(good, "Isolation", "nothing of yours loaded" if good else "; ".join(run.breach))
            line(iso.get("mcp_servers") == 0 and iso.get("connector_tools") == 0, "MCP servers and connectors",
                 f"{iso.get('mcp_servers')} servers, {iso.get('connector_tools')} connector tools")
            line("probe-skill" in iso.get("skills", []), "The assistant's own skills load (as .agents/skills)",
                 "probe-skill found" if "probe-skill" in iso.get("skills", []) else "probe-skill missing")
            if run.breach and not run.events:
                return False
            ok_word = PROBE_WORD in run.final.lower()
            line(ok_word, "The assistant's CLAUDE.md loads (as AGENTS.md, imports inlined)",
                 "yes" if ok_word else f"the answer was {run.final[:80]!r}" + (f" ({run.failure})" if not run.ok else ""))
            tries = [it for e in run.events if e.get("type") == "item.completed"
                     for it in [e.get("item") or {}] if it.get("type") == "command_execution" and str(canary) in str(it.get("command"))]
            if any(secret in str(it.get("aggregated_output")) for it in tries):
                line(False, "Your home folder", "a run could read a file in it. Don't run experiments; report this "
                                                "with your Codex version")
            elif tries:
                line(True, "Your home folder", "hidden from runs (the probe couldn't read a file there)")
            else:
                line(None, "Your home folder", "not tested: the probe didn't run the command")
            line(not (runner.home.path / "sessions").exists(), "Session saved", "no (runs are ephemeral)")
            u = run.usage
            say(f"  The probe took {run.seconds} s" + (f" and {u.get('input_tokens', 0):,} tokens in, "
                                                       f"{u.get('output_tokens', 0):,} out" if u else "") + ".")
            good = good and ok_word
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            canary.unlink(missing_ok=True)
    return good


# --- Personal I: suites of tests (checks-only) -----------------------------
#
# A suites file (suites.yaml, or the same as .json or .toml) lists suites;
# each has an object (product, stage or process), its items (folders under
# <object>/<item>/), its control cases (folders under controls/<suite>/<case>/
# with expect.json) and its tests (mechanical, llm or human). `suite` runs
# every mechanical and LLM test on every case, appends a row per result to
# judgments.csv (never rewriting it), keeps every LLM run, writes a bundle for
# the wizard (which collects the human tests and the student's reference
# judgments) and a report per suite.

SUITES_SCHEMA = "skill-eval-lite/suites@1"
SUITE_BUNDLE_SCHEMA = "skill-eval-lite/suite-bundle@1"
CSV_COLUMNS = ["item", "config", "object", "check", "route", "judge", "version", "result", "reason", "shown_left", "when"]
OBJECTS = {"product", "stage", "process"}
TEST_KINDS = {"mechanical", "llm", "human"}


class YamlError(Fail):
    pass


def parse_yaml(text: str):
    """The YAML that suites.yaml needs: block mappings and sequences (a
    sequence item may be a mapping), plain, single- and double-quoted
    scalars, | and > block scalars, one-line [flow, lists] and {flow: maps},
    and comments. Not anchors, tags, multi-line flow collections or several
    documents."""
    raw = text.replace("\t", "    ").splitlines()
    lines = []  # [lineno, indent, content]
    for n, line in enumerate(raw):
        body = line.rstrip()
        if not body.strip() or body.lstrip().startswith("#") or body.strip() in ("---", "..."):
            lines.append([n, None, ""])
            continue
        lines.append([n, len(body) - len(body.lstrip(" ")), body.strip()])

    def fail(n, msg):
        raise YamlError(f"suites file, line {n + 1}: {msg}")

    def next_line(i):
        while i < len(lines) and lines[i][1] is None:
            i += 1
        return i

    def strip_comment(s):
        out, q = [], None
        for k, ch in enumerate(s):
            if q:
                if ch == q:
                    q = None
            elif ch in "'\"" and (k == 0 or s[k - 1] in " [{,:"):
                q = ch
            elif ch == "#" and (k == 0 or s[k - 1] == " "):
                break
            out.append(ch)
        return "".join(out).rstrip()

    def split_flow(s):
        parts, depth, q, cur = [], 0, None, ""
        for ch in s:
            if q:
                cur += ch
                if ch == q:
                    q = None
                continue
            if ch in "'\"":
                q = ch
            elif ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
            elif ch == "," and depth == 0:
                parts.append(cur.strip())
                cur = ""
                continue
            cur += ch
        if cur.strip():
            parts.append(cur.strip())
        return parts

    def key_split(s):
        """(key, rest) when s is `key: rest` or `key:`; else None."""
        if s and s[0] in "'\"":
            q = s[0]
            j = s.find(q, 1)
            while q == "'" and j >= 0 and s[j + 1:j + 2] == "'":
                j = s.find(q, j + 2)
            if j > 0 and s[j + 1:j + 2] == ":" and (len(s) == j + 2 or s[j + 2] == " "):
                return scalar(s[:j + 1], -1), s[j + 2:].strip()
            return None
        m = re.match(r"([^:#\[\]{},][^:#]*?):(?:\s+(.*)|$)", s)
        if m and not s.startswith("- "):
            return m.group(1).strip(), (m.group(2) or "").strip()
        return None

    def scalar(s, n):
        s = s.strip()
        if s[:1] == '"':
            if not s.endswith('"') or len(s) < 2:
                fail(n, "a double-quoted string that does not end on its line")
            try:
                return json.loads(s)
            except ValueError:
                fail(n, f"a bad escape in {s}")
        if s[:1] == "'":
            if not s.endswith("'") or len(s) < 2:
                fail(n, "a single-quoted string that does not end on its line")
            return s[1:-1].replace("''", "'")
        if s[:1] == "[":
            if not s.endswith("]"):
                fail(n, "a [list] must end on its line")
            return [scalar(p, n) for p in split_flow(s[1:-1])]
        if s[:1] == "{":
            if not s.endswith("}"):
                fail(n, "a {map} must end on its line")
            out = {}
            for p in split_flow(s[1:-1]):
                kv = key_split(p)
                if not kv:
                    fail(n, f"{p!r} is not key: value")
                out[kv[0]] = scalar(kv[1], n) if kv[1] else None
            return out
        if s in ("", "~", "null", "Null", "NULL"):
            return None
        if s in ("true", "True", "TRUE"):
            return True
        if s in ("false", "False", "FALSE"):
            return False
        if re.fullmatch(r"[-+]?\d+", s):
            return int(s)
        if re.fullmatch(r"[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?", s):
            return float(s)
        return s

    def block_scalar(i, indent, style):
        out, j, base = [], i, None
        while j < len(lines):
            n, ind, _ = lines[j]
            text_line = raw[n].replace("\t", "    ")
            if ind is not None and ind <= indent:
                break
            if ind is None and not text_line.strip():
                out.append("")
            elif ind is None:  # a comment-looking line inside the block
                cur = len(text_line) - len(text_line.lstrip(" "))
                if cur <= indent:
                    break
                base = cur if base is None else base
                out.append(text_line[base:])
            else:
                base = ind if base is None else base
                out.append(text_line[base:].rstrip())
            j += 1
        while out and not out[-1]:
            out.pop()
        chomp = style[1:2]
        if style[0] == ">":
            paras, cur = [], []
            for l in out:
                if l:
                    cur.append(l.strip())
                else:
                    paras.append(" ".join(cur))
                    cur = []
            paras.append(" ".join(cur))
            body = "\n".join(paras)
        else:
            body = "\n".join(out)
        return (body if chomp == "-" else body + "\n") if body else "", j

    def value_after(i, indent, rest, n):
        """The value for `key: rest` on line i, which may continue below."""
        rest = strip_comment(rest)
        if rest and rest[0] in "|>":
            return block_scalar(i + 1, indent, rest[:2] if rest[1:2] and rest[1] in "-+" else rest[:1])
        if rest:
            return scalar(rest, n), i + 1
        j = next_line(i + 1)
        if j < len(lines) and (lines[j][1] > indent or (lines[j][1] == indent and lines[j][2].startswith("-"))):
            return block(j, lines[j][1])
        return None, i + 1

    def block(i, indent):
        i = next_line(i)
        if i >= len(lines):
            return None, i
        if lines[i][2] == "-" or lines[i][2].startswith("- "):
            seq = []
            while True:
                i = next_line(i)
                if i >= len(lines) or lines[i][1] != indent or not (lines[i][2] == "-" or lines[i][2].startswith("- ")):
                    break
                n, _, content = lines[i]
                rest = content[1:].strip()
                if not rest:
                    j = next_line(i + 1)
                    if j < len(lines) and lines[j][1] > indent:
                        v, i = block(j, lines[j][1])
                    else:
                        v, i = None, i + 1
                elif key_split(strip_comment(rest)) and rest[0] not in "[{":
                    sub_indent = indent + (len(content) - len(rest))
                    lines[i] = [n, sub_indent, rest]
                    v, i = block(i, sub_indent)
                else:
                    v, i = scalar(strip_comment(rest), n), i + 1
                seq.append(v)
            return seq, i
        out = {}
        while True:
            i = next_line(i)
            if i >= len(lines) or lines[i][1] < indent:
                break
            n, ind, content = lines[i]
            if ind > indent:
                fail(n, "this line is indented more than the one before it")
            if content == "-" or content.startswith("- "):
                break
            kv = key_split(content)
            if not kv:
                fail(n, f"expected `key: value`, found {content!r}")
            k, rest = kv
            if k in out:
                fail(n, f"{k!r} is set twice")
            out[k], i = value_after(i, indent, rest, n)
        return out, i

    i = next_line(0)
    if i >= len(lines):
        return {}
    data, end = block(i, lines[i][1])
    end = next_line(end)
    if end < len(lines):
        fail(lines[end][0], "unexpected indentation or content")
    return data


def read_suites_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    if path.suffix == ".toml":
        return tomllib.loads(text)
    return parse_yaml(text)


def short_hash(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()[:12]


RECORD_FILES = ("transcript.jsonl", "trace.jsonl")


class RecordError(Fail):
    """A line of a process case's record that is not a JSON object."""

    def __init__(self, path: Path, line: int):
        super().__init__(f"{path}, line {line}, is not a JSON object. Each line of a record is one JSON object: is it the right file?")
        self.path, self.line = path, line


def record_lines(path: Path) -> list[dict]:
    """The JSON objects of a record, one a line (blank lines skipped). Lines
    are split at \\n only, as the wizard splits them."""
    return [j for _, j in numbered_record_lines(path)]


def numbered_record_lines(path: Path) -> list[tuple[int, dict]]:
    out = []
    for k, line in enumerate(path.read_text(encoding="utf-8", errors="replace").split("\n"), 1):
        if not line.strip():
            continue
        try:
            j = json.loads(line)
        except ValueError:
            j = None
        if not isinstance(j, dict):
            raise RecordError(path, k)
        out.append((k, j))
    return out


def read_trace(folder: Path, red: Redactor | None = None) -> list | None:
    """A process case's steps, from its record, in this order:
    transcript.jsonl (a Claude Code or Codex session's events, as the runner
    keeps them), with what each step returned; else trace.jsonl, one step a
    line: {"tool", "detail", "error", "result", "refused"}. A case should
    have only one of the two (`suite --check` refuses a case with both); a
    program test that reads the record should read them in this order too.
    None when there is neither. A line that isn't a JSON object raises
    RecordError, which names the file and the line."""
    s = folder / "transcript.jsonl"
    if s.is_file():
        return trace_of(record_lines(s), red or Redactor(None), results=True)
    t = folder / "trace.jsonl"
    if t.is_file():
        steps = []
        for j in record_lines(t):
            st = {"tool": str(j.get("tool", "?")), "detail": str(j.get("detail", j.get("input", "")) or ""), "error": bool(j.get("error"))}
            if j.get("result") is not None:
                st["result"] = str(j["result"])[:400]
            if j.get("refused") or (st["error"] and str(j.get("result") or "").startswith(REFUSALS)):
                st["refused"] = st["error"] = True
            steps.append(st)
        return steps
    return None


def record_problems(folder: Path, rel: str) -> tuple[list[str], list[str]]:
    """What `suite --check` says about a process case's record: (must fix, notes).
    The suite designer in wizard.html says the same (recordProblems)."""
    have = [n for n in RECORD_FILES if (folder / n).is_file()]
    if len(have) == 2:
        return [f"{rel}/ has both transcript.jsonl and trace.jsonl. Keep one: the one this case's tests should read."], []
    if not have:
        other = sorted((p.name for p in folder.iterdir() if p.is_file() and p.suffix in (".jsonl", ".json") and p.name != "expect.json"),
                       key=lambda n: (not n.endswith(".jsonl"), n))
        if other:
            return [f"{rel}/ has {other[0]} but no transcript.jsonl or trace.jsonl. "
                    f"If {other[0]} is a Claude Code session, rename it transcript.jsonl."], []
        return [f"{rel}/ has no record of the run. Put the session in it as transcript.jsonl "
                "(a Claude Code or Codex session) or trace.jsonl (one step a line)."], []
    try:
        lines = numbered_record_lines(folder / have[0])
        steps = read_trace(folder)
    except RecordError as e:
        return [f"{rel}/{have[0]}, line {e.line}, is not a JSON object. Each line of a record is one JSON object: is it the right file?"], []
    except Exception as e:  # a record a program made by hand, say; the wizard has no copy of this
        return [f"{rel}/{have[0]} can't be read as a record ({type(e).__name__}). Is it the right file?"], []
    if have[0] == "trace.jsonl":
        k = next((k for k, j in lines if "tool" not in j), None)
        if k is not None:
            return [f'{rel}/trace.jsonl, line {k}, has no "tool". A trace.jsonl has one step a line: '
                    '{"tool", "detail", "error"}. If this is a Claude Code or Codex session, rename it transcript.jsonl.'], []
    if not steps:
        return [], [f"{rel}/{have[0]} has no tool steps. Is it the right session?"]
    return [], []


# --- Reading a shell step ----------------------------------------------------
#
# The trace checks look at each command in a shell step, the way a shell
# would split it. wizard.html has the same code (shellSplit, commandForms,
# patternMatches); tests/fixtures/shell.json holds what both must give.

_WS = " \t\n\r\f\v"
_WORD_END = _WS + ";&|<>()"


def shell_split(cmd: str) -> list[tuple[str, bool]]:
    """The commands in a shell step, in order, each as (text, writes).

    It splits at newlines, ;, &, &&, ||, | and |&, but not inside single or
    double quotes, after a backslash, inside $(...), <(...) or backticks, or
    in a heredoc's body, which stays with its command. A comment (# at the
    start of a word) is dropped. `writes` is True when the command has an
    output redirection into a file: >, >>, >| or &>, but not one that
    duplicates a descriptor (2>&1, >&2) or goes to /dev/null.

    A limit: a command inside $(...) or backticks is not split out. It stays
    part of the command around it, and is not checked on its own."""
    s, n = cmd or "", len(cmd or "")
    parts: list[list] = []
    cur: list[str] = []
    writes = False
    heredocs: list[tuple[str, bool, int]] = []   # (delimiter, tabs stripped, its command's index)
    depth = 0                                    # inside $(...), <(...) or >(...)
    groups = 0                                   # inside ( ... ), a subshell
    i = 0

    def last() -> str:
        return cur[-1][-1:] if cur else ""

    def at_start() -> bool:
        return not "".join(cur).strip(_WS)

    def word_at(k: int) -> tuple[str, int]:
        """The word that starts at k (after spaces), and where it ends."""
        while k < n and s[k] in " \t":
            k += 1
        start = k
        while k < n and s[k] not in _WORD_END:
            if s[k] in "'\"":
                q = s.find(s[k], k + 1)
                k = n if q < 0 else q + 1
            else:
                k += 2 if s[k] == "\\" else 1
        return s[start:k], k

    def flush():
        nonlocal cur, writes
        text = "".join(cur).strip(_WS)
        if text:
            parts.append([text, writes])
        cur, writes = [], False

    while i < n:
        c, nxt = s[i], s[i + 1:i + 2]
        if c == "\\":
            cur.append(s[i:i + 2])
            i += 2
            continue
        if c == "'":
            j = s.find("'", i + 1)
            j = n - 1 if j < 0 else j
            cur.append(s[i:j + 1])
            i = j + 1
            continue
        if c == "$" and nxt == "'":
            j = i + 2
            while j < n and s[j] != "'":
                j += 2 if s[j] == "\\" else 1
            cur.append(s[i:j + 1])
            i = j + 1
            continue
        if c in "\"`":
            j = i + 1
            while j < n and s[j] != c:
                j += 2 if s[j] == "\\" else 1
            cur.append(s[i:j + 1])
            i = j + 1
            continue
        if c in "$<>" and nxt == "(":
            depth += 1
            cur.append(c + "(")
            i += 2
            continue
        if depth:
            depth += 1 if c == "(" else -1 if c == ")" else 0
            cur.append(c)
            i += 1
            continue
        if c == "#" and (not cur or last() in tuple(_WS)):
            j = s.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "\n":
            flush()
            i += 1
            for delim, tabs, owner in heredocs:
                body = []
                while i < n:
                    j = s.find("\n", i)
                    line = s[i:] if j < 0 else s[i:j]
                    i = n if j < 0 else j + 1
                    body.append(line)
                    if (line.lstrip("\t") if tabs else line) == delim:
                        break
                if owner < len(parts):
                    parts[owner][0] += "\n" + "\n".join(body)
            heredocs = []
            continue
        if c == ";":
            flush()
            i += 1
            continue
        if c == "&":
            if nxt == "&":
                flush()
                i += 2
            elif nxt == ">" or last() in ("<", ">"):
                cur.append(c)
                i += 1
            else:
                flush()
                i += 1
            continue
        if c == "|":
            if nxt == "|":
                flush()
                i += 2
            elif last() == ">":
                cur.append(c)
                i += 1
            else:
                flush()
                i += 2 if nxt == "&" else 1
            continue
        if s.startswith("<<<", i):
            cur.append("<<<")
            i += 3
            continue
        if s.startswith("<<", i):
            j = i + 2
            tabs = s[j:j + 1] == "-"
            j += 1 if tabs else 0
            while j < n and s[j] in " \t":
                j += 1
            word, k = [], j
            while k < n and s[k] not in _WORD_END:
                if s[k] in "'\"":
                    q = s.find(s[k], k + 1)
                    q = n if q < 0 else q
                    word.append(s[k + 1:q])
                    k = q + 1
                elif s[k] == "\\":
                    word.append(s[k + 1:k + 2])
                    k += 2
                else:
                    word.append(s[k])
                    k += 1
            if "".join(word):
                heredocs.append(("".join(word), tabs, len(parts)))
            cur.append(s[i:k])
            i = k
            continue
        if c == ">":
            j = i + 1
            if j < n and s[j] in ">|":
                j += 1
            dup = s[j:j + 1] == "&"
            target, _ = word_at(j + 1 if dup else j)
            if dup and re.fullmatch(r"[0-9]+|-", target):
                pass                                 # >&2, 2>&1: a descriptor, not a file
            elif target and target.strip("'\"") != "/dev/null":
                writes = True
            cur.append(s[i:j + 1] if dup else s[i:j])
            i = j + 1 if dup else j
            continue
        if c == "(" and at_start():
            groups += 1
            i += 1
            continue
        if c == ")" and groups:
            flush()
            groups -= 1
            i += 1
            continue
        if c in "{}" and at_start() and (i + 1 >= n or s[i + 1] in _WORD_END):
            i += 1
            continue
        cur.append(c)
        i += 1
    flush()
    return [(t, w) for t, w in parts]


_ASSIGN = re.compile(r"""[A-Za-z_][A-Za-z0-9_]*=(?:'[^']*'|"(?:[^"\\]|\\[\s\S])*"|\\[\s\S]|[^ \t\n\r\f\v'"\\])*[ \t\n\r\f\v]+""")
_PREFIX = re.compile(r"(?:command|exec|time)[ \t\n\r\f\v]+")
_PROGRAM = re.compile(r"([^ \t\n\r\f\v]+)([\s\S]*)")


def command_forms(part: str, head: str = "") -> list[str]:
    """The forms of one command that a pattern is tried on: as written; with
    any leading NAME=value assignments and a leading command, exec or time
    dropped; and, when its program is a path, with a leading ./ removed and
    with the directories before `head` (the pattern's own program, such as
    kb/kb) removed. So /tmp/run-1/kb/kb search Dana is also tried as
    kb/kb search Dana."""
    forms, t = [part], part
    while True:
        m = _ASSIGN.match(t) or _PREFIX.match(t)
        if not m:
            break
        t = t[m.end():]
    forms.append(t)
    m = _PROGRAM.fullmatch(t)
    if m and "/" in m.group(1):
        prog, rest = m.group(1), m.group(2)
        if prog.startswith("./"):
            forms.append(prog[2:] + rest)
        if head and "*" not in head and prog != head and prog.endswith("/" + head):
            forms.append(head + rest)
    return list(dict.fromkeys(forms))


def _glob(pattern: str):
    """A check's pattern as a regular expression for re.fullmatch: * matches
    anything, and a pattern that ends in " *" also matches the command with
    nothing after it (ls * matches ls, as well as ls -la)."""
    if pattern.endswith(" *"):
        return re.compile(".*".join(re.escape(p) for p in pattern[:-2].split("*")) + r"(?:[ \t][\s\S]*)?", re.S)
    return re.compile(".*".join(re.escape(p) for p in pattern.split("*")), re.S)


def pattern_matches(pattern: str, command: str) -> bool:
    """Does a check's pattern (* for anything) match one command, in any of its forms?"""
    g = _glob(pattern)
    return any(g.fullmatch(f) for f in command_forms(command, pattern.split(" ", 1)[0]))


def _shell_parts(cmd: str) -> list[str]:
    return [t for t, _ in shell_split(cmd)]


def _allowed_part(part: str, writes: bool, allowed: list[str]) -> bool:
    """A command in a shell step is allowed by a `Bash <pattern>` entry that
    matches it; one that writes a file (a redirection) only by a pattern that
    itself contains >."""
    return any(a.startswith("Bash ") and (not writes or ">" in a[5:]) and pattern_matches(a[5:], part) for a in allowed)


def _allowed_step(st: dict, allowed: list[str]) -> bool:
    if st["tool"] in allowed:
        return True
    if st["tool"] == "Bash":
        return all(_allowed_part(p, w, allowed) for p, w in shell_split(st["detail"]))
    return any(" " in a and _glob(a).fullmatch(st["tool"] + " " + st["detail"]) for a in allowed)


def _brief(text: str, n: int = 120) -> str:
    """A command as a reason shows it: its first line, at most n characters."""
    first = (text or "").split("\n", 1)[0]
    return first if first == text and len(first) <= n else first[:n].rstrip(_WS) + " ..."


CHAIN_NOTE = " (in a chain: the step's success is its last command's)"


def step_mark(st: dict) -> str:
    """A step's mark in a bundle's trace: "refused" (it never ran), "error" (it failed) or ""."""
    return "refused" if st.get("refused") else "error" if st.get("error") else ""


# --- A pattern in Python and in the browser (0.2.1) -------------------------
#
# A matches check runs twice: here, in Python's re, and in the wizard, in the
# browser's JavaScript. The wizard reads a pattern as Python does where the two
# differ in ways an intake has written: flags at the pattern's very start,
# (?m), (?s), (?i), and \A and \Z (wizard.html's browserPattern). What it
# can't read is a "must fix" here, so that a check that works in the runner
# works in the wizard too. And a pattern can take minutes on a long output (a
# repeated group inside a repeat, such as (?:\s*\S+){1,30}), which would hang
# the runner and the wizard alike: `check` and `suite --check` time each one,
# in a process of its own, on long made-up outputs and stretched references.

_BROWSER_CANT = [
    (re.compile(r"\(\?P[<=>]"), "a named group written (?P<name>...) or (?P=name): write (?<name>...) and \\k<name>"),
    (re.compile(r"\(\?>"), "an atomic group, (?>...)"),
    (re.compile(r"\(\?\("), "a conditional group, (?(...)...)"),
    (re.compile(r"\(\?#"), "a comment, (?#...)"),
    (re.compile(r"[*+?}]\+"), "a possessive repeat, such as *+ or ++"),
    (re.compile(r"^\(\?[aiLmsux]*[aLx][aiLmsux]*\)"), "a flag the browser has no form of: (?a), (?L) or (?x)"),
]
PATTERN_SECONDS = 3.0


def pattern_problems(cid: str, pattern: str, flags: str = "") -> list[str]:
    """What the browser can't read in a matches check's pattern, as must-fix
    lines. Escaped characters are set aside first, so \\++ is a literal plus."""
    if not isinstance(pattern, str) or not pattern:
        return []
    try:
        re.compile(pattern, sum({"i": re.I, "m": re.M, "s": re.S}.get(f, 0) for f in (flags or "")))
    except re.error as e:
        return [f"Check {cid!r}: its pattern isn't a regular expression Python can read ({e})."]
    bare = re.sub(r"\\.", "_", pattern)
    found = [what for rx, what in _BROWSER_CANT if rx.search(bare)]
    return [f"Check {cid!r}: its pattern has {what}, which the wizard (JavaScript, in your browser) can't read. "
            "Write it another way, so that the runner and the wizard give the same answer." for what in found]


def _stretch(text: str, times: int = 4) -> str:
    """A text with each line's words repeated: the long output a pattern
    should still answer quickly."""
    return "\n".join(" ".join(line.split() * times) for line in text.splitlines())


def pattern_samples(texts: list[str]) -> list[str]:
    words = " ".join(["ingredient", "roasted", "with", "garden", "herbs"] * 60)
    made_up = [f"## A heading\n{words}\nContains: something", f"## A heading\n{words}\n", words, "\n".join([words] * 3)]
    return made_up + [_stretch(t) for t in texts if isinstance(t, str) and t.strip()][:8]


def slow_pattern_problems(cid: str, pattern: str, flags: str, samples: list[str]) -> list[str]:
    """Run the pattern on long samples in a process of its own; a must-fix
    line if it takes longer than PATTERN_SECONDS (it backtracks)."""
    if not isinstance(pattern, str) or not pattern:
        return []
    code = ("import json,re,sys\nd=json.load(sys.stdin)\n"
            "f=sum({'i':re.I,'m':re.M,'s':re.S}.get(x,0) for x in d['flags'])\n"
            "r=re.compile(d['pattern'],f)\n[r.search(t) for t in d['samples']]\n")
    try:
        subprocess.run([sys.executable, "-I", "-c", code], input=json.dumps({"pattern": pattern, "flags": flags or "", "samples": samples}),
                       text=True, capture_output=True, timeout=PATTERN_SECONDS)
    except subprocess.TimeoutExpired:
        return [f"Check {cid!r}: its pattern took more than {PATTERN_SECONDS:g} seconds on a long made-up output, so it would hang "
                "the runner and the wizard. It has a repeated group inside a repeat that can split the text many ways, such as "
                "(?:\\s*\\S+){1,30}. Make each repeated part start with something the part before can't match, such as "
                "\\S+(?:\\s+\\S+){0,29} for at most 30 words, or use a word-count check."]
    return []


def run_check(c: dict, text: str | None, trace: list | None, no_trace: str = "no trace kept") -> tuple[str, str]:
    """One check on an output and its trace: (pass, fail or n/a, the reason).
    wizard.html's CHECK_KINDS and runCheck give the same results."""
    kind = c.get("kind")
    if kind in ("trace-ran-command", "trace-no-tool-outside"):
        if trace is None:
            return "n/a", no_trace
        if kind == "trace-ran-command":
            tries = []
            for st in trace:
                if st["tool"] != "Bash":
                    continue
                parts = shell_split(st["detail"])
                cmd = next((p for p, _ in parts if pattern_matches(c["pattern"], p)), None)
                if cmd is not None:
                    tries.append((st, cmd, len(parts) > 1))
            hit = next((t for t in tries if not t[0]["error"]), None)
            if hit:
                return "pass", "ran " + _brief(hit[1]) + (CHAIN_NOTE if hit[2] else "")
            if tries:
                st, cmd, chain = tries[0]
                return "fail", "tried " + _brief(cmd) + ", in a step that failed" + (" (refused)" if st.get("refused") else "") \
                    + (CHAIN_NOTE if chain and not st.get("refused") else "")
            return "fail", "never ran " + c["pattern"]
        allowed = c.get("allowed", [])
        refused = [st for st in trace if st.get("refused")]
        for st in trace:
            if st.get("refused") or _allowed_step(st, allowed):
                continue
            if st["tool"] == "Bash":
                p, w = next((p, w) for p, w in shell_split(st["detail"]) if not _allowed_part(p, w, allowed))
                return "fail", "outside the list: Bash " + _brief(p) + (" (it writes a file)" if w else "")
            return "fail", "outside the list: " + st["tool"] + " " + _brief(st["detail"])
        if not refused:
            return "pass", "every step on the list"
        shown = [_brief(st["detail"] if st["tool"] == "Bash" else st["tool"] + " " + st["detail"], 60) for st in refused[:3]]
        return "pass", (f"every step that ran was on the list; {len(refused)} attempt{'s were' if len(refused) != 1 else ' was'} "
                        f"refused: " + ", ".join(shown) + (", ..." if len(refused) > 3 else ""))
    if text is None:
        return "n/a", "no output to check"
    if kind == "contains":
        miss = [t for t in c.get("text", []) if t not in text]
        return ("fail", "missing: " + ", ".join(miss)) if miss else ("pass", "all present")
    if kind == "not-contains":
        found = [t for t in c.get("text", []) if t in text]
        return ("fail", "found: " + ", ".join(found)) if found else ("pass", "none found")
    if kind == "matches":
        flags = sum({"i": re.I, "m": re.M, "s": re.S}.get(f, 0) for f in c.get("flags", ""))
        return ("pass", "matches") if re.search(c["pattern"], text, flags) else ("fail", "no match for /" + c["pattern"] + "/")
    if kind == "word-count":
        w = len(text.split())
        ok = (c.get("min") is None or w >= c["min"]) and (c.get("max") is None or w <= c["max"])
        return ("pass" if ok else "fail"), f"{w} words"
    if kind == "json-parses":
        try:
            json.loads(text)
            return "pass", "parses"
        except ValueError as e:
            return "fail", f"does not parse: {e}"
    return "n/a", f"unknown kind {kind}"


class Suites:
    """The suites file, its cases and its tests, as the runner and the wizard need them."""

    def __init__(self, path: Path):
        self.path = path
        self.root = path.parent.resolve()
        self.data = read_suites_file(path)
        self.errors: list[str] = []
        self.suites = []
        if self.data.get("schema") not in (None, SUITES_SCHEMA):
            self.errors.append(f'schema should be "{SUITES_SCHEMA}".')
        self.warnings: list[str] = []
        for s in self.data.get("suites") or []:
            self.suites.append(self._suite(s))
        if not self.suites:
            self.errors.append("There are no suites (a `suites:` list).")
        objects = {s["object"] for s in self.suites}
        if self.suites and ("process" not in objects or not objects & {"product", "stage"}):
            self.warnings.append("The brief asks for two suites: one on a product or a stage, and one on a process.")

    def _file(self, rel):
        return (self.root / rel) if rel else None

    def _suite(self, s: dict) -> dict:
        sid = s.get("id") or "?"
        obj = s.get("object")
        if obj not in OBJECTS:
            self.errors.append(f"Suite {sid}: object is {obj!r}; it must be product, stage or process.")
        out_file = s.get("file", "output.md")
        cases = []
        for item in s.get("items") or []:
            folder = self.root / (obj or "product") / str(item)
            if not folder.is_dir():
                self.errors.append(f"Suite {sid}: no folder {folder.relative_to(self.root).as_posix()}/ for item {item}.")
            cases.append({"id": str(item), "role": "item", "folder": folder})
        cdir = self.root / "controls" / sid
        for folder in sorted(p for p in cdir.iterdir() if p.is_dir()) if cdir.is_dir() else []:
            ej = folder / "expect.json"
            if not ej.is_file():
                self.errors.append(f"Suite {sid}: control {folder.name} has no expect.json.")
                continue
            e = json.loads(ej.read_text(encoding="utf-8"))
            if e.get("role") not in ("reference", "fault", "variation"):
                self.errors.append(f"Suite {sid}: control {folder.name}: role must be reference, fault or variation.")
            cases.append({"id": folder.name, "role": e.get("role"), "varies": e.get("varies"), "expect": e.get("expect") or {},
                          "note": e.get("note", ""), "folder": folder})
        tests = []
        for t in s.get("tests") or []:
            tid = t.get("id") or "?"
            if t.get("kind") not in TEST_KINDS:
                self.errors.append(f"Suite {sid}, test {tid}: kind must be mechanical, llm or human.")
            files = {}
            for key in ("program", "prompt", "skill", "instructions"):
                if t.get(key):
                    f = self._file(t[key])
                    if not f.is_file():
                        self.errors.append(f"Suite {sid}, test {tid}: its {key} {t[key]} does not exist.")
                    else:
                        files[key] = f
            if t.get("kind") == "mechanical" and not t.get("check") and "program" not in files:
                self.errors.append(f"Suite {sid}, test {tid}: a mechanical test needs `check` (a built-in kind) or `program`.")
            if t.get("kind") == "mechanical" and t.get("check") and t["check"].get("kind") not in CHECK_KINDS:
                self.errors.append(f"Suite {sid}, test {tid}: check kind {t['check'].get('kind')!r} is not one Skill Eval Lite knows.")
            if t.get("kind") == "mechanical" and isinstance(t.get("check"), dict) and t["check"].get("kind") == "matches":
                self.errors += [f"Suite {sid}, test {tid}: " + e.split(": ", 1)[1]
                                for e in pattern_problems(tid, t["check"].get("pattern"), t["check"].get("flags", ""))]
            if t.get("kind") == "llm" and not ({"prompt", "skill"} & set(files)):
                self.errors.append(f"Suite {sid}, test {tid}: an LLM test needs `prompt` (a prompt.md) or `skill` (a SKILL.md).")
            version = short_hash(json.dumps(t, sort_keys=True, ensure_ascii=False),
                                 *[files[k].read_text(encoding="utf-8", errors="replace") for k in sorted(files)])
            tests.append({**t, "files": files, "version": version})
        warns = []
        if obj == "process":
            for c in cases:
                if c["folder"].is_dir() and (c["role"] == "item" or (c["folder"] / "expect.json").is_file()):
                    errs, notes = record_problems(c["folder"], c["folder"].relative_to(self.root).as_posix())
                    self.errors += [f"Suite {sid}: {e}" for e in errs]
                    warns += [f"Suite {sid}: {w}" for w in notes]
        n_items = sum(1 for c in cases if c["role"] == "item")
        roles = [c["role"] for c in cases]
        if obj in ("product", "stage") and n_items < 6:
            warns.append(f"Suite {sid}: {n_items} instances; the brief asks for at least six.")
        if obj == "process" and n_items < 3:
            warns.append(f"Suite {sid}: {n_items} recorded runs; the brief asks for at least three.")
        if roles.count("reference") < 1 or roles.count("fault") < 2 or roles.count("variation") < 2:
            warns.append(f"Suite {sid}: the brief asks for a reference, two planted faults and two harmless variations.")
        kinds = {t.get("kind") for t in tests}
        if not {"mechanical", "llm", "human"} <= kinds:
            warns.append(f"Suite {sid}: the brief asks for at least one test of each kind.")
        return {"id": sid, "object": obj, "what": s.get("what", ""), "file": out_file, "cases": cases, "tests": tests,
                "version": short_hash(*[t["version"] for t in tests]), "warnings": warns}

    def case_content(self, suite: dict, case: dict) -> dict:
        folder = case["folder"]
        files = {}
        for p in sorted(folder.rglob("*")):
            if p.is_file() and p.name not in ("expect.json", "trace.jsonl", "transcript.jsonl") and p.stat().st_size < 200_000:
                files[p.relative_to(folder).as_posix()] = p.read_text(encoding="utf-8", errors="replace")
        trace = read_trace(folder)
        return {"files": files, "trace": trace, "output": files.get(suite["file"])}


def render_case(suite: dict, content: dict) -> str:
    """A case as an LLM test reads it: its files, then its trace."""
    parts = []
    for name, body in content["files"].items():
        parts += [f"### {name}", "", body.strip(), ""]
    if content["trace"] is not None:
        parts += ["### The trace (each step the agent took, in order)", ""]
        for k, st in enumerate(content["trace"], 1):
            parts.append(f"{k}. {st['tool']}: {st['detail']}" + ("  [this step failed]" if st["error"] else ""))
            if st.get("result"):
                parts.append("   returned: " + " ".join(st["result"].split())[:300])
    return "\n".join(parts).strip()


def parse_verdict(text: str) -> str:
    return parse_verdict_noted(text)[0]


def parse_verdict_noted(text: str) -> tuple[str, str]:
    """An LLM test's verdict, from its response's last line: (pass, fail or unknown, a note)."""
    word, note = last_line_word(text, VERDICT_WORDS)
    return word.lower(), note


def append_rows(csv_path: Path, rows: list[dict]):
    import csv
    new = not csv_path.exists()
    with open(csv_path, "a", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore", lineterminator="\n")
        if new:
            w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in CSV_COLUMNS})


def read_rows(csv_path: Path) -> list[dict]:
    import csv
    if not csv_path.exists():
        return []
    with open(csv_path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def latest(rows: list[dict], suite: dict) -> dict:
    """The latest result per (case, test) for mechanical and LLM tests, per
    (case, test, rater) for human tests, and per (case, test) for each
    student's reference judgments, for this suite's current test versions."""
    versions = {t["id"]: t["version"] for t in suite["tests"]}
    ids = {c["id"] for c in suite["cases"]}
    out = {"auto": {}, "human": {}, "reference": {}}
    for r in sorted(rows, key=lambda r: r.get("when", "")):
        item = r["item"]
        if item not in ids and not ("|" in item and all(x in ids for x in item.split("|"))):
            continue
        check = r["check"]
        if r["route"] in ("mechanical", "llm") and versions.get(check) == r["version"]:
            out["auto"][(r["item"], check)] = r
        elif r["route"] == "human" and check.endswith("-reference") and check[:-10] in versions:
            out["reference"][(r["item"], check[:-10], r["judge"])] = r
        elif r["route"] == "human" and check in versions:
            out["human"][(r["item"], check, r["judge"])] = r
    return out


def human_pass(test: dict, value: str) -> str | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return "pass" if v >= float(test.get("pass_at", 3)) else "fail"


def shows_nothing(base: str, on_base: str, got: str) -> str:
    """A control's cell when the test doesn't pass the reference it was made from."""
    return (f"shows nothing: the test fails {base} too (got {got})" if on_base == "fail"
            else f"shows nothing: the test can't tell on {base} (got {got})")


def reference_note(test: str, ref: str, result: str) -> str:
    """The note under the controls table for a test that doesn't pass a reference."""
    which = "the reference" + ("" if ref == "reference" else f" ({ref})")
    return (f"- `{test}` " + (f"fails {which}" if result == "fail" else f"can't tell on {which} (unknown)")
            + ", so its results on the faults and variations show little until the reference or the test is fixed. "
              "Look at why first.")


def suite_report(suite: dict, rows: list[dict], when: str) -> str:
    """The suite report, as Markdown: a row per case and a column per test,
    the failures, where tests disagree, the controls and the agreement."""
    L = latest(rows, suite)
    tests, cases = suite["tests"], suite["cases"]

    def cell(case, t):
        if t["kind"] == "human" and t.get("form", "rating") == "comparison":
            rs = [r for k, r in L["human"].items() if k[1] == t["id"] and case["id"] in k[0].split("|")]
            return (f"won {sum(1 for r in rs if r['result'] == case['id'])} of {len(rs)}", None) if rs else ("not compared", None)
        if t["kind"] == "human":
            rs = sorted((k[2], r) for k, r in L["human"].items() if k[0] == case["id"] and k[1] == t["id"])
            if not rs:
                return "not rated", None
            vals = ", ".join(f"{r['result']} ({j})" for j, r in rs)
            verdicts = {human_pass(t, r["result"]) for _, r in rs} - {None}
            return vals, (verdicts.pop() if len(verdicts) == 1 else ("split" if verdicts else None))
        r = L["auto"].get((case["id"], t["id"]))
        return (r["result"] + (" (re-read)" if r.get("reason", "").startswith(REREAD) else ""), r["result"]) if r else ("not run", None)

    grid = {(c["id"], t["id"]): cell(c, t) for c in cases for t in tests}
    role = {"item": "instance", "reference": "reference", "fault": "planted fault", "variation": "harmless variation"}
    out = [f"# Suite report: {suite['id']}", "",
           f"Object: {suite['object']}. Suite version {suite['version']} "
           f"({', '.join(t['id'] + ' ' + t['version'] for t in tests)}). Written {when} by {TOOL}.", ""]
    if suite.get("what"):
        out += [suite["what"].strip(), ""]
    out += ["| Case | Role | " + " | ".join(f"{t['id']} ({t['kind']})" for t in tests) + " |",
            "| --- | --- | " + " | ".join("---" for _ in tests) + " |"]
    for c in cases:
        out.append(f"| {c['id']} | {role.get(c['role'], c['role'])} | " + " | ".join(grid[(c['id'], t['id'])][0] for t in tests) + " |")
    fails = []
    for c in cases:
        for t in tests:
            v = grid[(c["id"], t["id"])][1]
            if v in ("fail", "split"):
                r = L["auto"].get((c["id"], t["id"]))
                fails.append(f"- {c['id']}, {t['id']}: {v}" + (f" ({r['reason'][:160]})" if r and r.get("reason") else ""))
    out += ["", "## Failures", ""] + (fails or ["None."])
    dis = []
    for c in cases:
        vs = {t["id"]: grid[(c["id"], t["id"])][1] for t in tests if grid[(c["id"], t["id"])][1] in ("pass", "fail")}
        if len(set(vs.values())) > 1:
            dis.append(f"- {c['id']}: " + ", ".join(f"{k} {v}" for k, v in vs.items()))
    out += ["", "## Where the tests disagree on the same case", ""] + (dis or ["Nowhere."])
    out += ["", "## Controls: did each test do what the control expects?", ""]
    controls = [c for c in cases if c["role"] != "item"]
    if controls:
        out += ["| Test | " + " | ".join(f"{c['id']} ({role[c['role']]})" for c in controls) + " |",
                "| --- | " + " | ".join("---" for _ in controls) + " |"]
        by_id = {c["id"]: c for c in cases}
        for t in tests:
            marks = []
            for c in controls:
                want = (c.get("expect") or {}).get(t["id"], {"reference": "pass", "variation": "same"}.get(c["role"], "any"))
                got = grid[(c["id"], t["id"])][1]
                base = by_id.get(c.get("varies"))
                if want == "same":
                    want = grid[(base["id"], t["id"])][1] if base else None
                    label = "same as " + (c.get("varies") or "?")
                else:
                    label = want
                # A control made from the reference (a variation, or a fault that
                # says it varies the reference) shows nothing about a test that
                # doesn't pass the reference: it carries the reference's own result.
                on_base = grid[(base["id"], t["id"])][1] if base and base["role"] == "reference" else None
                if want in (None, "any") or got not in ("pass", "fail"):
                    marks.append("-" if want == "any" else f"? ({label}; got {got or 'nothing'})")
                elif c["role"] in ("fault", "variation") and on_base in ("fail", "unknown"):
                    marks.append(shows_nothing(base["id"], on_base, got))
                else:
                    marks.append(("ok" if got == want else "MISSED") + f" ({label}, got {got})")
            out.append(f"| {t['id']} | " + " | ".join(marks) + " |")
        notes = [reference_note(t["id"], r["id"], grid[(r["id"], t["id"])][1]) for t in tests for r in controls
                 if r["role"] == "reference" and grid[(r["id"], t["id"])][1] in ("fail", "unknown")]
        if notes:
            out += [""] + notes
    else:
        out.append("No control cases.")
    out += ["", "## Agreement", ""]
    agree = []
    for t in tests:
        if t["kind"] == "llm":
            refs = {}
            for (cid, tid, who), r in L["reference"].items():
                if tid == t["id"]:
                    refs.setdefault(who, {})[cid] = r["result"]
            for who, mine in sorted(refs.items()):
                both = [(cid, v, L["auto"][(cid, t["id"])]["result"]) for cid, v in mine.items() if (cid, t["id"]) in L["auto"]]
                same = sum(1 for _, a, b in both if a == b)
                agree.append(f"- {t['id']}: the LLM and {who}'s reference judgments agree on {same} of {len(both)} cases."
                             + "".join(f"\n  - {cid}: {who} {a}, the LLM {b}" for cid, a, b in both if a != b))
            if not refs:
                agree.append(f"- {t['id']}: no reference judgments yet.")
        if t["kind"] == "human":
            raters = sorted({k[2] for k in L["human"] if k[1] == t["id"]})
            for a_i in range(len(raters)):
                for b_i in range(a_i + 1, len(raters)):
                    a, b = raters[a_i], raters[b_i]
                    items = [c["id"] for c in cases] + list(dict.fromkeys(k[0] for k in L["human"] if k[1] == t["id"] and "|" in k[0]))
                    pairs = [(L["human"][(i, t["id"], a)]["result"], L["human"][(i, t["id"], b)]["result"]) for i in items
                             if (i, t["id"], a) in L["human"] and (i, t["id"], b) in L["human"]]
                    same = sum(1 for x, y in pairs if x == y)
                    near = sum(1 for x, y in pairs if _num(x) is not None and _num(y) is not None and abs(_num(x) - _num(y)) <= 1)
                    agree.append(f"- {t['id']}: {a} and {b} gave the same answer on {same} of {len(pairs)} cases"
                                 + (f", within one point on {near}" if t.get("form", "rating") == "rating" else "") + ".")
            if len(raters) < 2:
                agree.append(f"- {t['id']}: {len(raters)} rater{'s' if len(raters) != 1 else ''} so far; agreement needs two.")
    out += agree or ["No LLM or human tests."]
    return "\n".join(out) + "\n"


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def suites_slow_patterns(S: "Suites") -> list[str]:
    """Each mechanical matches test timed on long made-up outputs and on its suite's cases, stretched."""
    out = []
    for su in S.suites:
        texts = []
        for c in su["cases"][:8]:
            f = c["folder"] / su.get("file", "output.md")
            if f.is_file():
                texts.append(f.read_text(encoding="utf-8", errors="replace")[:20000])
        samples = pattern_samples(texts)
        for t in su["tests"]:
            ck = t.get("check")
            if t.get("kind") == "mechanical" and isinstance(ck, dict) and ck.get("kind") == "matches":
                out += [f"Suite {su['id']}, test {t['id']}: " + e.split(": ", 1)[1]
                        for e in slow_pattern_problems(t["id"], ck.get("pattern"), ck.get("flags", ""), samples)]
    return out


def cmd_suite(a) -> int:
    src = Path(a.suites)
    if not src.is_file():
        raise Fail(f"There is no suites file at {a.suites}. Check the path (for the worked example: examples/personal-suites/suites.yaml).")
    if a.out:
        out = Path(a.out)
        if out.resolve() != src.parent.resolve():
            out.mkdir(parents=True, exist_ok=True)
            for name in (src.name, "product", "stage", "process", "controls", "tests"):
                p = src.parent / name
                if p.is_dir():
                    shutil.copytree(p, out / name, dirs_exist_ok=True, ignore=shutil.ignore_patterns("runs"))
                elif p.is_file():
                    shutil.copyfile(p, out / name)
            src = out / src.name
    S = Suites(src)
    root = src.parent
    if not S.errors:
        S.errors += suites_slow_patterns(S)
    for w in [w for s in S.suites for w in s["warnings"]] + S.warnings:
        say("  note: " + w)
    if S.errors:
        say("The suites file can't be run yet. Fix these, then check it again:")
        for e in S.errors:
            say("  " + e)
        check = f"{PY} run_ab.py suite {a.suites} --check"
        say(check if (getattr(a, "runner", None) or S.data.get("runner")) == "codex" else in_claude("run-suites", check) + ".")
        return 1
    if a.check:
        say(f"{src}: {len(S.suites)} suites ({', '.join(s['id'] + ': ' + str(len(s['cases'])) + ' cases, ' + str(len(s['tests'])) + ' tests' for s in S.suites)}). Nothing to fix.")
        return 0
    chosen = [s for s in S.suites if not a.suite or s["id"] in a.suite.split(",")]
    only_cases = set(a.cases.split(",")) if a.cases else None
    only_tests = set(a.tests.split(",")) if a.tests else None
    csv_path = root / "judgments.csv"
    rows = read_rows(csv_path)
    llm_needed = [(s, t, c) for s in chosen for t in s["tests"] if t.get("kind") == "llm" and (not only_tests or t["id"] in only_tests)
                  for c in s["cases"] if not only_cases or c["id"] in only_cases]
    done_llm = {(r["item"], r["check"], r["version"]) for r in rows if r["route"] == "llm"}
    todo = [] if a.no_llm else [(s, t, c) for s, t, c in llm_needed if a.again or (c["id"], t["id"], t["version"]) not in done_llm]
    skipped = len(llm_needed) - len(todo)
    runner = None
    rname = runner_name(a, S.data.get("runner"))
    if todo:
        safe_temp_parent()
        runner = open_runner(rname, a).__enter__()
        try:
            runner.require_login()
        except Fail:
            runner.__exit__(None, None, None)
            raise
    try:
        return _suite_rest(a, S, src, root, chosen, only_cases, only_tests, csv_path, todo, skipped, runner)
    finally:
        if runner:
            runner.__exit__(None, None, None)


REREAD = "re-read with 0.1.1's rule; no new run"


def reread_unknowns(S, chosen, only_cases, only_tests, root: Path) -> list[dict]:
    """Rows for the stored LLM runs of each test's current version whose
    verdict was unknown and which the last-line rule (last_line_word) now
    reads as pass or fail. No model is called, and the run's record is kept
    as it is; each run is re-read once (its row names the run's file)."""
    rows = read_rows(root / "judgments.csv")
    done = [r["reason"] for r in rows if r.get("route") == "llm" and r.get("reason", "").startswith(REREAD)]
    out = []
    for s in chosen:
        ids = {c["id"] for c in s["cases"]}
        for t in s["tests"]:
            if t.get("kind") != "llm" or (only_tests and t["id"] not in only_tests):
                continue
            for f in sorted((root / "tests" / t["id"] / "runs").glob("*.json")):
                rel = f.relative_to(root).as_posix()
                try:
                    rec = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if rec.get("version") != t["version"] or rec.get("decision") != "unknown" or rec.get("status") != "ok" \
                        or rec.get("case") not in ids or (only_cases and rec.get("case") not in only_cases) \
                        or any(x.endswith(f"({rel})") for x in done):
                    continue
                word, note = parse_verdict_noted(rec.get("response", ""))
                if word in ("pass", "fail"):
                    out.append({"item": rec["case"], "object": s["object"], "check": t["id"], "route": "llm", "judge": rec.get("model", ""),
                                "version": t["version"], "result": word, "reason": f"{REREAD}: {note} ({rel})", "when": rec.get("when", "")})
                    say(f"  {t['id']:24} {rec['case']:24} {word:8} re-read from {rel}, with no new run")
    return out


def _suite_rest(a, S, src, root, chosen, only_cases, only_tests, csv_path, todo, skipped, runner) -> int:
    codex = runner is not None and runner.name == "codex"
    when = now()
    new_rows = []
    for s in chosen:
        for t in s["tests"]:
            if only_tests and t["id"] not in only_tests or t.get("kind") != "mechanical":
                continue
            for c in s["cases"]:
                if only_cases and c["id"] not in only_cases:
                    continue
                content = S.case_content(s, c)
                if t.get("program"):
                    prog = t["files"]["program"]
                    result, reason = run_program(prog, c["folder"], timeout=120, cwd=root)
                    judge = prog.name
                else:
                    result, reason = run_check(t["check"], content["output"], content["trace"],
                                               no_trace=f"no transcript.jsonl or trace.jsonl in {c['folder'].relative_to(root.resolve()).as_posix()}/")
                    judge = TOOL + " (" + t["check"]["kind"] + ")"
                new_rows.append({"item": c["id"], "object": s["object"], "check": t["id"], "route": "mechanical", "judge": judge,
                                 "version": t["version"], "result": result, "reason": reason, "when": when})
    new_rows += reread_unknowns(S, chosen, only_cases, only_tests, root)
    if todo:
        say(f"LLM tests: {len(todo)} runs with {runner.label}, {a.jobs} at a time"
            + (f" ({skipped} already run for this version; add --again to run them again)" if skipped else "")
            + ". Each runs in a fresh, isolated session (SAFETY.md).")
    registry: set = set()
    lock = threading.Lock()
    stop = []

    def llm(item):
        s, t, c = item
        if stop:
            return
        content = S.case_content(s, c)
        case_text = render_case(s, content)
        tmp = Path(tempfile.mkdtemp(prefix="skill-eval-lite-test-", dir=safe_temp_parent()))
        try:
            if t["files"].get("skill"):
                name = re.sub(r"[^a-z0-9-]+", "-", t["id"].lower())
                d = tmp / (".agents" if codex else ".claude") / "skills" / name
                d.mkdir(parents=True)
                shutil.copyfile(t["files"]["skill"], d / "SKILL.md")
                text = (f"Use the {name} skill to judge the case below. End your answer with one line that says only PASS, FAIL or UNKNOWN.\n\n"
                        f"## The case\n\n{case_text}\n")
                tools, allowed, shell = ["Skill"], ["Skill"], True
            else:
                prompt = t["files"]["prompt"].read_text(encoding="utf-8")
                text = prompt.replace("{{case}}", case_text) if "{{case}}" in prompt else prompt.rstrip() + "\n\n## The case\n\n" + case_text + "\n"
                tools, allowed, shell = [], [], False
            model = runner.pick_model(t.get("codex_model" if codex else "claude_model"), t.get("model"))
            started = now()
            skills_dir = tmp / ".claude" / "skills"
            run = runner.run(tmp, text, model=model, timeout=int(t.get("timeout_seconds", 180)), tools=tools, allowed=allowed,
                             budget=float(t.get("budget_usd", 0.5)), registry=registry, shell=shell,
                             project_skills={p.name for p in skills_dir.iterdir()} if skills_dir.is_dir() else set())
            red = Redactor(tmp)
            if run.breach:
                stop.append("STOPPED: an LLM test's run was not isolated: " + "; ".join(run.breach))
                return
            if run.not_logged_in:
                stop.append(CODEX_NOT_LOGGED_IN if codex else NOT_LOGGED_IN)
                return
            response = red.text(run.final.strip())
            ok = run.ok
            decision, note = parse_verdict_noted(response) if ok else ("unknown", "the run " + ("timed out" if run.timed_out else "failed"))
            model = run.model_seen or model or ""
            rec = {"suite": s["id"], "test": t["id"], "version": t["version"], "case": c["id"], "when": started, "model": model,
                   **runner.record(), "command": run.command, "decision_rule": t.get("decision", "The last line is PASS, FAIL or UNKNOWN."),
                   "decision": decision, "decision_note": note, "status": "ok" if ok else ("timeout" if run.timed_out else "failed"), "seconds": run.seconds,
                   "cost_usd": run.cost_usd, "input": red.text(text), "response": response,
                   "isolation": run.isolation, "tool": TOOL}
            if run.usage:
                rec["usage"] = run.usage
            d = root / "tests" / t["id"] / "runs"
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{c['id']}__{started.replace(':', '')}.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            reason = " ".join(response.splitlines()[:-1]).strip()[:300] if response else (rec["status"])
            if note:
                reason = (note[0].upper() + note[1:] + ". " + reason).strip()
            with lock:
                new_rows.append({"item": c["id"], "object": s["object"], "check": t["id"], "route": "llm", "judge": model,
                                 "version": t["version"], "result": decision, "reason": reason, "when": started})
                say(f"  {t['id']:24} {c['id']:24} {decision:8} {run.seconds:5.0f} s")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    if todo:
        with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as pool:
            list(pool.map(llm, todo))
    append_rows(csv_path, new_rows)
    if stop:
        say("\n" + stop[0], err=True)
        return 3
    rows = read_rows(csv_path)
    (root / "reports").mkdir(exist_ok=True)
    bundle = {"schema": SUITE_BUNDLE_SCHEMA, "tool": TOOL, "made_up": False, "updated": now(),
              "suites_file": {"name": src.name, "text": src.read_text(encoding="utf-8")}, "title": S.data.get("title", ""),
              "suites": [], "rows": rows}
    for s in S.suites:
        report = suite_report(s, rows, when)
        (root / "reports" / f"{s['id']}-{s['version']}.md").write_text(report, encoding="utf-8")
        cases = []
        for c in s["cases"]:
            content = S.case_content(s, c)
            cases.append({"id": c["id"], "role": c["role"], "varies": c.get("varies"), "expect": c.get("expect") or {},
                          "note": c.get("note", ""), "files": content["files"],
                          "trace": [[x["tool"], x["detail"], step_mark(x), x.get("result", "")] for x in content["trace"]]
                          if content["trace"] is not None else None})
        tests = []
        for t in s["tests"]:
            tt = {k: v for k, v in t.items() if k != "files"}
            for key, f in t["files"].items():
                tt[key + "_text"] = f.read_text(encoding="utf-8", errors="replace")
            tests.append(tt)
        bundle["suites"].append({"id": s["id"], "object": s["object"], "what": s["what"], "file": s["file"], "version": s["version"],
                                 "cases": cases, "tests": tests})
    (root / "bundle.json").write_text(json.dumps(bundle, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for s in S.suites:
        L = latest(rows, s)
        say(f"\nSuite {s['id']} ({s['object']}), version {s['version']}:")
        auto = [t for t in s["tests"] if t["kind"] != "human"]
        say("  " + f"{'case':26}" + "".join(f"{t['id'][:22]:24}" for t in auto))
        for c in s["cases"]:
            say("  " + f"{c['id'][:24]:26}" + "".join(f"{(L['auto'].get((c['id'], t['id'])) or {}).get('result', '-'):24}" for t in auto))
    say(f"\n{len(new_rows)} rows added to {csv_path}. Reports in {root / 'reports'}.")
    if runner_name(a, S.data.get("runner")) == "codex":
        say(f"Next: open wizard.html and load {root / 'bundle.json'} for the human tests and your reference judgments.")
    else:
        say(f"Next, load {root / 'bundle.json'} in the wizard's step 1, for your reference judgments and the human tests. "
            + in_claude("wizard", OPEN_WIZARD) + ".")
    return 0


# --- status and ask ---------------------------------------------------------
#
# `status` says where a student is: the setup, the assistant, the
# experiments, the runs and the suites, and the one next step with the skill
# that does it in Claude and its exact command for a terminal (PY and
# OPEN_WIZARD are at the top). `ask` opens Claude Code or Codex in this
# folder as a helper (HELPER.md), given that status; with a question, it
# answers once.

def shown_path(p: Path) -> str:
    """A path as a student would type it from Skill Eval Lite's folder."""
    p = Path(p).resolve()
    cwd = Path.cwd().resolve()
    for base, prefix in ((cwd, ""), (HERE, ""), (cwd.parent, "../"), (HERE.parent, "../")):
        try:
            return prefix + p.relative_to(base).as_posix()
        except ValueError:
            pass
    return Redactor(None).text(str(p))


def tool_state(name: str, explicit: str | None) -> dict:
    """Is Claude Code or Codex installed, which version, is it logged in?
    Nothing here calls a model."""
    if name == "claude-code":
        exe = explicit or os.environ.get("SKILL_EVAL_LITE_CLAUDE") or shutil.which("claude")
    else:
        exe = explicit or os.environ.get("SKILL_EVAL_LITE_CODEX") or shutil.which("codex")
    if not exe:
        return {"installed": False}
    try:
        version = claude_version(exe) if name == "claude-code" else codex_version(exe)
    except Fail:
        version = None
    if name == "claude-code":
        st = login_state(exe)
        logged, how = (st.get("loggedIn") if st else None), (st.get("authMethod") if st else "")
    else:
        logged, how = codex_login_text(exe, dict(os.environ))
    return {"installed": True, "version": version, "logged_in": logged, "login": how or ""}


def run_folder_state(bundle_path: Path) -> dict | None:
    try:
        b = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if b.get("schema") != BUNDLE_SCHEMA:
        return None
    outs = b.get("outputs", [])
    try:
        exp = Experiment(Path(b["experiment"]["name"]), b["experiment"]["text"])
    except (Fail, KeyError, TypeError):
        exp = None
    have = {(o["prompt"], o["round"], o["repeat"]) for o in outs if o.get("status") == "ok"}
    pairs = set()
    for c in (exp.data.get("comparisons", []) if exp else []):
        for (pid, r, k) in have:
            if r == c.get("baseline") and (pid, c.get("new"), k) in have and pid not in exp.held_out:
                pairs.add((f"{c['baseline']}|{c['new']}", pid, k))
    judged = {(j.get("comparison"), j.get("prompt"), j.get("repeat")) for j in b.get("judge", []) if j.get("status", "ok") == "ok"}
    names = {o.get("runner") or (b.get("runner") or {}).get("name") or "claude-code" for o in outs}
    return {"folder": shown_path(bundle_path.parent), "experiment": (b.get("experiment") or {}).get("name"),
            "runner": names.pop() if len(names) == 1 else ("mixed" if names else None),
            "runs": len(outs), "ok": sum(o.get("status") == "ok" for o in outs),
            "failed": sum(o.get("status") == "failed" for o in outs), "timed_out": sum(o.get("status") == "timeout" for o in outs),
            "pairs": len(pairs), "judged": len(pairs & judged), "updated": b.get("updated"),
            "unfrozen": sum(o.get("frozen") is False for o in outs)}


def packet_state(f: Path) -> dict:
    """A Personal I packet: whether its suites file has problems (suite
    --check's, with no model called), whether it has run, whether it has
    changed since (a newer suites or test file, or a test whose current
    version has no rows), and whether the wizard has added human rows."""
    rows = read_rows(f.parent / "judgments.csv")
    bundle = f.parent / "bundle.json"
    x = {"file": shown_path(f), "folder": shown_path(f.parent), "has_run": bundle.is_file(), "rows": len(rows),
         "human": sum(r.get("route") == "human" for r in rows)}
    try:
        S = Suites(f)
    except Exception:  # status never stops on a broken packet: an unreadable file is one thing to fix, which --check names
        x["errors"] = 1
        return x
    x["errors"] = len(S.errors)
    if not S.errors and x["has_run"]:
        tests = [t for s in S.suites for t in s["tests"] if t.get("kind") in ("mechanical", "llm")]
        have = {(r.get("check"), r.get("version")) for r in rows if r.get("route") in ("mechanical", "llm")}
        x["changed"] = sum((t["id"], t["version"]) not in have for t in tests)
        x["llm_new"] = sum(t.get("kind") == "llm" and (t["id"], t["version"]) not in have for t in tests)
        made = bundle.stat().st_mtime
        x["newer"] = any(p.stat().st_mtime > made for p in [f] + [p for t in tests for p in t["files"].values()] if p.is_file())
    return x


def run_of(e: dict, runs: list[dict]) -> dict | None:
    """The run folder of one of your experiments, if it has one."""
    by_name = {r["experiment"]: r for r in runs}
    return next((r for n, r in by_name.items() if n and Path(n).stem in (e["name"], "experiment") and e["name"] in r["folder"]), None)


def unscored_programs(exp: Experiment, bundle_path: Path) -> int:
    """How many results of an experiment's program checks a run folder lacks (or has for another version)."""
    try:
        b = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    have = {(r.get("check"), r.get("prompt"), r.get("round"), r.get("repeat")): r for r in b.get("program_results", [])}
    n = 0
    for o in b.get("outputs", []):
        p = exp.prompts.get(o.get("prompt"))
        if not p or o.get("status") != "ok":
            continue
        for c in exp.program_checks():
            if check_applies(c, p) and not program_current(c, o, have.get((c.get("id"), o["prompt"], o["round"], o["repeat"]))):
                n += 1
    return n


def gather_status(a) -> dict:
    st = {"schema": "skill-eval-lite/status@1", "tool": TOOL, "folder": str(HERE.name)}
    git_v = git("--version", check=False).stdout.strip() if shutil.which("git") else None
    tools = {"claude-code": tool_state("claude-code", getattr(a, "claude", None)),
             "codex": tool_state("codex", getattr(a, "codex", None))}
    chosen = getattr(a, "runner", None)
    if not chosen:
        logged = [n for n in RUNNERS if tools[n].get("logged_in")]
        installed = [n for n in RUNNERS if tools[n].get("installed")]
        chosen = (logged or installed or [None])[0]
    st["setup"] = {"python": sys.version.split()[0], "python_ok": sys.version_info >= (3, 11), "git": git_v,
                   "claude_code": tools["claude-code"], "codex": tools["codex"], "runner": chosen,
                   "api_keys_set": [k for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CODEX_API_KEY") if os.environ.get(k)]}
    # The assistant.
    cands = [Path(a.assistant).expanduser()] if getattr(a, "assistant", None) else \
        [HERE.parent / "class-assistant", Path.cwd().parent / "class-assistant"]
    folder = next((c for c in cands if c.is_dir()), cands[0])
    asst = {"folder": shown_path(folder), "exists": folder.is_dir(), "claude_md": (folder / "CLAUDE.md").is_file(),
            "git": (folder / ".git").exists()}
    if asst["git"]:
        asst["commit"] = git("rev-parse", "--short", "HEAD", cwd=folder, check=False).stdout.strip()
        asst["branch"] = git("branch", "--show-current", cwd=folder, check=False).stdout.strip()
        asst["uncommitted_changes"] = bool(git("status", "--porcelain", cwd=folder, check=False).stdout.strip())
    st["assistant"] = asst
    # Experiments.
    root = Path(getattr(a, "root", None) or HERE).resolve()
    found = []
    for base in dict.fromkeys([root / "experiments", Path.cwd() / "experiments"]):
        for f in sorted(base.glob("*/experiment.toml")) + sorted(base.glob("*.toml")):
            found.append(("yours", f))
    found += [("demonstration", f) for f in sorted((HERE / "examples").glob("demo-*.toml"))]
    found += [("class example", HERE / "examples" / "class-assistant" / "experiment.toml")]
    exps, seen, loaded = [], set(), {}
    for kind, f in found:
        if not f.is_file() or f.resolve() in seen:
            continue
        seen.add(f.resolve())
        try:
            e = Experiment(f)
            loaded[shown_path(f)] = e
            errors, warns = e.problems()
            state, date = e.freeze_state()
            exps.append({"file": shown_path(f), "kind": kind, "name": e.name, "title": e.data.get("title", ""),
                         "errors": errors, "notes": len(warns), "frozen": state in ("frozen", "old"), "freeze": state,
                         "frozen_date": date, "demo": bool(e.data.get("demo")), "runner": e.model.get("runner", "claude-code")})
        except Fail as err:
            exps.append({"file": shown_path(f), "kind": kind, "name": f.stem, "errors": [str(err).splitlines()[0]],
                         "notes": 0, "frozen": False, "freeze": "unfrozen", "frozen_date": "", "demo": False})
    st["experiments"] = exps
    # Runs.
    runs, seen, bundles = [], set(), {}
    for base in dict.fromkeys([root / "runs", Path.cwd() / "runs"]):
        for b in sorted(base.glob("*/bundle.json")):
            if b.resolve() in seen:
                continue
            seen.add(b.resolve())
            r = run_folder_state(b)
            if r:
                runs.append(r)
                bundles[r["folder"]] = b
    st["runs"] = runs
    # Program checks with no result (or an old one) on the runs of your experiments.
    for e in exps:
        x, r = loaded.get(e["file"]), run_of(e, runs)
        if e["kind"] == "yours" and not e["errors"] and x and x.program_checks() and r:
            e["unscored"] = unscored_programs(x, bundles[r["folder"]])
    # Personal I packets beside Skill Eval Lite.
    suites = []
    for f in sorted(root.parent.glob("*/suites.yaml")) + sorted(root.parent.glob("*/suites.json")):
        if f.parent.resolve() in (HERE.resolve(), root.resolve()):
            continue
        suites.append(packet_state(f))
    st["suites"] = suites
    st["next_steps"] = next_steps(st, getattr(a, "project", None))
    st["next"] = st["next_steps"][0]
    st["update"] = newer_version()
    return st


def pays(st: dict, what: str = "run") -> str:
    """Who pays for a model call, from the status's own login state: an API
    key, or the plan (as doctor says)."""
    s = st["setup"]
    rn = s.get("runner")
    t = s.get("claude_code" if rn == "claude-code" else "codex") or {}
    key = (rn == "claude-code" and t.get("login") == "api_key") or (rn == "codex" and t.get("login") == "API key")
    return f"each {what} is billed to your API key" if key else f"each {what} uses a little of your plan"


def personal_hint(codex: bool = False) -> str:
    """The line for Personal I under Shared I's first steps."""
    copy = "cp -r examples/personal-suites ../my-suites"
    return ("On Personal I? You don't need Wren. Make your packet, or start from a copy of the worked example. "
            + (f"In a terminal: {copy}" if codex else in_claude("personal-i", copy)) + ".")


def next_steps(st: dict, project: str | None = None) -> list[dict]:
    """The next step for each project the student is on, each with its
    `project`: "setup" (what both need), "shared" or "personal". A Personal I
    packet beside Skill Eval Lite, and no experiment of the student's own,
    means Personal I; both mean a step for each; neither, Shared I's, with a
    line for Personal I. `project` forces one. Each step has `skill`, the
    skill that does it in Claude ("/run-suites"), and `command`, the same in a
    terminal. The skills are Claude's, so with Codex `skill` is None."""
    codex = st["setup"].get("runner") == "codex"
    return [dict(x, skill=None) if codex else x for x in _next_steps(st, project, codex)]


def _next_steps(st: dict, project: str | None, codex: bool) -> list[dict]:
    s = setup_step(st)
    if s:
        return [dict(s, project="setup")]
    packets = st.get("suites") or []
    mine = [e for e in st["experiments"] if e["kind"] == "yours"]
    if project == "personal" or (project is None and packets and not mine):
        return [dict(personal_step(st, packets), project="personal")]
    shared = dict(shared_step(st), project="shared")
    if project == "shared":
        return [shared]
    if packets:
        return [shared, dict(personal_step(st, packets), project="personal")]
    return [dict(shared, note=personal_hint(codex))]


def next_step(st: dict, project: str | None = None) -> dict:
    """The one next step, in plain words, with its skill and its exact command."""
    return next_steps(st, project)[0]


def personal_step(st: dict, packets: list[dict]) -> dict:
    """Personal I's next step, for the first packet that isn't finished: fix
    it, run it, run it again, judge and rate in the wizard, then export."""
    rflag = " --runner codex" if st["setup"]["runner"] == "codex" else ""
    if not packets:
        return {"what": "To start Personal I, make your packet in a folder beside this one: designed with Claude, or a copy "
                        "of the worked example to start from.",
                "skill": "/personal-i", "command": "cp -r examples/personal-suites ../my-suites"}
    steps = []
    for x in packets:
        cmd = f"{PY} run_ab.py suite {x['file']}"
        if x.get("errors"):
            steps.append({"what": f"Your suites file {x['file']} has {x['errors']} thing(s) to fix. Check it to see them.",
                          "skill": "/run-suites", "command": cmd + " --check"})
        elif not x["has_run"]:
            steps.append({"what": f"Run the mechanical tests on every case in {x['file']}: they call no model. The LLM tests "
                                  "come after your own reference judgments, so that their verdicts can't sway yours.",
                          "skill": "/run-suites", "command": cmd + " --no-llm"})
        elif x.get("llm_new") and not x.get("human"):
            steps.append({"what": f"Before the LLM tests run, open the wizard and load {x['folder']}/bundle.json in step 1. Judge "
                                  "each LLM test's criterion yourself (Reference), then export judgments.csv into "
                                  f"{x['folder']}/. Then run the LLM tests ({pays(st, 'LLM test run')}).",
                          "skill": "/wizard", "command": OPEN_WIZARD})
        elif x.get("changed") or x.get("newer"):
            steps.append({"what": f"Run {x['file']} again: " + (f"{x['changed']} test(s) have changed since the last run, or have no "
                                                                "results yet" if x.get("changed") else
                                                                "the suites file or a test's file has changed since the last run")
                                  + f" ({pays(st, 'LLM test run')}).", "skill": "/run-suites", "command": cmd + rflag})
        elif not x.get("human"):
            steps.append({"what": f"Open the wizard and load {x['folder']}/bundle.json in step 1. Judge each LLM test's criterion "
                                  "yourself (Reference), then rate the cases (Human tests).", "skill": "/wizard", "command": OPEN_WIZARD})
        else:
            steps.append({"what": f"In the wizard's Report step, export judgments.csv into {x['folder']}/ and each report into "
                                  f"{x['folder']}/reports/. Then ask a classmate to rate the same cases.",
                          "skill": "/wizard", "command": OPEN_WIZARD, "done": True})
    s = next((s for s in steps if not s.get("done")), steps[0])
    s.pop("done", None)
    return s


def setup_step(st: dict) -> dict | None:
    """What both projects need first: Python, git, Claude Code or Codex, and its login."""
    s = st["setup"]
    rn = s["runner"]
    if not s["python_ok"]:
        return {"what": "Install Python 3.11 or later (https://www.python.org/downloads/), then run this again.",
                "skill": "/get-ready", "command": f"{PY} run_ab.py status"}
    if not s["git"]:
        return {"what": "Install git (https://git-scm.com/downloads), then run this again.",
                "skill": "/get-ready", "command": f"{PY} run_ab.py status"}
    if rn is None:
        return {"what": "Install Claude Code, or Codex if your paid plan is ChatGPT's. You need only one. "
                        "The README's \"What you need\" shows how; then run this again.",
                "skill": "/get-ready", "command": INSTALL_CLAUDE}
    tool = s["claude_code" if rn == "claude-code" else "codex"]
    if not tool.get("installed"):
        return {"what": f"Install {RUNNER_LABEL[rn]} (the README's \"What you need\" shows how), then run this again.",
                "skill": "/get-ready", "command": f"{PY} run_ab.py status"}
    if tool.get("logged_in") is False:
        if rn == "codex":
            return {"what": "Log in to Codex: this opens your browser; sign in with the ChatGPT account that has your plan.",
                    "skill": None, "command": "codex login"}
        return {"what": "Sign the `claude` command in, once, with the Claude account that has your plan: a page opens in "
                        "your browser.", "skill": "/get-ready", "command": "claude auth login"}
    return None


def shared_step(st: dict) -> dict:
    """Shared I's next step (and the demonstrations'): the class assistant,
    your experiments, their runs. A group's own experiment goes through
    /run-experiment; the demonstrations, which aren't frozen, through the
    helper, whose steps run them."""
    s, asst = st["setup"], st["assistant"]
    rn = s["runner"]
    rflag = " --runner codex" if rn == "codex" else ""
    if not asst["exists"]:
        return {"what": "Set up the class assistant, Wren, in a folder beside this one (about a minute; it needs the internet).",
                "skill": "/get-ready", "command": f"{PY} run_ab.py setup ../class-assistant"}
    if not asst["claude_md"]:
        return {"what": f"{asst['folder']} has no CLAUDE.md, so it doesn't look like an assistant's folder. "
                        "Check the folder, or set up the class assistant in a new one.",
                "skill": "/get-ready", "command": f"{PY} run_ab.py setup ../class-assistant"}
    a_flag = "" if asst["folder"] == "../class-assistant" else f" (your assistant is in {asst['folder']})"
    mine = [e for e in st["experiments"] if e["kind"] == "yours"]
    for e in mine:
        if e["errors"]:
            return {"what": f"Your experiment {e['file']} has {len(e['errors'])} thing(s) to fix. Check it to see them.",
                    "skill": "/skill-eval-helper", "command": f"{PY} run_ab.py check {e['file']}"}
        if e.get("freeze") == "changed":
            return {"what": f"Your experiment {e['file']} has changed since it was frozen on {e['frozen_date']}. Freeze it again in the wizard "
                            "(step 1, then Freeze in step 2 and 'Export the frozen experiment'), then save it over the old file. Keep "
                            "the earlier file, dated: your report says what you changed and why.",
                    "skill": "/wizard", "command": OPEN_WIZARD}
        if not e["frozen"]:
            return {"what": f"Your experiment {e['file']} is ready to freeze. " + "Freeze it in the wizard: load it in step 1, press Freeze in step 2, then press 'Export the frozen experiment' "
                            f"(now in step 2) and save the file over {e['file']}.",
                    "skill": "/wizard", "command": OPEN_WIZARD}
        r = run_of(e, st["runs"])
        if not r:
            return {"what": f"Run rounds A and B of your experiment{a_flag} (the controls C and D come next).",
                    "skill": "/run-experiment",
                    "command": f"{PY} run_ab.py run {e['file']} --assistant {asst['folder']} --rounds A,B --jobs 4{rflag}"}
        if e.get("unscored"):
            return {"what": f"Run the program checks of {e['file']} on the runs in {r['folder']}: {e['unscored']} of their "
                            "results are missing or out of date. No model is called.",
                    "skill": "/run-experiment", "command": f"{PY} run_ab.py score {e['file']} --out {r['folder']}"}
        if r["judged"] < r["pairs"]:
            return {"what": f"Run the LLM judge on {r['folder']}: it reads each blind pair and says which is better.",
                    "skill": "/run-experiment", "command": f"{PY} run_ab.py judge {r['folder']}"}
    if mine:
        return {"what": f"Open the wizard and load {st['runs'][-1]['folder'] if st['runs'] else 'your run folder'}/bundle.json "
                        "in step 1: judge the blind pairs (step 4) and read the results (step 5).",
                "skill": "/wizard", "command": OPEN_WIZARD}
    if not st["runs"]:
        return {"what": "Try the first demonstration: six runs of the class assistant, with and without one line added "
                        f"to its voice file (about half a minute; {pays(st)}).",
                "skill": "/skill-eval-helper",
                "command": f"{PY} run_ab.py run examples/demo-one-line.toml --assistant {asst['folder']} --jobs 6{rflag}"}
    for r in st["runs"]:
        if r["ok"] == 0 and r["runs"]:
            return {"what": f"Every run in {r['folder']} failed. Run the setup check to see why.",
                    "skill": "/get-ready", "command": f"{PY} run_ab.py doctor{rflag}"}
        if r["judged"] < r["pairs"]:
            return {"what": f"Run the LLM judge on {r['folder']}: it reads each blind pair and says which is better (about a minute).",
                    "skill": "/skill-eval-helper", "command": f"{PY} run_ab.py judge {r['folder']}"}
    new = f"{PY} run_ab.py new <name> --from class"
    if rn == "codex":
        then = (f"to adapt the class experiment, `{new}`; for your own assistant, the intake: start `codex` here and ask "
                "it to follow AGENTS.md.")
    else:
        then = ("copy the class experiment and change it, or write one for your own assistant with the intake. "
                + in_claude("shared-i", new) + ".")
    return {"what": f"Open the wizard, load {st['runs'][0]['folder']}/bundle.json in step 1 and look at the results. Then "
                    "make your group's experiment: " + then, "skill": "/wizard", "command": OPEN_WIZARD}


def status_text(st: dict) -> str:
    s, asst = st["setup"], st["assistant"]
    L = [f"Skill Eval Lite {VERSION}: where you are now", ""]
    if st.get("update"):
        L += ["  NEW  " + update_text(st["update"], s["runner"] == "codex"), ""]
    L.append("Your setup")

    def mark(good):
        return {True: "ok  ", False: "FIX ", None: "--  "}[good]
    L.append(f"  {mark(s['python_ok'])} Python {s['python']}")
    L.append(f"  {mark(bool(s['git']))} " + (s["git"] or "git: not installed"))
    for key, name in (("claude_code", "claude-code"), ("codex", "codex")):
        t = s[key]
        label = RUNNER_LABEL[name]
        if not t.get("installed"):
            L.append(f"  --   {label}: not installed")
        elif t.get("logged_in") is False:
            L.append(f"  {mark(False if s['runner'] == name else None)} {label} {t.get('version')}: not logged in")
        else:
            L.append(f"  ok   {label} {t.get('version')}: logged in" + (f" ({t['login']})" if t.get("login") else "")
                     + (": runs are billed to the key" if t.get("login") in ("api_key", "API key") else ""))
    if s["runner"]:
        other = "codex" if s["runner"] == "claude-code" else "claude-code"
        L.append(f"  You need only one of the two. This status uses {RUNNER_LABEL[s['runner']]}"
                 + (f"; add --runner {other} for {RUNNER_LABEL[other]}." if s[other.replace('-', '_')].get("installed") else "."))
    L += ["", "The assistant"]
    if not asst["exists"]:
        L.append(f"  --   {asst['folder']}: not set up yet (Shared I and the demonstrations need it; Personal I's suites don't)")
    else:
        bits = ["a git project" if asst["git"] else "not a git project",
                "with a CLAUDE.md" if asst["claude_md"] else "with no CLAUDE.md"]
        extra = f" (commit {asst.get('commit')}, branch {asst.get('branch') or '?'}" + \
                (", with changes not committed" if asst.get("uncommitted_changes") else "") + ")" if asst["git"] else ""
        L.append(f"  {mark(asst['claude_md'])} {asst['folder']}: {' '.join(bits)}{extra}")
    L += ["", "Experiments"]
    for e in st["experiments"]:
        if e["errors"]:
            state = f"{len(e['errors'])} thing(s) to fix"
        elif e["demo"]:
            state = "ready to run"
        elif e.get("freeze") == "changed":
            state = "changed since it was frozen: freeze it again"
        else:
            state = "frozen, ready to run" if e["frozen"] else "ready to freeze in the wizard"
        L.append(f"  {e['file']:44} {e['kind']}: {state}")
    if not any(e["kind"] == "yours" for e in st["experiments"]):
        L.append("  (none of your own yet: they go in experiments/<name>/)")
    L += ["", "Runs"]
    for r in st["runs"]:
        fails = r["failed"] + r["timed_out"]
        L.append(f"  {r['folder']:36} {RUNNER_LABEL.get(r['runner'], r['runner'] or '?'):12} {r['ok']} of {r['runs']} finished"
                 + (f" ({fails} failed)" if fails else "") + f"; judge: {r['judged']} of {r['pairs']} pairs"
                 + (f"; {r['unfrozen']} made before the freeze" if r.get("unfrozen") else ""))
    if not st["runs"]:
        L.append("  none yet")
    if st["suites"]:
        L += ["", "Personal I packets"]
        for x in st["suites"]:
            L.append(f"  {x['file']:44} " + (f"{x['errors']} thing(s) to fix" if x.get("errors") else
                                              f"run, {x['rows']} rows in judgments.csv" if x["has_run"] else "not run yet"))
    steps = st.get("next_steps") or [st["next"]]
    heads = {"shared": "Next step, Shared I", "personal": "Next step, Personal I"}
    for n in steps:
        L += ["", heads.get(n.get("project"), "Next step") if len(steps) > 1 else "Next step", "  " + n["what"]]
        if n.get("skill"):
            # The one form, its two halves on two lines: the skill, then the command for a terminal.
            way, _, terminal = in_claude(n["skill"], n.get("command")).partition(" (")
            L += ["", "      " + way] + (["      (" + terminal] if terminal else [])
        elif n.get("command"):
            L += ["", "      " + n["command"]]
        if n.get("note"):
            L += ["", "  " + n["note"]]
    return "\n".join(L) + "\n"


def cmd_status(a) -> int:
    st = gather_status(a)
    if a.json:
        print(json.dumps(st, indent=1, ensure_ascii=False))
    else:
        say(status_text(st))
    return 0


def cmd_new(a) -> int:
    """Copy an experiment (the class experiment, or another file) into
    experiments/<name>/ for a group to adapt; without --from, point to the intake."""
    name = a.name
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", name or ""):
        raise Fail(f"{name!r} can't be an experiment's name. Use small letters, digits and dashes, "
                   "for example board-memo.")
    dest = Path(getattr(a, "root", None) or HERE) / "experiments" / name
    if not a.source:
        say(f"To write a new experiment for your group's own assistant, use the intake. It asks your group a few\n"
            f"questions and writes {shown_path(dest)}/experiment.toml for you.\n"
            + in_claude("experiment-intake ../<your assistant's folder>") + ". (With Codex, start `codex` here and ask it "
            "to follow AGENTS.md.)\n\n"
            "To start from the class experiment instead (the class assistant, Wren), copy it.\n"
            + in_claude("shared-i", f"{PY} run_ab.py new {name} --from class") + ".")
        return 0
    src = HERE / "examples" / "class-assistant" / "experiment.toml" if a.source == "class" else Path(a.source).expanduser()
    if src.is_dir():
        src = src / "experiment.toml"
    if not src.is_file():
        raise Fail(f"There is no experiment file at {a.source}. Use --from class for the class experiment, "
                   "or give the path of an experiment.toml.")
    if dest.exists() and any(dest.iterdir()):
        raise Fail(f"{shown_path(dest)} already exists and is not empty, so nothing was copied.\n"
                   "Choose another name, or work on that one. "
                   + in_claude("shared-i", f"{PY} run_ab.py check {shown_path(dest)}/experiment.toml") + ".")
    exp = Experiment(src)
    text = exp.text
    if exp.data.get("files_from") not in (None, "."):
        text = re.sub(r"(?m)^files_from\s*=.*\n", "", text)
    text = re.sub(r'(?ms)^(\[frozen\]\s*\n)date\s*=\s*"[^"]*"\s*\nhash\s*=\s*"[^"]*"', r'\1date = ""\nhash = ""', text)
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for sub in ("rounds", "prompts"):
        if (exp.base / sub).is_dir():
            shutil.copytree(exp.base / sub, dest / sub)
            copied.append(f"{sub}/ ({', '.join(sorted(p.name for p in (dest / sub).iterdir() if p.is_dir()))})")
    # The program checks' folders: only those the experiment uses.
    progs = sorted({PurePosixPath(c["program"]).parent.as_posix() for c in exp.program_checks() if program_path_ok(c.get("program"))})
    for folder in progs:
        if (exp.base / folder).is_dir():
            shutil.copytree(exp.base / folder, dest / folder, ignore=shutil.ignore_patterns("__pycache__"))
    if progs:
        copied.append(f"checks/ ({', '.join(PurePosixPath(f).name for f in progs)})")
    (dest / "experiment.toml").write_text(text, encoding="utf-8")
    errors, _ = Experiment(dest / "experiment.toml").problems()
    what = "the class experiment" if a.source == "class" else shown_path(src)
    say(f"Made {shown_path(dest)}/ from {what}: experiment.toml" + (", " + ", ".join(copied) if copied else "") + ".")
    if errors:
        say("The copy has things to fix (its files may not all have come along):")
        for e in errors:
            say("  must fix:  " + e)
    say(f"\nNext, read {shown_path(dest)}/experiment.toml together, change what your group wants to test, then check it.\n"
        + in_claude("shared-i", f"{PY} run_ab.py check {shown_path(dest)}/experiment.toml; for help, {PY} run_ab.py ask") + ".")
    return 0


ASK_OPENING = "Hello! Please help me with Skill Eval Lite."
ASK_ONCE = ("This time the student asks one question and can't answer back. Answer it once, in plain words, from the "
            "status above and README.md (read it if you need to): a few short lines, and the exact command if there is "
            "one. Don't ask a question back, and don't run anything.")


def helper_prompt(st: dict, once: bool) -> str:
    text = (HERE / "HELPER.md").read_text(encoding="utf-8")
    text = re.sub(r"\A<!--.*?-->\s*", "", text, flags=re.S)
    text += "\n\n## Where the student is now\n\n(from `python3 run_ab.py status`, just now)\n\n```\n" + status_text(st) + "```\n"
    return text + ("\n" + ASK_ONCE + "\n" if once else "")


def codex_helper_config(prompt: str, interactive: bool):
    """The helper's Codex config: the runs' isolation (no personal config,
    MCP servers, connectors, plugins, skills, hooks or memories), with the
    student's approval asked before anything outside the sandbox; one-shot
    answers read only."""
    def make(read_paths, skills_off):
        q = json.dumps
        lines = ["# Written by Skill Eval Lite (run_ab.py ask); deleted when the session ends.",
                 f'approval_policy = "{"on-request" if interactive else "never"}"',
                 f'sandbox_mode = "{"workspace-write" if interactive else "read-only"}"',
                 "allow_login_shell = false", 'web_search = "disabled"', "check_for_update_on_startup = false",
                 f"developer_instructions = {q(prompt)}", "", "[sandbox_workspace_write]", "network_access = false", "",
                 "[history]", 'persistence = "none"', "", "[memories]", "use_memories = false", "generate_memories = false",
                 "", "[analytics]", "enabled = false", "", "[shell_environment_policy]", 'inherit = "core"', "", "[features]"]
        lines += [f"{f} = false" for f in CODEX_FEATURES_OFF]
        for sp in skills_off:
            lines += ["", "[[skills.config]]", f"path = {q(str(sp))}", "enabled = false"]
        lines += ["", f"[projects.{q(str(HERE))}]", 'trust_level = "trusted"', ""]
        return "\n".join(lines)
    return make


def ask_command(name: str, exe: str, st: dict, question: str, home: CodexHome | None = None) -> dict:
    """What `ask` runs: the program and its arguments, the folder, the
    environment and what goes on its input. No model is called here."""
    once = bool(question)
    prompt = helper_prompt(st, once)
    if name == "claude-code":
        base = ["--setting-sources", "project", "--strict-mcp-config",
                "--settings", json.dumps(ISOLATION_SETTINGS, separators=(",", ":")), "--append-system-prompt", prompt]
        if once:
            argv = [exe, "-p", "--output-format", "text", *base, "--tools", "Read,Glob,Grep",
                    "--permission-prompts", "none", "--no-session-persistence"]
            return {"argv": argv, "cwd": HERE, "env": child_env(), "stdin": question + "\n"}
        # Permission prompts stay on: "manual" asks before every command or edit,
        # whatever default the person has set (an "auto" default would not ask).
        return {"argv": [exe, *base, "--permission-mode", "manual", "-n", "Skill Eval Lite helper", ASK_OPENING],
                "cwd": HERE, "env": child_env(), "stdin": None}
    if once:
        argv = [exe, "exec", "--json", "--ephemeral", "--skip-git-repo-check", "-"]
        return {"argv": argv, "cwd": HERE, "env": home.env() if home else {}, "stdin": question + "\n"}
    return {"argv": [exe, ASK_OPENING], "cwd": HERE, "env": home.env() if home else {}, "stdin": None}


def cmd_ask(a) -> int:
    question = " ".join(a.question or []).strip()
    st = gather_status(a)
    name = st["setup"]["runner"]
    if not name:
        raise Fail("Neither Claude Code nor Codex is installed, so there is nobody to ask yet.\n"
                   + in_claude("get-ready", "install one of them as the README's \"What you need\" shows, then try again") + ".")
    tool = st["setup"]["claude_code" if name == "claude-code" else "codex"]
    if not tool.get("installed"):
        if name == "codex":
            raise Fail(f"Codex is not installed. Install it, or ask the other one: {PY} run_ab.py ask --runner claude-code")
        raise Fail("Claude Code is not installed. "
                   + in_claude("get-ready", f"install it, or ask the other one: {PY} run_ab.py ask --runner codex") + ".")
    if tool.get("logged_in") is False:
        raise Fail(CODEX_NOT_LOGGED_IN if name == "codex" else NOT_LOGGED_IN)
    exe = find_codex(a.codex) if name == "codex" else find_claude(a.claude)
    home = None
    if name == "codex":
        home = CodexHome(exe, a.use_api_key, codex_helper_config(helper_prompt(st, bool(question)), not question)).__enter__()
    try:
        cmd = ask_command(name, exe, st, question, home)
        if a.show_command:
            env = cmd["env"]
            print(json.dumps({"argv": cmd["argv"], "cwd": str(cmd["cwd"]), "stdin": cmd["stdin"],
                              "env": {k: env[k] for k in sorted(env) if k.startswith(("CODEX_HOME", "ENABLE_CLAUDEAI", "CLAUDE_CODE_DISABLE"))},
                              "env_names": sorted(env),
                              "config": (home.path / "config.toml").read_text(encoding="utf-8") if home else None}, indent=1))
            return 0
        if not question:
            say(f"Starting {RUNNER_LABEL[name]} as your helper, in this folder. It knows where you are (python3 run_ab.py status)\n"
                "and will ask you before it runs anything. Type /exit (or press Ctrl+C twice) when you are done.\n"
                + ("If Claude Code first asks whether you trust this folder, choose Yes (it is Skill Eval Lite's own folder):\n"
                   "press the down arrow key, then Enter.\n" if name == "claude-code" else ""))
            code = subprocess.run(cmd["argv"], cwd=cmd["cwd"], env=cmd["env"]).returncode
            if name == "codex":
                say("\n(The helper session is not kept, so `codex resume` can't reopen it. "
                    "To start again: python3 run_ab.py ask --runner codex)")
            return code
        say(f"Asking {RUNNER_LABEL[name]}... (a few seconds)\n")
        if name == "claude-code":
            return subprocess.run(cmd["argv"], cwd=cmd["cwd"], env=cmd["env"], input=cmd["stdin"], text=True).returncode
        run = CodexRun(cmd["argv"], cmd["cwd"], cmd["stdin"], 300, cmd["env"], set(), ([], {}), "").run()
        if run.ok and run.final:
            say(run.final.strip())
            return 0
        say(("Codex is not logged in. " + CODEX_NOT_LOGGED_IN) if run.not_logged_in else
            "Codex didn't answer: " + run.failure, err=True)
        return 1
    finally:
        if home:
            home.close()


# --- main -----------------------------------------------------------------

def add_runner_args(s, model_help=None):
    s.add_argument("--runner", choices=RUNNERS, help="claude-code or codex (default: the experiment's [model] runner, else claude-code)")
    s.add_argument("--claude", help="the claude program to use (default: the one on your PATH)")
    s.add_argument("--codex", help="the codex program to use (default: the one on your PATH)")
    s.add_argument("--use-api-key", action="store_true",
                   help="Codex only: use OPENAI_API_KEY (billed to the key) instead of your ChatGPT plan's login")
    if model_help:
        s.add_argument("--model", help=model_help)


def parser() -> argparse.ArgumentParser:
    """Every command and option (the tests read it to check that the skills
    name only commands and options that exist)."""
    ap = argparse.ArgumentParser(prog="run_ab.py", description="Skill Eval Lite's runner: run an assistant's rounds on an "
                                 "experiment's prompts with Claude Code or Codex, isolated, and judge blind pairs.")
    ap.add_argument("--version", action="version", version=TOOL)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("setup", help="set up the class assistant (the template from GitHub plus the class overlay) in a new folder")
    s.add_argument("folder", help="a new folder, for example ../class-assistant")
    s.add_argument("--from", dest="source", help="clone from here instead of the template's GitHub URL")
    s.add_argument("--commit", help="the template commit to use (default: the pinned one)")
    s.set_defaults(fn=cmd_setup)

    s = sub.add_parser("doctor", help="check Python, git, Claude Code or Codex, the login, and that runs are isolated")
    add_runner_args(s, "the model for the isolation probe (default: haiku for Claude Code, " + CODEX_PROBE_MODEL + " for Codex)")
    s.add_argument("--no-probe", action="store_true", help="skip the probe run (nothing is sent to a model)")
    s.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("updates", help="whether Skill Eval Lite and the brief folders beside it are up to date (reads only)")
    s.add_argument("--json", action="store_true", help="the report as JSON")
    s.add_argument("--hook", action="store_true", help="for Claude Code's SessionStart hook: a line only when something "
                   "is newer, at most one check a day, never a failure")
    s.add_argument("--again", action="store_true", help="check now, even if the last check was today")
    s.add_argument("--workspace", help="the folder that holds Skill Eval Lite and the brief folders (default: ..)")
    s.set_defaults(fn=cmd_updates)

    s = sub.add_parser("update", help="bring in a newer Skill Eval Lite or brief folder, keeping your own files")
    s.add_argument("--self", action="store_true", help="Skill Eval Lite itself: git pull, or the newest ZIP for a ZIP copy")
    s.add_argument("--brief", action="append", help="a brief folder, e.g. ../ai5500-shared-1 (may be given more than once)")
    s.add_argument("--dry-run", action="store_true", help="say what it would change, and change nothing")
    s.set_defaults(fn=cmd_update)

    s = sub.add_parser("status", help="where you are: the setup, the assistant, experiments, runs, and the next step")
    s.add_argument("--assistant", help="the assistant's folder (default: ../class-assistant)")
    s.add_argument("--runner", choices=RUNNERS, help="claude-code or codex (default: the one you are logged in to)")
    s.add_argument("--claude", help=argparse.SUPPRESS)
    s.add_argument("--codex", help=argparse.SUPPRESS)
    s.add_argument("--json", action="store_true", help="print the same as JSON")
    s.add_argument("--project", choices=("shared", "personal"),
                   help="give this project's next step (default: Personal I when there is a packet and no experiment of yours)")
    s.add_argument("--root", help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("ask", help="get help from Claude Code or Codex, step by step; or ask one question")
    s.add_argument("question", nargs="*", help='a question to answer once, e.g. "how do I freeze my experiment?"')
    s.add_argument("--assistant", help="the assistant's folder (default: ../class-assistant)")
    add_runner_args(s)
    s.add_argument("--project", choices=("shared", "personal"), help="the project you are on, if status can't tell")
    s.add_argument("--show-command", action="store_true", help=argparse.SUPPRESS)
    s.add_argument("--root", help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_ask)

    s = sub.add_parser("new", help="copy the class experiment into experiments/<name>/ for your group to adapt")
    s.add_argument("name", help="a short name for the experiment, e.g. board-memo")
    s.add_argument("--from", dest="source", help='"class" for the class experiment, or the path of another experiment.toml')
    s.add_argument("--root", help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_new)

    s = sub.add_parser("check", help="check an experiment file")
    s.add_argument("experiment")
    s.set_defaults(fn=cmd_check)

    for name, fn, hlp in (("plan", cmd_plan, "list the runs an experiment would make"), ("run", cmd_run, "run the experiment")):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("experiment")
        if name == "run":
            s.add_argument("--assistant", required=True, help="the assistant's folder (a git project), e.g. ../class-assistant")
            s.add_argument("--out", help="the run folder (default: runs/<experiment name>, or runs/<name>-codex for "
                                         "--runner codex on an experiment written for Claude Code)")
            s.add_argument("--again", action="store_true", help="redo runs already in the run folder (replacing them)")
            s.add_argument("--keep-work", action="store_true", help="keep each run's working copy, and print where")
            s.add_argument("--unfrozen", action="store_true", help="run an experiment that isn't frozen, or has changed since it was "
                                                                   "(the runs are marked as made before the freeze)")
            add_runner_args(s, "the model for every run (default: the experiment's)")
        else:
            s.add_argument("--runner", choices=RUNNERS, help="claude-code or codex (default: the experiment's)")
            s.add_argument("--model", help="the model for every run (default: the experiment's)")
        s.add_argument("--rounds", help="only these rounds, e.g. A,C")
        s.add_argument("--prompts", help="only these prompts, e.g. reply-to-priya,prep-dana-checkin")
        s.add_argument("--repeats", type=int, help="repeats per prompt and round (default: the experiment's)")
        s.add_argument("--held-out", action="store_true", help="include (unseal) the held-out prompts")
        s.add_argument("--jobs", type=int, default=1, help="runs at the same time (default 1)")
        s.set_defaults(fn=fn)

    s = sub.add_parser("judge", help="run the experiment's LLM judge on the blind pairs in a run folder")
    s.add_argument("folder", help="the run folder, e.g. runs/demo-graph-removed")
    s.add_argument("--comparisons", help="only these comparisons, e.g. A-B,A-C")
    s.add_argument("--jobs", type=int, default=4, help="judgments at the same time (default 4)")
    s.add_argument("--again", action="store_true", help="judge pairs again that this model has judged")
    s.add_argument("--held-out", action="store_true", help="also judge the held-out confirmation: the baseline round against each "
                                                           "round run on the held-out prompts")
    s.add_argument("--budget", type=float, default=0.50, help="Claude Code only: the most one judgment may cost, in dollars (default 0.50)")
    s.add_argument("--timeout", type=int, default=180, help="seconds before a judgment counts as timed out (default 180)")
    add_runner_args(s, "the judge's model (default: the experiment's [judge] model)")
    s.set_defaults(fn=cmd_judge)

    s = sub.add_parser("score", help="run an experiment's program checks on the outputs in a run folder (no model is called)")
    s.add_argument("experiment", help="the experiment file whose program checks to run")
    s.add_argument("--out", help="the run folder (default: runs/<experiment name>)")
    s.add_argument("--checks", help="only these program checks, e.g. looked-up-first")
    s.add_argument("--again", action="store_true", help="run them again on outputs that already have a result")
    s.add_argument("--jobs", type=int, default=4, help="programs at the same time (default 4)")
    s.set_defaults(fn=cmd_score)

    s = sub.add_parser("suite", help="Personal I: run every mechanical and LLM test of a suites file on every case")
    s.add_argument("suites", help="the suites file, e.g. my-suites/suites.yaml")
    s.add_argument("--suite", help="only these suites, e.g. replies")
    s.add_argument("--tests", help="only these tests")
    s.add_argument("--cases", help="only these cases")
    s.add_argument("--out", help="copy the packet here and run there (default: in the suites file's folder)")
    s.add_argument("--again", action="store_true", help="rerun LLM tests already run for their current version")
    s.add_argument("--no-llm", action="store_true", help="run the mechanical tests only")
    s.add_argument("--check", action="store_true", help="check the suites file, and run nothing")
    s.add_argument("--jobs", type=int, default=4, help="LLM runs at the same time (default 4)")
    add_runner_args(s)
    s.set_defaults(fn=cmd_suite)
    return ap


def main(argv=None) -> int:
    a = parser().parse_args(argv)
    try:
        return a.fn(a)
    except Fail as e:
        say(str(e), err=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())

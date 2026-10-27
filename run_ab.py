#!/usr/bin/env python3
"""run_ab.py: Skill Eval Lite's runner.

Runs an assistant (a folder of Claude Code instructions, such as the AI 5100
assistant template) on the prompts of an experiment, once per round and
repeat, in a fresh copy each time, with Claude Code in print mode; keeps every
output, run record and trace; writes a bundle that the wizard (wizard.html)
loads; and runs an LLM judge on blind pairs.

    python3 run_ab.py setup ../class-assistant          the class assistant, from GitHub
    python3 run_ab.py doctor                            Python, git, Claude Code, login, isolation
    python3 run_ab.py check examples/demo-graph-removed.toml
    python3 run_ab.py plan  examples/demo-graph-removed.toml
    python3 run_ab.py run   examples/demo-graph-removed.toml --assistant ../class-assistant --jobs 4
    python3 run_ab.py judge runs/demo-graph-removed
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
    sys.exit("Skill Eval Lite needs Python 3.11 or later (for tomllib); this is " + sys.version.split()[0] + ".")

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
CHECK_KINDS = {"contains", "not-contains", "matches", "word-count", "json-parses",
               "trace-ran-command", "trace-no-tool-outside"}
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


def say(*parts, err=False):
    print(*parts, file=sys.stderr if err else sys.stdout, flush=True)


class Fail(Exception):
    """A problem the person can fix; the message says how."""


def find_claude(explicit: str | None = None) -> str:
    exe = explicit or os.environ.get("SKILL_EVAL_LITE_CLAUDE") or shutil.which("claude")
    if not exe:
        raise Fail("Claude Code is not installed, or `claude` is not on your PATH.\n"
                   "Install it (https://docs.claude.com/en/docs/claude-code/setup), run `claude` once to log in, "
                   "type /exit, and try again.")
    return exe


def claude_version(exe: str) -> str:
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=60, env=child_env())
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Fail(f"Claude Code didn't answer `claude --version` ({e}).\n"
                   "Check that it is installed: type `claude --version` in a terminal.")
    m = re.search(r"\d+\.\d+\.\d+", out.stdout + out.stderr)
    return m.group(0) if m else (out.stdout.strip() or "unknown")


def login_state(exe: str) -> dict:
    """`claude auth status`, which reports the login without calling a model."""
    try:
        out = subprocess.run([exe, "auth", "status"], capture_output=True, text=True, timeout=60, env=child_env())
        return json.loads(out.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {}


NOT_LOGGED_IN = ("Claude Code is not logged in on this computer.\n"
                 "Run `claude` in a terminal, log in with your Claude account when it asks, type /exit,\n"
                 "and then run this command again.")


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
        for c in d.get("checks", []):
            if c.get("kind") not in CHECK_KINDS:
                errors.append(f"Check {c.get('id')!r} has a kind Skill Eval Lite doesn't know: {c.get('kind')!r}. "
                              f"Use one of: {', '.join(sorted(CHECK_KINDS))}.")
            if c.get("object") not in ("product", "process"):
                warns.append(f"Check {c.get('id')!r}: set object = \"product\" (it checks the output) or \"process\" (it checks the steps).")
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
# private samples, earlier outputs, and the intake skill.
EXCLUDE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "drafts", "notes", "research"}
EXCLUDE_FILES = {".claude/settings.local.json", "CLAUDE.local.md", ".claude/setup/answers.md", ".DS_Store"}
EXCLUDE_TREES = {".claude/skills/experiment-intake", ".claude/skills/skill-eval-helper", "writing-samples"}
INTAKE_MARK = "skill-eval-lite experiment-intake"
HELPER_MARK = "skill-eval-lite helper"


def copy_assistant(src: Path, dst: Path, skip: set[Path] = frozenset()) -> None:
    src = src.resolve()
    for root, dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        keep = []
        for d in dirs:
            r = (rel / d).as_posix()
            if d in EXCLUDE_DIRS and rel == Path(".") or d == ".git" or r in EXCLUDE_TREES or (Path(root) / d).resolve() in skip:
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
                           "Move or rename that file, or use another temporary folder, for example:\n"
                           "    mkdir -p ~/skill-eval-tmp && export TMPDIR=~/skill-eval-tmp")
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
        d = inp.get("command", "")
    elif name in ("Read", "Write", "Edit", "NotebookEdit"):
        d = inp.get("file_path") or inp.get("notebook_path") or ""
    elif name in ("Glob", "Grep"):
        d = inp.get("pattern", "") + (" in " + inp["path"] if inp.get("path") else "")
    elif name == "Skill":
        d = inp.get("skill") or inp.get("command") or json.dumps(inp)
    else:
        d = json.dumps(inp, ensure_ascii=False)
    d = red.text(str(d))
    return d[2:] if d.startswith("./") else d


def trace_of(events: list[dict], red: Redactor, results: bool = False) -> list[dict]:
    """The steps of a session: tool, detail and whether it failed; with
    results=True, also the first 400 characters of what each step returned.
    A Codex stream is read by codex_steps."""
    if is_codex_stream(events):
        return codex_steps(events, red, results)
    steps, by_id = [], {}
    for e in events:
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
                    by_id[c["tool_use_id"]]["error"] = bool(c.get("is_error"))
                    if results:
                        body = c.get("content")
                        if isinstance(body, list):
                            body = " ".join(b.get("text", "") for b in body if isinstance(b, dict))
                        by_id[c["tool_use_id"]]["result"] = red.text(str(body or ""))[:400]
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
        for ch in item.get("changes") or []:
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
        raise Fail("git is not installed. Install it (https://git-scm.com/downloads) and run this again.")
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
    say("Next, check your setup (if you haven't yet), then run the first demonstration:")
    say("    python3 run_ab.py doctor")
    say(f"    python3 run_ab.py run examples/demo-one-line.toml --assistant {a.folder} --jobs 6")
    return 0


# --- check and plan -------------------------------------------------------

def load(path: str) -> Experiment:
    p = Path(path)
    if not p.is_file():
        raise Fail(f"There is no experiment file at {path}. Check the path; `python3 run_ab.py status` lists the ones there are.")
    return Experiment(p)


def cmd_check(a) -> int:
    exp = load(a.experiment)
    errors, warns = exp.problems()
    say(f"{exp.path}: {exp.data.get('title', '(no title)')}")
    for e in errors:
        say("  must fix:  " + e)
    for w in warns:
        say(("  (demo)    " if exp.data.get("demo") else "  to do:     ") + w)
    if not errors and not warns:
        say("  Nothing is missing.")
    if exp.data.get("demo") and warns:
        say("  This file is a demonstration (demo = true); the (demo) lines are what a full experiment would also need.")
    frozen = (exp.data.get("frozen") or {}).get("hash")
    say("  Frozen: " + (f"yes, {exp.data['frozen'].get('date')}" if frozen else "not yet (the wizard's step 2 freezes it)"))
    if errors:
        say(f"\nFix the lines marked \"must fix\", save the file, and check it again:\n    python3 run_ab.py check {a.experiment}")
    elif exp.data.get("demo") or frozen:
        say(f"\nNext, run it:\n    python3 run_ab.py run {a.experiment} --assistant ../class-assistant --jobs 4")
    else:
        say("\nNext, freeze it in the wizard: load it in step 1, press Freeze in step 2, then press 'Export the frozen "
            f"experiment' (now in step 2) and save the file over {a.experiment}.")
    return 1 if errors else 0


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
        say("\nFix these first, then check again with: python3 run_ab.py check " + a.experiment)
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
            registry: set, keep_work: bool) -> dict:
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
        if codex:
            record["usage"] = run.usage
            record["reasoning_effort"] = exp.model.get("reasoning_effort") or "the model's default"
            record["codex_mapping"] = mapping
        (folder / "run.json").write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        entry = {"prompt": p, "round": r, "repeat": k, "status": status, "reason": reason, "output": output,
                 "message": red.text(run.final) if run.final else "", "output_from": output_from,
                 "trace": [[s["tool"], s["detail"], "error"] if s["error"] else [s["tool"], s["detail"]] for s in steps],
                 "model": seen_model, "seconds": run.seconds, "cost_usd": run.cost_usd, "when": started,
                 "runner": runner.name}
        if codex:
            entry["usage"] = run.usage
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
    if errors:
        say("This experiment can't be run yet:")
        for e in errors:
            say("  " + e)
        say(f"Fix these, then check again with: python3 run_ab.py check {a.experiment}")
        return 1
    assistant = Path(a.assistant).expanduser()
    if not assistant.is_dir():
        raise Fail(f"There is no assistant folder at {a.assistant}.\n"
                   f"For the class assistant, set it up first with: python3 run_ab.py setup {a.assistant}")
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
        git_state = {}
        if (assistant / ".git").exists():
            h = git("rev-parse", "--short", "HEAD", cwd=assistant, check=False).stdout.strip()
            dirty = bool(git("status", "--porcelain", cwd=assistant, check=False).stdout.strip())
            git_state = {"commit": h, "uncommitted_changes": dirty}
        if out.bundle is None:
            out.bundle = {"schema": BUNDLE_SCHEMA, "tool": TOOL, "made_up": False, "outputs": [], "judge": [], "files": {}}
        out.bundle.update({
            "experiment": {"name": exp.path.name, "text": exp.text, "sha256": sha256(exp.text)},
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
        if not (exp.data.get("frozen") or {}).get("hash") and not exp.data.get("demo"):
            say("Note: this experiment is not frozen yet. Freeze it in the wizard (step 2), save the exported file, and run that.")
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
            res = one_run(exp, assistant, skip, p, r, k, runner, model, out, registry, a.keep_work)
            e = res["entry"]
            with lock:
                have[(p, r, k)] = e
                out.bundle["outputs"] = sorted(have.values(), key=lambda o: (o["prompt"], o["round"], o["repeat"]))
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
    say(f"The bundle for the wizard: {out.bundle_path}")
    say(f"Next, run the LLM judge:  python3 run_ab.py judge {out.path}")
    say("Then open wizard.html and load the bundle in step 1.")
    return 0


# --- judge ----------------------------------------------------------------

def parse_decision(text: str) -> tuple[str, str]:
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    last = re.sub(r"[^A-Za-z]", "", lines[-1]).upper() if lines else ""
    if last in ("LEFT", "RIGHT", "TIE", "UNKNOWN"):
        return last, ""
    for word in ("UNKNOWN", "TIE", "RIGHT", "LEFT"):
        if lines and re.search(r"\b" + word + r"\b", lines[-1].upper()):
            return word, "read from the last line"
    return "UNKNOWN", "the last line was not LEFT, RIGHT, TIE or UNKNOWN"


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
                   "Run the experiment first: python3 run_ab.py run <experiment file> --assistant <folder>")
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
        for c in exp.data.get("comparisons", []):
            cfg = f"{c['baseline']}|{c['new']}"
            if a.comparisons and cfg.replace("|", "-") not in a.comparisons.split(",") and cfg not in a.comparisons.split(","):
                continue
            for (p, r, k), o in sorted(outputs.items()):
                if r != c["baseline"] or (p, c["new"], k) not in outputs or p in exp.held_out and not a.held_out:
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
                    say(f"[{done[0]}/{len(pairs)}] {cfg.replace('|', ' vs '):8} {p:28} repeat {k}  left was {left}: {decision}"
                        + (f"  ({note})" if note else "") + (f"  {run.seconds:.0f} s" if run.seconds else ""))
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
    say(f"\nThe judge's verdicts are saved in {out.bundle_path} (and one file per pair in {folder / 'judge'}).")
    say("Next: open wizard.html and load the bundle in step 1.")
    return 0


# --- doctor ---------------------------------------------------------------

PROBE_WORD = "heliotrope"


def cmd_doctor(a) -> int:
    ok = True

    def line(good, what, detail=""):
        nonlocal ok
        ok = ok and good is not False
        mark = {True: "ok  ", False: "FIX ", None: "--  "}[good]
        say(f"  {mark} {what}" + (f": {detail}" if detail else ""))

    say(f"Skill Eval Lite {VERSION}")
    line(True, "Python", sys.version.split()[0])
    g = shutil.which("git")
    line(bool(g), "git", git("--version", check=False).stdout.strip() if g else "not found: install git")
    if runner_name(a, None) == "codex":
        ok = doctor_codex(a, line) and ok
        say("\nReady. To see where you are and what to do next:  python3 run_ab.py status" if ok else
            "\nFix the lines marked FIX, then run this again:  python3 run_ab.py doctor --runner codex")
        return 0 if ok else 1
    try:
        exe = find_claude(a.claude)
    except Fail as e:
        line(False, "Claude Code", str(e).splitlines()[0])
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
        line(True, "Login", f"logged in ({method})" + ("; runs are billed to that API key, not to your Claude plan "
                                                       "(type `unset ANTHROPIC_API_KEY` to use your plan)"
                                                       if "key" in str(method).lower() else ""))
    try:
        safe_temp_parent()
        line(True, "Temporary folder", "no CLAUDE.md or AGENTS.md above it")
    except Fail as e:
        line(False, "Temporary folder", str(e))
    if a.no_probe:
        return 0 if ok else 1
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
    say("\nReady. To see where you are and what to do next:  python3 run_ab.py status" if ok else
        "\nFix the lines marked FIX, then run this again:  python3 run_ab.py doctor")
    return 0 if ok else 1


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


def read_trace(folder: Path, red: Redactor | None = None) -> list | None:
    """A process case's steps: from a Claude Code stream (transcript.jsonl,
    as the runner keeps it), with what each step returned; or from
    trace.jsonl, one step a line: {"tool", "detail", "error", "result"}."""
    s = folder / "transcript.jsonl"
    if s.is_file():
        events = [json.loads(l) for l in s.read_text(encoding="utf-8").splitlines() if l.strip()]
        return trace_of(events, red or Redactor(None), results=True)
    t = folder / "trace.jsonl"
    if t.is_file():
        steps = []
        for line in t.read_text(encoding="utf-8").splitlines():
            if line.strip():
                j = json.loads(line)
                st = {"tool": j.get("tool", "?"), "detail": j.get("detail", j.get("input", "")), "error": bool(j.get("error"))}
                if j.get("result") is not None:
                    st["result"] = str(j["result"])[:400]
                steps.append(st)
        return steps
    return None


# The check kinds, as the wizard runs them for Shared I.
def _glob(pattern: str):
    return re.compile("^" + ".*".join(re.escape(p) for p in pattern.split("*")) + "$", re.S)


def _shell_parts(cmd: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n|;|&&|\|\||\|", cmd or "") if p.strip()]


def _allowed_step(st: dict, allowed: list[str]) -> bool:
    if st["tool"] in allowed:
        return True
    if st["tool"] == "Bash":
        return all(any(a.startswith("Bash ") and _glob(a[5:]).match(p) for a in allowed) for p in _shell_parts(st["detail"]))
    return any(" " in a and _glob(a).match(st["tool"] + " " + st["detail"]) for a in allowed)


def run_check(c: dict, text: str | None, trace: list | None) -> tuple[str, str]:
    kind = c.get("kind")
    if kind in ("trace-ran-command", "trace-no-tool-outside"):
        if trace is None:
            return "n/a", "no trace kept"
        if kind == "trace-ran-command":
            tries = [s for s in trace if s["tool"] == "Bash" and any(_glob(c["pattern"]).match(p) for p in _shell_parts(s["detail"]))]
            hit = next((s for s in tries if not s["error"]), None)
            return ("pass", "ran a command matching " + c["pattern"]) if hit else \
                ("fail", "tried it in a step that failed" if tries else "never ran " + c["pattern"])
        out = next((s for s in trace if not _allowed_step(s, c.get("allowed", []))), None)
        return ("fail", "outside the list: " + out["tool"] + " " + out["detail"][:120]) if out else ("pass", "every step on the list")
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
        for s in self.data.get("suites") or []:
            self.suites.append(self._suite(s))
        if not self.suites:
            self.errors.append("There are no suites (a `suites:` list).")

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
            if t.get("kind") == "llm" and not ({"prompt", "skill"} & set(files)):
                self.errors.append(f"Suite {sid}, test {tid}: an LLM test needs `prompt` (a prompt.md) or `skill` (a SKILL.md).")
            version = short_hash(json.dumps(t, sort_keys=True, ensure_ascii=False),
                                 *[files[k].read_text(encoding="utf-8", errors="replace") for k in sorted(files)])
            tests.append({**t, "files": files, "version": version})
        n_items = sum(1 for c in cases if c["role"] == "item")
        roles = [c["role"] for c in cases]
        warns = []
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
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    last = re.sub(r"[^A-Za-z]", "", lines[-1]).upper() if lines else ""
    return {"PASS": "pass", "FAIL": "fail", "UNKNOWN": "unknown"}.get(last, "unknown")


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
        return (r["result"], r["result"]) if r else ("not run", None)

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
                if want == "same":
                    base = by_id.get(c.get("varies"))
                    want = grid[(base["id"], t["id"])][1] if base else None
                    label = "same as " + (c.get("varies") or "?")
                else:
                    label = want
                if want in (None, "any") or got not in ("pass", "fail"):
                    marks.append("-" if want == "any" else f"? ({label}; got {got or 'nothing'})")
                else:
                    marks.append(("ok" if got == want else "MISSED") + f" ({label}, got {got})")
            out.append(f"| {t['id']} | " + " | ".join(marks) + " |")
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
    for w in (w for s in S.suites for w in s["warnings"]):
        say("  note: " + w)
    if S.errors:
        say("The suites file can't be run yet. Fix these, then run the same command again:")
        for e in S.errors:
            say("  " + e)
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
                    cmd = [sys.executable, str(prog)] if prog.suffix == ".py" else [str(prog)]
                    try:
                        p = subprocess.run(cmd + [str(c["folder"])], capture_output=True, text=True, timeout=120, cwd=root)
                        first = (p.stdout.strip().splitlines() or [""])[0]
                        word, _, why = first.partition(" ")
                        result = word.lower() if word.lower() in ("pass", "fail") else "n/a"
                        reason = why.strip() or (p.stderr.strip()[-200:] if result == "n/a" else "")
                        if result == "n/a":
                            reason = f"the program printed {first!r}, not pass or fail" + (": " + reason if reason else "")
                    except (OSError, subprocess.TimeoutExpired) as e:
                        result, reason = "n/a", f"the program did not run: {e}"
                    judge = prog.name
                else:
                    result, reason = run_check(t["check"], content["output"], content["trace"])
                    judge = TOOL + " (" + t["check"]["kind"] + ")"
                new_rows.append({"item": c["id"], "object": s["object"], "check": t["id"], "route": "mechanical", "judge": judge,
                                 "version": t["version"], "result": result, "reason": reason, "when": when})
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
                text = (f"Use the {name} skill to judge the case below. End your answer with one line: PASS, FAIL or UNKNOWN.\n\n"
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
            decision = parse_verdict(response) if ok else "unknown"
            model = run.model_seen or model or ""
            rec = {"suite": s["id"], "test": t["id"], "version": t["version"], "case": c["id"], "when": started, "model": model,
                   **runner.record(), "command": run.command, "decision_rule": t.get("decision", "The last line is PASS, FAIL or UNKNOWN."),
                   "decision": decision, "status": "ok" if ok else ("timeout" if run.timed_out else "failed"), "seconds": run.seconds,
                   "cost_usd": run.cost_usd, "input": red.text(text), "response": response,
                   "isolation": run.isolation, "tool": TOOL}
            if run.usage:
                rec["usage"] = run.usage
            d = root / "tests" / t["id"] / "runs"
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{c['id']}__{started.replace(':', '')}.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            reason = " ".join(response.splitlines()[:-1]).strip()[:300] if response else (rec["status"])
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
                          "trace": [[x["tool"], x["detail"], "error" if x["error"] else "", x.get("result", "")] for x in content["trace"]]
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
    say(f"Next: open wizard.html and load {root / 'bundle.json'} for the human tests and your reference judgments.")
    return 0


# --- status and ask ---------------------------------------------------------
#
# `status` says where a student is: the setup, the assistant, the
# experiments, the runs and the suites, and the one next step with its exact
# command. `ask` opens Claude Code or Codex in this folder as a helper
# (HELPER.md), given that status; with a question, it answers once.

PY = "py" if os.name == "nt" else "python3"
OPEN_WIZARD = {"nt": "start wizard.html"}.get(os.name, "open wizard.html" if sys.platform == "darwin" else "xdg-open wizard.html")


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
            "pairs": len(pairs), "judged": len(pairs & judged), "updated": b.get("updated")}


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
    root = Path(getattr(a, "root", None) or HERE)
    found = []
    for base in dict.fromkeys([root / "experiments", Path.cwd() / "experiments"]):
        for f in sorted(base.glob("*/experiment.toml")) + sorted(base.glob("*.toml")):
            found.append(("yours", f))
    found += [("demonstration", f) for f in sorted((HERE / "examples").glob("demo-*.toml"))]
    found += [("class example", HERE / "examples" / "class-assistant" / "experiment.toml")]
    exps, seen = [], set()
    for kind, f in found:
        if not f.is_file() or f.resolve() in seen:
            continue
        seen.add(f.resolve())
        try:
            e = Experiment(f)
            errors, warns = e.problems()
            exps.append({"file": shown_path(f), "kind": kind, "name": e.name, "title": e.data.get("title", ""),
                         "errors": errors, "notes": len(warns), "frozen": bool((e.data.get("frozen") or {}).get("hash")),
                         "demo": bool(e.data.get("demo")), "runner": e.model.get("runner", "claude-code")})
        except Fail as err:
            exps.append({"file": shown_path(f), "kind": kind, "name": f.stem, "errors": [str(err).splitlines()[0]],
                         "notes": 0, "frozen": False, "demo": False})
    st["experiments"] = exps
    # Runs.
    runs, seen = [], set()
    for base in dict.fromkeys([root / "runs", Path.cwd() / "runs"]):
        for b in sorted(base.glob("*/bundle.json")):
            if b.resolve() in seen:
                continue
            seen.add(b.resolve())
            r = run_folder_state(b)
            if r:
                runs.append(r)
    st["runs"] = runs
    # Personal I packets beside Skill Eval Lite.
    suites = []
    for f in sorted(root.parent.glob("*/suites.yaml")) + sorted(root.parent.glob("*/suites.json")):
        if f.parent.resolve() in (HERE.resolve(), root.resolve()):
            continue
        rows = len(read_rows(f.parent / "judgments.csv"))
        suites.append({"file": shown_path(f), "has_run": (f.parent / "bundle.json").is_file(), "rows": rows})
    st["suites"] = suites
    st["next"] = next_step(st)
    return st


def next_step(st: dict) -> dict:
    """The one next step, in plain words, with its exact command."""
    s, asst = st["setup"], st["assistant"]
    rn = s["runner"]
    rflag = " --runner codex" if rn == "codex" else ""
    if not s["python_ok"]:
        return {"what": "Install Python 3.11 or later (https://www.python.org/downloads/), then run this again.",
                "command": f"{PY} run_ab.py status"}
    if not s["git"]:
        return {"what": "Install git (https://git-scm.com/downloads), then run this again.", "command": f"{PY} run_ab.py status"}
    if rn is None:
        return {"what": "Install Claude Code, or Codex if your paid plan is ChatGPT's. You need only one. "
                        "The README's \"What you need\" shows how; then run this again.",
                "command": "curl -fsSL https://claude.ai/install.sh | bash"}
    tool = s["claude_code" if rn == "claude-code" else "codex"]
    if not tool.get("installed"):
        return {"what": f"Install {RUNNER_LABEL[rn]} (the README's \"What you need\" shows how), then run this again.",
                "command": f"{PY} run_ab.py status"}
    if tool.get("logged_in") is False:
        if rn == "codex":
            return {"what": "Log in to Codex: this opens your browser; sign in with the ChatGPT account that has your plan.",
                    "command": "codex login"}
        return {"what": "Log in to Claude Code: type the command, log in when it asks, then type /exit.", "command": "claude"}
    if not asst["exists"]:
        return {"what": "Set up the class assistant, Wren, in a folder beside this one (about a minute; it needs the internet).",
                "command": f"{PY} run_ab.py setup ../class-assistant"}
    if not asst["claude_md"]:
        return {"what": f"{asst['folder']} has no CLAUDE.md, so it doesn't look like an assistant's folder. "
                        "Check the folder, or set up the class assistant in a new one.",
                "command": f"{PY} run_ab.py setup ../class-assistant"}
    a_flag = "" if asst["folder"] == "../class-assistant" else f" (your assistant is in {asst['folder']})"
    mine = [e for e in st["experiments"] if e["kind"] == "yours"]
    runs = {r["experiment"]: r for r in st["runs"]}
    for e in mine:
        if e["errors"]:
            return {"what": f"Your experiment {e['file']} has {len(e['errors'])} thing(s) to fix. Check it to see them.",
                    "command": f"{PY} run_ab.py check {e['file']}"}
        if not e["frozen"]:
            return {"what": f"Your experiment {e['file']} is ready to freeze. " + "Freeze it in the wizard: load it in step 1, press Freeze in step 2, then press 'Export the frozen experiment' "
                            f"(now in step 2) and save the file over {e['file']}.",
                    "command": OPEN_WIZARD}
        r = next((r for n, r in runs.items() if n and Path(n).stem in (e["name"], "experiment") and e["name"] in r["folder"]), None)
        if not r:
            return {"what": f"Run rounds A and B of your experiment{a_flag} (the controls C and D come next).",
                    "command": f"{PY} run_ab.py run {e['file']} --assistant {asst['folder']} --rounds A,B --jobs 4{rflag}"}
        if r["judged"] < r["pairs"]:
            return {"what": f"Run the LLM judge on {r['folder']}: it reads each blind pair and says which is better.",
                    "command": f"{PY} run_ab.py judge {r['folder']}"}
    if mine:
        return {"what": f"Open the wizard and load {st['runs'][-1]['folder'] if st['runs'] else 'your run folder'}/bundle.json "
                        "in step 1: judge the blind pairs (step 4) and read the results (step 5).", "command": OPEN_WIZARD}
    if not st["runs"]:
        return {"what": "Try the first demonstration: six runs of the class assistant, with and without one line added "
                        "to its voice file (about half a minute; each run uses your plan).",
                "command": f"{PY} run_ab.py run examples/demo-one-line.toml --assistant {asst['folder']} --jobs 6{rflag}"}
    for r in st["runs"]:
        if r["ok"] == 0 and r["runs"]:
            return {"what": f"Every run in {r['folder']} failed. Run the setup check to see why.",
                    "command": f"{PY} run_ab.py doctor{rflag}"}
        if r["judged"] < r["pairs"]:
            return {"what": f"Run the LLM judge on {r['folder']}: it reads each blind pair and says which is better (about a minute).",
                    "command": f"{PY} run_ab.py judge {r['folder']}"}
    intake = "/experiment-intake (typed inside Claude Code, started here with `claude`)" \
        if rn == "claude-code" else "Codex (start `codex` here and ask it to follow AGENTS.md)"
    return {"what": f"Open the wizard, load {st['runs'][0]['folder']}/bundle.json in step 1, and look at the results. Then "
                    f"make your group's experiment: to adapt the class experiment, `{PY} run_ab.py new <name> --from class`; "
                    f"for your own assistant, the intake: {intake}.", "command": OPEN_WIZARD}


def status_text(st: dict) -> str:
    s, asst = st["setup"], st["assistant"]
    L = [f"Skill Eval Lite {VERSION}: where you are now", "", "Your setup"]

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
            L.append(f"  ok   {label} {t.get('version')}: logged in" + (f" ({t['login']})" if t.get("login") else ""))
    if s["runner"]:
        other = "codex" if s["runner"] == "claude-code" else "claude-code"
        L.append(f"  You need only one of the two. This status uses {RUNNER_LABEL[s['runner']]}"
                 + (f"; add --runner {other} for {RUNNER_LABEL[other]}." if s[other.replace('-', '_')].get("installed") else "."))
    L += ["", "The assistant"]
    if not asst["exists"]:
        L.append(f"  --   {asst['folder']}: not set up yet")
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
        else:
            state = "frozen, ready to run" if e["frozen"] else "ready to freeze in the wizard"
        L.append(f"  {e['file']:44} {e['kind']}: {state}")
    if not any(e["kind"] == "yours" for e in st["experiments"]):
        L.append("  (none of your own yet: they go in experiments/<name>/)")
    L += ["", "Runs"]
    for r in st["runs"]:
        fails = r["failed"] + r["timed_out"]
        L.append(f"  {r['folder']:36} {RUNNER_LABEL.get(r['runner'], r['runner'] or '?'):12} {r['ok']} of {r['runs']} finished"
                 + (f" ({fails} failed)" if fails else "") + f"; judge: {r['judged']} of {r['pairs']} pairs")
    if not st["runs"]:
        L.append("  none yet")
    if st["suites"]:
        L += ["", "Personal I packets"]
        for x in st["suites"]:
            L.append(f"  {x['file']:44} " + (f"run, {x['rows']} rows in judgments.csv" if x["has_run"] else "not run yet"))
    n = st["next"]
    L += ["", "Next step", "  " + n["what"]]
    if n.get("command"):
        L += ["", "      " + n["command"]]
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
                   "for example: python3 run_ab.py new board-memo --from class")
    dest = Path(getattr(a, "root", None) or HERE) / "experiments" / name
    if not a.source:
        say(f"To write a new experiment for your group's own assistant, use the intake. It asks your group a few\n"
            f"questions and writes {shown_path(dest)}/experiment.toml for you:\n\n"
            "    claude                                 then type:  /experiment-intake <your assistant's folder>\n"
            "    codex                                  then ask it to follow AGENTS.md (Codex users)\n\n"
            "To start from the class experiment instead (the class assistant, Wren), copy it:\n\n"
            f"    {PY} run_ab.py new {name} --from class")
        return 0
    src = HERE / "examples" / "class-assistant" / "experiment.toml" if a.source == "class" else Path(a.source).expanduser()
    if src.is_dir():
        src = src / "experiment.toml"
    if not src.is_file():
        raise Fail(f"There is no experiment file at {a.source}. Use --from class for the class experiment, "
                   "or give the path of an experiment.toml.")
    if dest.exists() and any(dest.iterdir()):
        raise Fail(f"{shown_path(dest)} already exists and is not empty, so nothing was copied.\n"
                   f"Choose another name, or work on that one:  {PY} run_ab.py check {shown_path(dest)}/experiment.toml")
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
    (dest / "experiment.toml").write_text(text, encoding="utf-8")
    errors, _ = Experiment(dest / "experiment.toml").problems()
    what = "the class experiment" if a.source == "class" else shown_path(src)
    say(f"Made {shown_path(dest)}/ from {what}: experiment.toml" + (", " + ", ".join(copied) if copied else "") + ".")
    if errors:
        say("The copy has things to fix (its files may not all have come along):")
        for e in errors:
            say("  must fix:  " + e)
    say(f"\nNext, read {shown_path(dest)}/experiment.toml and change what your group wants to test (or ask for help:\n"
        f"{PY} run_ab.py ask). Then check it:\n\n    {PY} run_ab.py check {shown_path(dest)}/experiment.toml")
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
                   "Install one of them (the README's \"What you need\" shows how), then try again.")
    tool = st["setup"]["claude_code" if name == "claude-code" else "codex"]
    if not tool.get("installed"):
        raise Fail(f"{RUNNER_LABEL[name]} is not installed. Install it, or ask the other one: "
                   f"python3 run_ab.py ask --runner {'codex' if name == 'claude-code' else 'claude-code'}")
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


def main(argv=None) -> int:
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

    s = sub.add_parser("status", help="where you are: the setup, the assistant, experiments, runs, and the next step")
    s.add_argument("--assistant", help="the assistant's folder (default: ../class-assistant)")
    s.add_argument("--runner", choices=RUNNERS, help="claude-code or codex (default: the one you are logged in to)")
    s.add_argument("--claude", help=argparse.SUPPRESS)
    s.add_argument("--codex", help=argparse.SUPPRESS)
    s.add_argument("--json", action="store_true", help="print the same as JSON")
    s.add_argument("--root", help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("ask", help="get help from Claude Code or Codex, step by step; or ask one question")
    s.add_argument("question", nargs="*", help='a question to answer once, e.g. "how do I freeze my experiment?"')
    s.add_argument("--assistant", help="the assistant's folder (default: ../class-assistant)")
    add_runner_args(s)
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
    s.add_argument("--held-out", action="store_true", help="include held-out prompts")
    s.add_argument("--budget", type=float, default=0.50, help="Claude Code only: the most one judgment may cost, in dollars (default 0.50)")
    s.add_argument("--timeout", type=int, default=180, help="seconds before a judgment counts as timed out (default 180)")
    add_runner_args(s, "the judge's model (default: the experiment's [judge] model)")
    s.set_defaults(fn=cmd_judge)

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

    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except Fail as e:
        say(str(e), err=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())

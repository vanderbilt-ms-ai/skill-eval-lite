#!/usr/bin/env python3
"""Small helpers for Personal I's cases, for the suites-intake, control-cases
and llm-test skills (Skill Eval Lite 0.2.0). Run from Skill Eval Lite's
folder, with the runner's Python; it reads run_ab.py from there and changes
nothing except where `copy` is told to write.

    python3 .claude/skills/suites-intake/case.py sessions [FOLDER]
        Claude Code's saved sessions for the project FOLDER (default: list
        every project with sessions): date, size, steps and the first words
        of the first request. Claude Code keeps them in ~/.claude/projects/.
    python3 .claude/skills/suites-intake/case.py copy SESSION.jsonl CASE_FOLDER
        Copy a saved session into CASE_FOLDER/transcript.jsonl, keeping only
        its `user` and `assistant` lines (the record the runner reads). The
        rest is the app's own bookkeeping, which can hold settings and
        instructions. Refuses to overwrite.
    python3 .claude/skills/suites-intake/case.py steps CASE_FOLDER
        The case's steps as trace.jsonl lines (tool, detail, error, result),
        read as run_ab.py reads them: to make a control case's record.
    python3 .claude/skills/suites-intake/case.py text SUITES_FILE SUITE CASE
        The case as an LLM test reads it (its files, then its steps).
    python3 .claude/skills/suites-intake/case.py private FOLDER
        Lines in FOLDER's files that may be private: the home folder's path,
        e-mail addresses, things that look like keys or tokens. Each match is
        shown masked, with its file and line, for the student to read.

Written for Skill Eval Lite 0.2.0, 2026-11-07.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(HERE))
import run_ab as R  # noqa: E402

PROJECTS = Path.home() / ".claude" / "projects"


def project_dir(folder: str) -> Path:
    """Claude Code's folder for a project: its path with every character
    that isn't a letter or a digit written as '-'."""
    return PROJECTS / re.sub(r"[^A-Za-z0-9]", "-", str(Path(folder).expanduser().resolve()))


def first_request(path: Path) -> str:
    for line in path.read_text(encoding="utf-8", errors="replace").split("\n"):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict) or e.get("type") != "user" or e.get("isMeta"):
            continue
        c = (e.get("message") or {}).get("content")
        text = c if isinstance(c, str) else " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text") \
            if isinstance(c, list) else ""
        text = " ".join(text.split())
        if text and not text.startswith("<"):
            return text[:70] + ("..." if len(text) > 70 else "")
    return "(no request found)"


def cmd_sessions(args):
    if not PROJECTS.is_dir():
        print(f"No saved sessions: there is no {PROJECTS}.")
        return 1
    if not args:
        rows = []
        for d in sorted(p for p in PROJECTS.iterdir() if p.is_dir()):
            files = list(d.glob("*.jsonl"))
            if files:
                rows.append((max(f.stat().st_mtime for f in files), d.name, len(files)))
        for t, name, n in sorted(rows, reverse=True):
            print(f"{dt.datetime.fromtimestamp(t):%Y-%m-%d}  {n:4} sessions  {name}")
        print("\nName a project's folder to list its sessions: case.py sessions ../my-system")
        return 0
    d = project_dir(args[0])
    if not d.is_dir():
        print(f"No saved sessions for {args[0]} (looked in {d}). Run case.py sessions alone to list every project.")
        return 1
    for f in sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime):
        try:
            n = len(R.trace_of(R.record_lines(f), R.Redactor(None)))
        except Exception:  # a file that isn't a session: say so, then go on
            n = -1
        when = dt.datetime.fromtimestamp(f.stat().st_mtime)
        steps = f"{n:4} steps" if n >= 0 else "  unreadable"
        print(f"{when:%Y-%m-%d %H:%M}  {f.stat().st_size // 1024:6} KB  {steps}  {f.name}\n    {first_request(f)}")
    return 0


def cmd_copy(args):
    src, dst = Path(args[0]).expanduser(), Path(args[1])
    out = dst / "transcript.jsonl"
    if out.exists():
        print(f"{out} is there already. Nothing copied.")
        return 1
    kept = []
    for line in src.read_text(encoding="utf-8", errors="replace").split("\n"):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and e.get("type") in ("user", "assistant"):
            kept.append(line)
    dst.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(kept) + "\n", encoding="utf-8")
    steps = R.read_trace(dst)
    print(f"Wrote {out}: {len(kept)} lines, {len(steps or [])} steps.")
    return 0


def cmd_steps(args):
    steps = R.read_trace(Path(args[0]))
    if steps is None:
        print(f"{args[0]} has no transcript.jsonl or trace.jsonl.", file=sys.stderr)
        return 1
    for st in steps:
        print(json.dumps({k: st[k] for k in ("tool", "detail", "error", "result", "refused") if k in st}, ensure_ascii=False))
    return 0


def cmd_text(args):
    S = R.Suites(Path(args[0]))
    suite = next((s for s in S.suites if s["id"] == args[1]), None)
    case = next((c for c in (suite or {}).get("cases", []) if c["id"] == args[2]), None)
    if not case:
        print(f"No case {args[2]} in suite {args[1]}.", file=sys.stderr)
        return 1
    print(R.render_case(suite, S.case_content(suite, case)))
    return 0


KEY = re.compile(r"\b(sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[abp]-[A-Za-z0-9-]{10,})")
MAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def mask(s: str) -> str:
    return s[:3] + "*" * max(3, len(s) - 5) + s[-2:] if len(s) > 6 else "*" * len(s)


def cmd_private(args):
    home = str(Path.home())
    found = 0
    for f in sorted(p for p in Path(args[0]).rglob("*") if p.is_file() and p.stat().st_size < 20_000_000):
        try:
            lines = f.read_text(encoding="utf-8").split("\n")
        except (UnicodeDecodeError, OSError):
            continue
        for k, line in enumerate(lines, 1):
            hits = [("a key or token", m.group(0)) for m in KEY.finditer(line)]
            hits += [("an e-mail address", m.group(0)) for m in MAIL.finditer(line) if not m.group(0).endswith(".example")]
            if home in line:
                hits.append(("your home folder's path", home))
            for what, s in dict.fromkeys(hits):
                print(f"{f}:{k}: {what}: {mask(s)}")
                found += 1
    print(f"\n{found} things to look at." if found else "Nothing found. Please read the files anyway: a name or a detail can be private too.")
    return 0


def main():
    cmds = {"sessions": (cmd_sessions, 0), "copy": (cmd_copy, 2), "steps": (cmd_steps, 1), "text": (cmd_text, 3), "private": (cmd_private, 1)}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds or len(sys.argv) - 2 < cmds[sys.argv[1]][1]:
        print(__doc__.split("Written for")[0].strip())
        return 2
    return cmds[sys.argv[1]][0](sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""search-before-write: did the run look something up in the knowledge graph
before it wrote a file?

    python3 check.py CASE_FOLDER

Reads CASE_FOLDER/trace.jsonl (one step a line: {"tool", "detail", "error"}),
or CASE_FOLDER/transcript.jsonl (Claude Code's stream-json events). Prints one
line: "pass <reason>" or "fail <reason>". A lookup is a shell command
`kb/kb search`, `kb/kb node` or `kb/kb query` (alone or in a chain of
commands), or the knowledge-graph skill, in a step that didn't fail. A write
is a Write or Edit step, or a shell step that redirects into a file.

What a pass does not show: that the lookup found anything, or that the brief
used it. A chained command such as `kb/kb search Dana | head` counts as a step
that didn't fail even when kb/kb is missing, because the chain's last command
succeeded.
"""
import json
import re
import sys
from pathlib import Path


def steps(folder: Path):
    t = folder / "trace.jsonl"
    if t.is_file():
        return [json.loads(l) for l in t.read_text().splitlines() if l.strip()]
    s = folder / "transcript.jsonl"
    out, by_id = [], {}
    for line in s.read_text().splitlines() if s.is_file() else []:
        e = json.loads(line)
        content = (e.get("message") or {}).get("content") if isinstance(e.get("message"), dict) else None
        for c in content if isinstance(content, list) else []:
            if c.get("type") == "tool_use":
                inp = c.get("input") or {}
                st = {"tool": c.get("name"), "detail": inp.get("command") or inp.get("file_path") or inp.get("skill") or "", "error": False}
                by_id[c.get("id")] = st
                out.append(st)
            elif c.get("type") == "tool_result" and c.get("tool_use_id") in by_id:
                by_id[c["tool_use_id"]]["error"] = bool(c.get("is_error"))
    return out


def is_lookup(st):
    if st.get("error"):
        return False
    if st["tool"] == "Skill":
        return "knowledge-graph" in st["detail"]
    if st["tool"] == "Bash":
        return any(re.match(r"(\./)?kb/kb (search|node|query)\b", p.strip()) for p in re.split(r"\n|;|&&|\|\||\|", st["detail"]))
    return False


def is_write(st):
    # A shell redirection into a file (> or >>), not 2> or >&2 or > /dev/null.
    redirect = r"(?<![0-9>&])>>?\s*(?!&|/dev/null)[\w./~-]"
    return st["tool"] in ("Write", "Edit") or (st["tool"] == "Bash" and re.search(redirect, st["detail"].split("\n")[0]) is not None)


def main():
    folder = Path(sys.argv[1])
    trace = steps(folder)
    if not trace:
        print("fail no trace in the case folder")
        return
    first_write = next((k for k, st in enumerate(trace) if is_write(st) and not st.get("error")), len(trace))
    lookup = next((k for k, st in enumerate(trace[:first_write]) if is_lookup(st)), None)
    if lookup is None:
        print("fail no lookup before the first write" + (f" (step {first_write + 1})" if first_write < len(trace) else ""))
    else:
        print(f"pass step {lookup + 1} looked up ({trace[lookup]['detail'][:60]}) before the first write")


main()

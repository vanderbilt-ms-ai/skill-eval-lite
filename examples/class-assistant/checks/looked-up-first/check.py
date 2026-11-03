#!/usr/bin/env python3
"""looked-up-first: did the run look something up in the knowledge graph
before it wrote anything?

    python3 check.py CASE_FOLDER

A program check for Skill Eval Lite (CHECKS.md says how to write one). It
reads CASE_FOLDER/trace.jsonl, one step of the run a line: {"tool",
"detail", "error"}. It prints one line: "pass <reason>" or "fail <reason>",
or "n/a <reason>" when there is no trace, so there is nothing to check.

A lookup is a shell command `kb/kb search`, `kb/kb node` or `kb/kb query`
(alone or in a chain of commands), or the knowledge-graph skill, in a step
that didn't fail. A write is a Write or Edit step, or a shell step that
redirects into a file.

Why a program: the built-in check trace-ran-command sees that a search ran,
but not when. This one sees the order: whether the lookup came before the
draft.

What a pass does not show: that the lookup found anything, or that the draft
used it. A chained command such as `kb/kb search Dana | head` counts as a
step that didn't fail even when kb/kb is missing, because the chain's last
command succeeded.

Adapted from examples/personal-suites/tests/search-before-write/check.py.
Standard library only. Made for AI 5500 (Vanderbilt, Fall 2026).
"""
import json
import re
import sys
from pathlib import Path

LOOKUP = re.compile(r"(\./)?kb/kb (search|node|query)\b")
# A redirection into a file (> or >>), not 2> or >&2 or > /dev/null.
REDIRECT = re.compile(r"(?<![0-9>&])>>?\s*(?!&|/dev/null)[\w./~-]")


def is_lookup(st):
    if st.get("error"):
        return False
    if st.get("tool") == "Skill":
        return "knowledge-graph" in st.get("detail", "")
    if st.get("tool") == "Bash":
        return any(LOOKUP.match(p.strip()) for p in re.split(r"\n|;|&&|\|\||\|", st.get("detail", "")))
    return False


def is_write(st):
    if st.get("error"):
        return False
    tool, detail = st.get("tool"), st.get("detail", "")
    return tool in ("Write", "Edit") or (tool == "Bash" and REDIRECT.search(detail.split("\n")[0]) is not None)


def main():
    trace = Path(sys.argv[1]) / "trace.jsonl"
    if not trace.is_file():
        print("n/a no trace.jsonl: this case has no record of its steps")
        return
    steps = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines() if line.strip()]
    first_write = next((k for k, st in enumerate(steps) if is_write(st)), len(steps))
    lookup = next((k for k, st in enumerate(steps[:first_write]) if is_lookup(st)), None)
    if lookup is None:
        where = f" (step {first_write + 1})" if first_write < len(steps) else ""
        print("fail no lookup in the knowledge graph before the first write" + where)
    else:
        print(f"pass step {lookup + 1} looked something up ({steps[lookup]['detail'][:60]}) before the first write")


main()

#!/usr/bin/env python3
"""no-made-up-amounts: is every amount of money in the output one that the
knowledge graph holds?

    python3 check.py CASE_FOLDER

A program check for Skill Eval Lite (CHECKS.md says how to write one). It
reads CASE_FOLDER/output.md, and the amounts the graph holds from
CASE_FOLDER/context.json ("params": {"amounts": [...]}, which the experiment
file sets). An amount is a number with a thousands comma (120,000), a dollar
sign ($120) or a k (120k). It prints one line: "pass <reason>" when every
amount in the output is one of them, or there is none; "fail <reason>",
naming the first that isn't; or "n/a <reason>" when there is no output.

Why a program: the built-in checks can look for one amount (matches) or rule
out a list of them (not-contains). They can't say "only these".

What a pass does not show: that the output gives the amounts it should, or
puts each one in the right place.

Standard library only. Made for AI 5500 (Vanderbilt, Fall 2026).
"""
import json
import re
import sys
from pathlib import Path

AMOUNT = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?\s?[kK]?\b|\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d+(?:\.\d+)?\s?[kK]\b")


def value(text):
    t = text.replace("$", "").replace(",", "").replace(" ", "")
    if t.endswith(("k", "K")):
        return float(t[:-1]) * 1000
    return float(t)


def main():
    case = Path(sys.argv[1])
    output = case / "output.md"
    if not output.is_file():
        print("n/a no output.md: this case has no output to read")
        return
    params = json.loads((case / "context.json").read_text(encoding="utf-8")).get("params", {})
    known = params.get("amounts", [])
    found = [a.strip() for a in AMOUNT.findall(output.read_text(encoding="utf-8"))]
    for a in found:
        if value(a) not in {value(k) for k in known}:
            print(f"fail {a} is not an amount the graph holds (it holds {', '.join(known)})")
            return
    print(f"pass {len(found)} amount{'s' if len(found) != 1 else ''}, each one the graph holds" if found
          else "pass no amounts of money in the output")


main()

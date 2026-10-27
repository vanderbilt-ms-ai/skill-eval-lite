#!/usr/bin/env python3
"""Puts the real material that starting.html quotes into it.

starting.html is the guided tour for new students. Everything it shows from
the class assistant's runs is copied, word for word, from the recorded runs
in examples/recorded/ (real Claude Code runs of a fictional assistant, made
on 2026-10-26), from the class experiment (examples/class-assistant/), from
the knowledge-graph pages in class-assistant/overlay/, and from the short
excerpts of the assistant template's files in tutorial/excerpts.json. This
script gathers them, runs the experiment's checks on the recorded outputs
the same way the wizard does, and writes the result into the JSON block in
starting.html between the markers.

    python3 tutorial/build.py            # rewrite the block in starting.html
    python3 tutorial/build.py --check    # exit 1 if the block is out of date
    python3 tutorial/build.py --assistant ../class-assistant
                                         # also check every excerpt is still in its file
    python3 tutorial/build.py --diagrams docs/diagrams
                                         # also copy the shared diagrams in (see DIAGRAMS)

Reads only files in this repository (and the folders named by --assistant
and --diagrams). Writes only starting.html. Standard library only (Python 3.11+).
Written by Claude (claude-opus-5-5) for AI 5500, 2026-10-26.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PAGE = REPO / "starting.html"
EX = REPO / "examples"
REC = EX / "recorded"
WIKI = REPO / "class-assistant" / "overlay" / "files" / "kb" / "wiki"
BEGIN = '<script type="application/json" id="tour-data">'
END = "</script>"

# The recorded demonstrations, by the short name the page uses.
DEMOS = {"graph": "demo-graph-removed", "voice": "demo-voice-reordered", "board": "demo-board-memo"}


# The wizard's mechanical checks (wizard.html, "The mechanical checks"),
# reimplemented so that the page shows the results the wizard would.
def _glob(pattern: str) -> re.Pattern:
    return re.compile("^" + ".*".join(re.escape(s) for s in pattern.split("*")) + "$", re.S)


def _parts(cmd: str) -> list[str]:
    return [x.strip() for x in re.split(r"\n|;|&&|\|\||\|", cmd or "") if x.strip()]


def _allowed(step: list, allowed: list[str]) -> bool:
    if step[0] in allowed:
        return True
    if step[0] == "Bash":
        return all(any(a.startswith("Bash ") and _glob(a[5:]).match(p) for a in allowed) for p in _parts(step[1]))
    text = step[0] + (" " + step[1] if len(step) > 1 and step[1] else "")
    return any(" " in a and _glob(a).match(text) for a in allowed)


def run_check(c: dict, prompt: dict, o: dict) -> dict | None:
    if "prompts" in c and prompt["id"] not in c["prompts"]:
        return None
    if "tags" in c and not set(prompt.get("tags", [])) & set(c["tags"]):
        return None
    if o["status"] != "ok":
        return {"result": "fail", "reason": "the run " + ("timed out" if o["status"] == "timeout" else "failed")}
    out, trace, k = o["output"], o.get("trace") or [], c["kind"]
    if k == "contains":
        miss = [t for t in c["text"] if t not in out]
        ok, why = not miss, ("missing: " + ", ".join(miss)) if miss else "all present"
    elif k == "not-contains":
        found = [t for t in c["text"] if t in out]
        ok, why = not found, ("found: " + ", ".join(found)) if found else "none found"
    elif k == "matches":
        ok = re.search(c["pattern"], out) is not None
        why = "matches" if ok else "no match"
    elif k == "word-count":
        w = len(out.split())
        ok = (c.get("min") is None or w >= c["min"]) and (c.get("max") is None or w <= c["max"])
        why = f"{w} words" + ("" if ok else f", over {c['max']}")
    elif k == "trace-ran-command":
        g = _glob(c["pattern"])
        tries = [st for st in trace if st[0] == "Bash" and any(g.match(p) for p in _parts(st[1]))]
        hit = next((st for st in tries if not (len(st) > 2 and st[2] == "error")), None)
        cmd = lambda st: next(p for p in _parts(st[1]) if g.match(p))
        ok = hit is not None
        why = ("ran " + cmd(hit)) if hit else (("tried " + cmd(tries[0]) + ", in a step that failed") if tries else "never ran " + c["pattern"])
    elif k == "trace-no-tool-outside":
        bad = next((st for st in trace if not _allowed(st, c["allowed"])), None)
        ok, why = bad is None, ("outside the list: " + bad[0] + " " + (bad[1] or "")[:80]) if bad else "every step on the list"
    else:
        return None
    return {"result": "pass" if ok else "fail", "reason": why}


def short(detail: str, n: int = 160) -> str:
    # A step that writes a whole draft with a heredoc is shown by its first line.
    first = (detail or "").split("\n", 1)[0]
    return first if first == detail and len(first) <= n else first[:n].rstrip() + " ..."


def trace_steps(o: dict) -> list[list]:
    # The bundle keeps each step as [tool, detail] or [tool, detail, "error"].
    return [[s[0], short(s[1] if len(s) > 1 else ""), bool(len(s) > 2 and s[2] == "error")] for s in o["trace"]]


def tool_results(transcript: Path) -> list[str]:
    """The text each tool returned, in order, from a run's transcript."""
    out = []
    for line in transcript.read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if e.get("type") != "user":
            continue
        content = e.get("message", {}).get("content")
        if not isinstance(content, list):
            continue
        for x in content:
            if x.get("type") == "tool_result":
                c = x.get("content")
                if isinstance(c, list):
                    c = "\n".join(p.get("text", "") for p in c if isinstance(p, dict))
                out.append(str(c))
    return out


def page_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        text = text.split("---", 2)[2]
    return text.strip()


def section(md: str, heading: str) -> str:
    m = re.search(r"^## " + re.escape(heading) + r"\n(.*?)(?=^## |\Z)", md, re.S | re.M)
    return m.group(1).strip() if m else ""


def demo(name: str) -> dict:
    folder = REC / name
    b = json.loads((folder / "bundle.json").read_text(encoding="utf-8"))
    x = tomllib.loads(b["experiment"]["text"])
    prompts = {p["id"]: p for p in x["prompt"]}
    outputs = []
    for o in b["outputs"]:
        checks = {}
        for c in x.get("checks", []):
            r = run_check(c, prompts[o["prompt"]], o)
            if r:
                checks[c["id"]] = r
        outputs.append({
            "prompt": o["prompt"], "round": o["round"], "repeat": o["repeat"], "status": o["status"],
            "output": o["output"], "message": o["message"], "output_from": o["output_from"],
            "trace": trace_steps(o), "model": o["model"], "seconds": o["seconds"], "when": o["when"],
            "checks": checks,
        })
    judge = [{k: j[k] for k in ("comparison", "prompt", "repeat", "shown_left", "decision", "winner", "response", "model", "when")}
             for j in b["judge"]]
    return {
        "folder": "examples/recorded/" + name,
        "experiment": name + ".toml",
        "sha256": b["experiment"]["sha256"],
        "claude_code": b["runner"]["claude_code_version"],
        "rounds": [{k: r.get(k) for k in ("id", "label", "role", "expected", "why")} for r in x["rounds"]],
        "prompts": {p["id"]: {k: p.get(k) for k in ("title", "tags", "text")} for p in x["prompt"] if p["id"] in x["prompts"]["development"]},
        "checks": [{k: c.get(k) for k in ("id", "kind", "object", "shows", "does_not_show", "pattern")} for c in x.get("checks", [])],
        "outputs": outputs,
        "judge": judge,
    }


def gather() -> dict:
    exp_path = EX / "class-assistant" / "experiment.toml"
    x = tomllib.loads(exp_path.read_text(encoding="utf-8"))
    files_root = EX / "class-assistant" / "prompts"
    prompts, reference_checks = [], {}
    for p in x["prompt"]:
        ref = {"status": "ok", "output": p["reference"].strip(), "trace": None}
        reference_checks[p["id"]] = {c["id"]: r for c in x["checks"] if c["object"] == "product" and (r := run_check(c, p, ref))}
        files = {f: (files_root / p["id"] / "files" / f).read_text(encoding="utf-8") for f in p.get("files", [])}
        prompts.append({k: p.get(k) for k in ("id", "title", "tags", "should", "should_not", "text", "reference")} | {"files": files})
    voice_b = (EX / "class-assistant" / "rounds" / "B" / ".claude" / "identity" / "voice.md").read_text(encoding="utf-8")
    voice_d = (EX / "class-assistant" / "rounds" / "D" / ".claude" / "identity" / "voice.md").read_text(encoding="utf-8")
    people = {}
    for name in ("Morgan Reyes", "Dana Whitfield", "Priya Raman", "Ellis Park", "Sam Reyes", "Cedar Commons",
                 "Riverside Youth Collective", "Hale Foundation"):
        people[name] = section(page_text(WIKI / f"{name}.md"), "Summary")
    graph_runs = REC / DEMOS["graph"] / "transcripts"
    excerpts = json.loads((REPO / "tutorial" / "excerpts.json").read_text(encoding="utf-8"))
    return {
        "made": "2026-10-26",
        "experiment": {
            "file": "examples/class-assistant/experiment.toml",
            "title": x["title"], "purpose": x["purpose"].strip(), "criterion": x["criterion"].strip(),
            "judging_question": x["judging_question"], "repeats": x["repeats"], "seed": x["seed"],
            "parts": x["system"]["parts"],
            "rounds": x["rounds"], "comparisons": x["comparisons"], "tolerance": x["controls"]["tolerance"],
            "behaviors": x["behaviors"], "prompts": x["prompts"], "prompt": prompts,
            "model": x["model"], "checks": x["checks"], "reference_checks": reference_checks,
        },
        "demos": {short: demo(name) for short, name in DEMOS.items()},
        "tool_results": {
            "dana_A_first": tool_results(graph_runs / "prep-dana-checkin__A__1.jsonl")[0],
            "dana_C_first": tool_results(graph_runs / "prep-dana-checkin__C__1.jsonl")[0],
        },
        "run_json_C": {k: v for k, v in json.loads((REC / DEMOS["graph"] / "outputs" / "prep-dana-checkin" / "C" / "1" / "run.json").read_text(encoding="utf-8")).items()
                       if k in ("prompt", "round", "repeat", "status", "model", "claude_code_version", "started", "seconds", "output_from", "round_change")}
                      | {"isolation": {k: v for k, v in json.loads((REC / DEMOS["graph"] / "outputs" / "prep-dana-checkin" / "C" / "1" / "run.json").read_text(encoding="utf-8"))["isolation"].items()
                                       if k in ("mcp_servers", "connector_tools", "auto_memory", "verified")}},
        "graph_pages": {"Dana Whitfield": page_text(WIKI / "Dana Whitfield.md")},
        "graph_page_count": len(list(WIKI.glob("*.md"))),
        "people": people,
        "voice": {
            "board_B": "## Board Memo Voice\n\n" + section(voice_b, "Board Memo Voice"),
            "headings_A": [h for h in re.findall(r"^## (.+)$", voice_b, re.M)],
            "headings_D": [h for h in re.findall(r"^## (.+)$", voice_d, re.M)],
        },
        "excerpts": excerpts["files"],
    }


def render(data: dict) -> str:
    text = json.dumps(data, ensure_ascii=False, indent=None, separators=(",", ":"))
    # Inside a <script> element, "</" must not appear.
    return text.replace("</", "<\\/")


# The shared diagrams (the wizard's Getting started screen draws them) that
# the tour shows, copied in so that the page stands alone. Each diagram's own
# light and dark styles become one style sheet that follows the page's theme
# switch as well as the system's setting.
DIAGRAMS = ["class-assistant", "stuck", "folder-map", "order-group"]
DG_BEGIN, DG_END = "<!-- diagrams: begin -->", "<!-- diagrams: end -->"


def diagrams_block(folder: Path) -> str:
    rules, svgs = {}, []
    for name in DIAGRAMS:
        svg = (folder / f"{name}.svg").read_text(encoding="utf-8")
        m = re.search(r"<style>(.*?)</style>", svg, re.S)
        if m:
            light, _, dark = m.group(1).partition("@media (prefers-color-scheme: dark) {")
            dark = dark.rsplit("}", 1)[0]
            for mode, block in (("light", light), ("dark", dark)):
                for sel, decl in re.findall(r"([^{}]+)\{([^{}]*)\}", block):
                    key = (mode, sel.strip())
                    if key in rules and rules[key] != decl.strip():
                        raise SystemExit(f"{name}.svg: {sel.strip()} differs from another diagram's")
                    rules[key] = decl.strip()
            svg = svg.replace(m.group(0), "")
        svgs.append(f'<template id="dg-{name}">{svg.strip()}</template>')
    light = "\n".join(f"{sel}{{{d}}}" for (mode, sel), d in rules.items() if mode == "light")
    dark = [(sel, d) for (mode, sel), d in rules.items() if mode == "dark"]
    css = (light + "\n" + "\n".join(f':root[data-theme="dark"] {sel}{{{d}}}' for sel, d in dark)
           + "\n@media (prefers-color-scheme: dark) {\n" + "\n".join(f':root:not([data-theme="light"]) {sel}{{{d}}}' for sel, d in dark) + "\n}")
    return ("\n<!-- The shared diagrams, from docs/diagrams/ (" + ", ".join(n + ".svg" for n in DIAGRAMS)
            + "), copied in by tutorial/build.py --diagrams. -->\n<style id=\"dg-style\">\n" + css + "\n</style>\n" + "\n".join(svgs) + "\n")


def check_excerpts(folder: Path) -> list[str]:
    bad = []
    norm = lambda s: re.sub(r"\s+", " ", s).strip()
    for e in json.loads((REPO / "tutorial" / "excerpts.json").read_text(encoding="utf-8"))["files"]:
        p = folder / e["path"]
        if not p.is_file() or norm(e["excerpt"]) not in norm(p.read_text(encoding="utf-8")):
            bad.append(e["path"] + ": " + e["excerpt"][:60])
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if starting.html's data block is out of date")
    ap.add_argument("--assistant", type=Path, help="a class assistant folder: check every excerpt is in it")
    ap.add_argument("--diagrams", type=Path, help="a folder of the shared diagrams (docs/diagrams): copy them in")
    a = ap.parse_args()
    if a.assistant:
        bad = check_excerpts(a.assistant)
        for b in bad:
            print("not found:", b)
        if bad:
            return 1
        print("every excerpt is in", a.assistant)
    html = PAGE.read_text(encoding="utf-8")
    if a.diagrams and not a.check:
        di, dj = html.index(DG_BEGIN) + len(DG_BEGIN), html.index(DG_END)
        html = html[:di] + diagrams_block(a.diagrams) + html[dj:]
        PAGE.write_text(html, encoding="utf-8")
        print("copied the diagrams in from", a.diagrams)
    i = html.index(BEGIN) + len(BEGIN)
    j = html.index(END, i)
    new = render(gather())
    if a.check:
        if html[i:j] != new:
            print("starting.html's data block is out of date: run python3 tutorial/build.py")
            return 1
        print("starting.html's data block is up to date")
        return 0
    if html[i:j] != new:
        PAGE.write_text(html[:i] + new + html[j:], encoding="utf-8")
        print("wrote the data block in starting.html")
    else:
        print("starting.html's data block was already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())

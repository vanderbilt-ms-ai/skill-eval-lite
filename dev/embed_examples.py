#!/usr/bin/env python3
"""The designers' starting points, embedded in wizard.html.

    python3 dev/embed_examples.py           write them into wizard.html
    python3 dev/embed_examples.py --check   change nothing; exit 1 if out of date

The experiment designer starts from the class experiment or a demonstration,
and the suite designer from the worked example of Personal I. The wizard is
one offline file that can't read the repository, so it carries their files:
the class experiment's round and starting files, every demonstration's
experiment file, and every file of examples/personal-suites/ (its
suites.yaml read here with run_ab.py's own YAML reader, so that the page
needs none). They go in <script type="application/json" id="designer-examples">.
tests/test_designer.py checks that the block matches the examples.

Reads examples/. Writes that one block of wizard.html. Python 3.11 or later,
standard library. Made for AI 5500 (Vanderbilt, Fall 2026), October 2026.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run_ab  # noqa: E402

EX = ROOT / "examples"
BLOCK = re.compile(r'(<script type="application/json" id="designer-examples">\n)(.*?)(\n</script>)', re.S)


def files_under(folder: Path, skip=()) -> dict:
    out = {}
    for p in sorted(folder.rglob("*")):
        rel = p.relative_to(folder).as_posix()
        if p.is_file() and rel not in skip and "__pycache__" not in p.parts:
            out[rel] = p.read_text(encoding="utf-8")
    return out


def examples() -> dict:
    cls = EX / "class-assistant"
    suites = EX / "personal-suites"
    return {
        "note": "Written by dev/embed_examples.py from examples/; don't edit by hand.",
        "experiment": {"files": files_under(cls, skip=("experiment.toml",))},
        "demos": {p.stem: p.read_text(encoding="utf-8") for p in sorted(EX.glob("demo-*.toml"))},
        "suites": {"data": run_ab.parse_yaml((suites / "suites.yaml").read_text(encoding="utf-8")),
                   "files": files_under(suites, skip=("suites.yaml", "README.md"))},
    }


def block_text() -> str:
    # Inside <script>, "<" is written as <, so that no text in a file can end the block.
    return json.dumps(examples(), ensure_ascii=False, indent=None, separators=(",", ":")).replace("<", "\\u003c")


def main() -> int:
    page = ROOT / "wizard.html"
    html = page.read_text(encoding="utf-8")
    m = BLOCK.search(html)
    if not m:
        print('wizard.html has no <script type="application/json" id="designer-examples"> block.')
        return 2
    want = block_text()
    if m.group(2) == want:
        print("wizard.html: the designers' examples are up to date.")
        return 0
    if "--check" in sys.argv:
        print("wizard.html: the designers' examples are out of date. Run: python3 dev/embed_examples.py")
        return 1
    page.write_text(html[:m.start(2)] + want + html[m.end(2):], encoding="utf-8")
    print("wizard.html: wrote the designers' examples (" + str(len(want) // 1024) + " KB).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

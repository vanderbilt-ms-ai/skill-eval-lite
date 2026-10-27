"""Getting started: the pictures and the steps that lead a new student in.

docs/diagrams/ (and the README's step lists) must match the drawing code in
wizard.html (dev/diagrams.mjs --check, with node); every picture must be
well-formed SVG with a title and a description, in light and dark; the
README's pictures must exist; the intake skill must check the assistant's
folder before it starts. In headless Chrome: the wizard opens on Getting
started with step 1 ready behind it, every step of every path has a picture
and the commands follow the settings, Getting started opens from a step, and
step 2 exports the frozen file, with no console errors."""
import json
import os
import re
import shutil
import subprocess
import time
import tomllib
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))

from cdp import Browser, find_chrome
from helpers import REPO

WIZARD = REPO / "wizard.html"
DIAGRAMS = REPO / "docs" / "diagrams"
CHROME = find_chrome() if os.name == "posix" else None
SVG = "{http://www.w3.org/2000/svg}"


class Pictures(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_files_match_the_drawing_code(self):
        r = subprocess.run(["node", str(REPO / "dev" / "diagrams.mjs"), "--check"], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_every_picture_is_labelled(self):
        files = sorted(DIAGRAMS.rglob("*.svg"))
        self.assertGreater(len(files), 40)
        for f in files:
            root = ET.parse(f).getroot()
            self.assertEqual(root.tag, SVG + "svg", f.name)
            self.assertEqual(root.get("role"), "img", f.name)
            title, desc = root.find(SVG + "title"), root.find(SVG + "desc")
            self.assertTrue(title is not None and title.text and title.text.strip(), f"{f.name} has no title")
            self.assertTrue(desc is not None and desc.text and len(desc.text) > 20, f"{f.name} has no description")
            style = root.find(SVG + "style").text
            self.assertIn("prefers-color-scheme: dark", style, f"{f.name} has no dark colors")

    def test_readme_pictures_exist(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn("## Getting started, in pictures", readme)
        refs = re.findall(r'(?:src="|\]\()(docs/diagrams/[^")]+\.svg)', readme)
        self.assertGreater(len(refs), 20)
        for ref in refs:
            self.assertTrue((REPO / ref).is_file(), ref)


class IntakeSkill(unittest.TestCase):
    def test_checks_the_folder_first(self):
        skill = (REPO / ".claude/skills/experiment-intake/SKILL.md").read_text(encoding="utf-8")
        check = skill[skill.index("## 1. Check that the assistant's folder is ready"):skill.index("## 2. Read the assistant")]
        for must in ("It doesn't exist", "has no `CLAUDE.md`", "isn't a git project", "explicit yes", "git init",
                     "Never write a `CLAUDE.md`", "python3 run_ab.py setup ../class-assistant", "never make them"):
            self.assertIn(must, check)
        self.assertIn("Export the frozen experiment", skill)


JS = r"""window.__btn = t => [...document.querySelectorAll('button')].find(b => b.textContent.trim() === t && !b.disabled);
window.__click = t => { const b = __btn(t); if (!b) return false; b.click(); return true; };
window.__path = t => { const b = [...document.querySelectorAll('.gs-path')].find(x => x.querySelector('.t').textContent === t); b.click(); return true; };
true"""


@unittest.skipUnless(CHROME, "headless Chrome is not available")
class GettingStarted(unittest.TestCase):
    def setUp(self):
        self.b = Browser(CHROME)
        self.b.goto(WIZARD.as_uri())
        self.b.js("localStorage.clear()")
        self.b.goto(WIZARD.as_uri())
        self.b.js(JS)

    def tearDown(self):
        errors = list(self.b.errors)
        self.b.close()
        self.assertEqual(errors, [], "console errors in the wizard")

    def test_every_path_steps_with_pictures(self):
        b = self.b
        self.assertTrue(b.js("!document.getElementById('start').hidden && document.querySelector('main').hidden"), "Getting started comes first")
        self.assertTrue(b.js("!!document.getElementById('bundle-file')"), "step 1 is ready behind it")
        self.assertIn("starting.html", b.js("document.querySelector('.gs-new').innerHTML"))
        self.assertIn("run_ab.py status", b.js("document.querySelector('.gs-stuck').textContent"))
        for title in ("A demonstration", "The class experiment", "Your group’s experiment", "Personal I: suites"):
            b.js(f"__path({json.dumps(title)})")
            steps = b.js("document.querySelectorAll('ol.gs-steps > li').length")
            self.assertGreater(steps, 12, title)
            self.assertEqual(b.js("document.querySelectorAll('ol.gs-steps > li .gs-pic svg[role=img] title').length"), steps, title + ": a picture for each step")
            self.assertEqual(b.js("[...document.querySelectorAll('ol.gs-steps > li')].filter(li => !li.querySelector('.gs-see')).length"), 0, title + ": what you should see")
        b.js(JS)
        b.js("__path('Your group’s experiment'); __click('Windows'); true")
        b.js("const i = document.getElementById('gs-name'); i.value = 'board-memo'; i.dispatchEvent(new Event('change')); true")
        cmds = b.js("[...document.querySelectorAll('ol.gs-steps .gs-cmd code')].map(c => c.textContent)")
        self.assertIn("py run_ab.py check experiments/board-memo/experiment.toml", cmds)
        self.assertTrue(any(c.startswith("Move-Item -Force ~/Downloads/experiment.toml experiments/board-memo/") for c in cmds), cmds)

    def test_from_a_step_and_back_and_the_frozen_file(self):
        b = self.b
        self.assertTrue(b.js("__click('Use the class assistant’s intake')"))
        self.assertTrue(b.js("document.getElementById('start').hidden"), "loading a file opens the steps")
        self.assertTrue(b.js("!!document.querySelector('#explain .box.where svg[role=img]')"), "each step has its picture")
        b.js("document.querySelectorAll('#steps button')[1].click(); true")
        b.js(JS)
        self.assertTrue(b.js("__click('Freeze')"))
        b.until("document.querySelector('main').innerText.includes('Next: save the frozen file')")
        b.js(JS)
        self.assertTrue(b.js("__click('Export the frozen experiment')"))
        path = Path(b.downloads) / "experiment.toml"
        for _ in range(100):
            if path.exists() and not path.with_name(path.name + ".crdownload").exists():
                break
            time.sleep(0.05)
        self.assertRegex(tomllib.loads(path.read_text(encoding="utf-8"))["frozen"]["hash"], r"^sha256:[0-9a-f]{64}$")
        self.assertTrue(b.js("document.getElementById('gs-btn').click(); !document.getElementById('start').hidden"))
        self.assertTrue(b.js("document.getElementById('gs-btn').getAttribute('aria-pressed') === 'true'"))


if __name__ == "__main__":
    unittest.main()

"""The guided tour (starting.html): its quoted material is the recorded runs'
own (tutorial/build.py --check), it loads nothing from the network, its
version is VERSION's, and, in headless Chrome, every stop can be completed
through its own buttons at a laptop's size (1366 x 768, where no stop may
scroll) and a phone's (390 px wide, where nothing may be wider than the
screen), with no console errors and no glossary word left undefined.

Chrome is found as in test_wizard.py; without it the walk is skipped."""
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cdp import Browser, find_chrome
from helpers import REPO

PAGE = REPO / "starting.html"
CHROME = find_chrome() if os.name == "posix" else None

# What may not overflow: at a laptop's size, the page, the stage and the
# explanation each fit their box; at any size, nothing (outside a box that
# scrolls sideways on purpose) sticks out past the screen.
OVERFLOW = r"""((W) => {
  const de = document.documentElement, out = [];
  if (innerWidth > W + 1) out.push('the layout is ' + innerWidth + ' px wide');
  if (de.scrollWidth > innerWidth + 1) out.push('the page scrolls sideways');
  if (innerWidth > 860) {
    if (de.scrollHeight > innerHeight) out.push('the page scrolls');
    for (const sel of ['#stage', '.rail-body']) { const el = document.querySelector(sel); if (el.scrollHeight > el.clientHeight + 1) out.push(sel + ' scrolls'); }
  }
  for (const el of document.querySelectorAll('#stage *, #rail *')) {
    const r = el.getBoundingClientRect();
    if (!r.width) continue;
    let p = el.parentElement, boxed = false;
    while (p && p !== document.body) { if (/(auto|scroll|hidden)/.test(getComputedStyle(p).overflowX)) { boxed = true; break; } p = p.parentElement; }
    if (!boxed && r.right > innerWidth + 1) { out.push('sticks out: ' + el.tagName.toLowerCase() + '.' + el.className); break; }
  }
  return out;
})"""


class Static(unittest.TestCase):
    def test_data_block_is_the_recorded_runs(self):
        r = subprocess.run([sys.executable, str(REPO / "tutorial" / "build.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_offline_page(self):
        html = PAGE.read_text(encoding="utf-8")
        self.assertIsNone(re.search(r'(src|href)="https?://', html), "the tour loads nothing from the network")
        self.assertNotIn("@font-face", html)
        self.assertNotIn("fetch(", html)

    def test_version(self):
        v = (REPO / "VERSION").read_text().strip()
        self.assertIn(f'<meta name="skill-eval-lite-version" content="{v}">', PAGE.read_text(encoding="utf-8"))

    def test_readme_points_here(self):
        self.assertIn("starting.html", "\n".join((REPO / "README.md").read_text(encoding="utf-8").splitlines()[:6]))


@unittest.skipUnless(CHROME, "headless Chrome is not available")
class Walk(unittest.TestCase):
    def test_every_stop_at_two_sizes(self):
        b = Browser(CHROME)
        problems = []
        try:
            for w, h, mobile in ((1366, 768, False), (390, 844, True)):
                b.send("Emulation.setDeviceMetricsOverride", {"width": w, "height": h, "deviceScaleFactor": 1, "mobile": mobile}, session=True)
                b.goto(PAGE.as_uri() + f"?w={w}")
                b.js("localStorage.clear()")
                n = b.js("__tour.STOPS.length")
                self.assertGreaterEqual(n, 14)
                for i in range(n):
                    sid = b.js(f"__tour.go({i}); __tour.STOPS[{i}].id")
                    problems += [f"{w} px, stop {i + 1} ({sid}), before: {p}" for p in b.js(OVERFLOW + f"({w})")]
                    b.js("__tour.complete()")
                    try:
                        b.until("__tour.isDone()", timeout=5)
                    except TimeoutError:
                        problems.append(f"{w} px, stop {i + 1} ({sid}): its action didn't complete it")
                    problems += [f"{w} px, stop {i + 1} ({sid}), after: {p}" for p in b.js(OVERFLOW + f"({w})")]
                missing = b.js("[...__tour.missingTerms]")
                if missing:
                    problems.append(f"glossary words without a definition: {missing}")
            problems += ["console: " + e for e in b.errors]
        finally:
            b.close()
        self.assertEqual(problems, [], "\n".join(problems))


if __name__ == "__main__":
    unittest.main()

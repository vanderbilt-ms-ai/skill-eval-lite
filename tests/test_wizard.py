"""The wizard (wizard.html): its TOML reader against Python's tomllib, the
class intake embedded in it against the example file, its version against
VERSION, and two journeys in headless Chrome: a runner's bundle (made with
the fake `claude`) from step 1 to the exports, and the made-up practice pack.
Each journey judges every pair and fails on any console error.

Chrome is found as google-chrome-stable, google-chrome or chromium, or at
CHROME_PATH; without it the journeys are skipped. The TOML test uses node
when it is installed, and Chrome otherwise."""
import csv
import io
import json
import math
import os
import re
import shutil
import subprocess
import tomllib
import unittest
from pathlib import Path

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

from cdp import Browser, find_chrome
from helpers import EXAMPLES, FAKE, REPO, class_assistant, fake_run, run_ab, tmpdir

WIZARD = REPO / "wizard.html"
CHROME = find_chrome() if os.name == "posix" else None
TOML_FILES = [EXAMPLES / "class-assistant" / "experiment.toml", *sorted(EXAMPLES.glob("demo-*.toml"))]


def page_script() -> str:
    html = WIZARD.read_text(encoding="utf-8")
    return html[html.index("function parseToml"):html.index("function readIntake")]


def normalize(obj):
    return json.loads(json.dumps(obj, sort_keys=True, ensure_ascii=False))


# The wizard's generator and bootstrap, in Python, to check its numbers.
M32 = 0xFFFFFFFF


def mulberry32(seed):
    a = seed & M32

    def r():
        nonlocal a
        a = (a + 0x6D2B79F5) & M32
        t = a
        t = ((t ^ (t >> 15)) * (t | 1)) & M32
        t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & M32)) & M32
        return ((t ^ (t >> 14)) & M32) / 4294967296
    return r


def bootstrap(groups, seed, B=10000):
    r, k, out = mulberry32(seed), len(groups), []
    for _ in range(B):
        s = m = 0
        for _ in range(k):
            g = groups[math.floor(r() * k)]
            s += sum(g)
            m += len(g)
        out.append(s / m)
    out.sort()
    q = lambda p: out[max(0, math.ceil(p * B) - 1)]
    return {"lo": q(0.025), "hi": q(0.975)}


class Static(unittest.TestCase):
    def test_embedded_intake_is_the_example(self):
        html = WIZARD.read_text(encoding="utf-8")
        m = re.search(r'<script type="text/plain" id="class-intake">\n(.*?)\n</script>', html, re.S)
        self.assertEqual(m.group(1).strip(), (EXAMPLES / "class-assistant" / "experiment.toml").read_text().strip(),
                         "wizard.html's class intake differs from examples/class-assistant/experiment.toml")

    def test_version_in_one_place(self):
        v = (REPO / "VERSION").read_text().strip()
        html = WIZARD.read_text(encoding="utf-8")
        self.assertIn(f'<meta name="skill-eval-lite-version" content="{v}">', html)
        self.assertEqual(run_ab("--version").stdout.strip(), f"skill-eval-lite {v}")

    def test_offline_page(self):
        html = WIZARD.read_text(encoding="utf-8")
        self.assertIsNone(re.search(r'(src|href)="https?://', html), "the wizard loads nothing from the network")
        self.assertNotIn("@font-face", html)
        self.assertNotIn("fetch(", html)

    def test_toml_reader_agrees_with_tomllib(self):
        code = page_script()
        node = shutil.which("node")
        for f in TOML_FILES:
            want = normalize(tomllib.loads(f.read_text(encoding="utf-8")))
            src = json.dumps(f.read_text(encoding="utf-8"))
            if node:
                out = subprocess.run([node, "-e", code + f"; process.stdout.write(JSON.stringify(parseToml({src})))"],
                                     capture_output=True, text=True, timeout=60)
                self.assertEqual(out.returncode, 0, out.stderr)
                got = normalize(json.loads(out.stdout))
            elif CHROME:
                b = Browser(CHROME)
                try:
                    got = normalize(b.js(code + f"; parseToml({src})"))
                finally:
                    b.close()
            else:
                self.skipTest("neither node nor Chrome is installed")
            self.assertEqual(got, want, f.name)


JS_HELPERS = r"""
window.__btn = text => [...document.querySelectorAll('button')].find(b => b.textContent.trim() === text && !b.disabled);
window.__click = text => { const b = __btn(text); if (!b) return false; b.click(); return true; };
window.__judgeAll = async (pick) => {
  for (let n = 0; n < 200; n++) {
    if (document.querySelector('main').innerText.includes('You have judged every pair')) return n;
    const texts = [...document.querySelectorAll('.grid2 .product .a')].map(e => e.textContent);
    const side = pick(texts[0] || '', texts[1] || '');
    if (!__click(side)) throw new Error('no button ' + side);
    const reason = document.getElementById('reason');
    reason.value = 'test: ' + side; reason.dispatchEvent(new Event('input'));
    if (!__click('Record')) throw new Error('could not record');
    if (!__click('Next pair →') && !__click('Finish')) throw new Error('no next');
  }
  throw new Error('too many pairs');
};
true
"""


@unittest.skipUnless(CHROME, "headless Chrome is not available")
class Journey(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.chmod(FAKE, 0o755)
        cls.root = tmpdir()
        assistant = class_assistant(cls.root)
        cls.out = cls.root / "runs" / "graph"
        r = fake_run(EXAMPLES / "demo-graph-removed.toml", assistant, cls.out)
        assert r.returncode == 0, r.stdout + r.stderr
        j = run_ab("judge", cls.out, "--claude", FAKE)
        assert j.returncode == 0, j.stdout + j.stderr

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def setUp(self):
        self.b = Browser(CHROME)
        self.b.goto(WIZARD.as_uri())
        self.b.js("localStorage.clear()")
        self.b.goto(WIZARD.as_uri())
        self.b.js(JS_HELPERS)

    def tearDown(self):
        errors = list(self.b.errors)
        self.b.close()
        self.assertEqual(errors, [], "console errors in the wizard")

    def step(self, n):
        self.b.js(f"document.querySelectorAll('#steps button')[{n - 1}].click(); true")
        self.b.js(JS_HELPERS)

    def downloaded(self, label, name):
        before = set(os.listdir(self.b.downloads))
        self.assertTrue(self.b.js(f"__click({json.dumps(label)})"), label)
        path = Path(self.b.downloads) / name
        for _ in range(100):
            if path.exists() and not (Path(self.b.downloads) / (name + ".crdownload")).exists():
                return path.read_text(encoding="utf-8")
            import time
            time.sleep(0.05)
        self.fail(f"{name} was not downloaded ({sorted(set(os.listdir(self.b.downloads)) - before)})")

    def test_bundle_from_the_runner(self):
        b = self.b
        b.set_files("#bundle-file", [self.out / "bundle.json"])
        b.until("document.querySelector('main').innerText.includes('Can the evaluation see the knowledge graph')")
        self.assertTrue(b.js("document.querySelector('main').innerText.includes('A demonstration (demo = true)')"))
        self.assertTrue(b.js("document.querySelector('main').innerText.includes('2 development prompts, once each')"))
        self.step(2)
        self.assertTrue(b.js("__click('Freeze this demonstration')"))
        b.until("document.querySelector('main').innerText.includes('The record')")
        self.assertTrue(b.js("document.querySelector('main').innerText.includes('Unmet when frozen')"))
        self.step(3)
        self.assertIn("writes runs/<name>/bundle.json", b.js("document.getElementById('explain').innerText"),
                      "a <name> in a step's text is shown, not taken for an HTML tag")
        self.assertTrue(b.js("document.querySelector('main').innerText.includes('4 ok · 0 failed or timed out · 0 still to come')"))
        self.assertTrue(b.js("document.querySelector('.cellbtn').click(); document.getElementById('overlay').innerText.includes('The route')"))
        self.assertTrue(b.js("__click('Close')"))
        self.step(4)
        b.js("document.getElementById('initials').value = 'SL'; __click('Start')")
        b.js(JS_HELPERS)
        n = b.js("__judgeAll((l, r) => l.includes('120,000') && !r.includes('120,000') ? 'Left is better' : r.includes('120,000') && !l.includes('120,000') ? 'Right is better' : 'About the same')")
        self.assertEqual(n, 2, "two blind pairs")
        self.step(5)
        text = b.js("document.getElementById('stage').textContent")
        self.assertRegex(text, r"round C \(knowledge graph removed\) was preferred to round A \(as it is\) in 0% of 2 judgments")
        self.assertIn("Did the evaluation move when it should?", text)
        self.assertIn("names-the-renewal-amount", text)
        csv_text = self.downloaded("Export judgments.csv", "judgments.csv")
        rows = list(csv.DictReader(io.StringIO(csv_text)))
        self.assertEqual(list(rows[0].keys()), ["item", "config", "object", "check", "route", "judge", "version", "result",
                                                "reason", "shown_left", "when"])
        routes = [r["route"] for r in rows]
        self.assertEqual(routes.count("human"), 2)
        self.assertEqual(routes.count("llm"), 2)
        self.assertIn("mechanical", routes)
        self.assertTrue(any(r["config"] == "reference" for r in rows))
        res = json.loads(self.downloaded("Export results.json", "results.json"))
        self.assertEqual(res["improvement"]["comparison"], "A|C")
        frozen = self.downloaded("Export the frozen experiment", "experiment.toml")
        self.assertRegex(tomllib.loads(frozen)["frozen"]["hash"], r"^sha256:[0-9a-f]{64}$")

    def test_recorded_bundles_load(self):
        for d in sorted(p for p in (EXAMPLES / "recorded").iterdir() if p.name.startswith("demo-")):
            b = self.b
            b.js("__click('Reset')")
            b.set_files("#bundle-file", [d / "bundle.json"])
            b.until("document.querySelector('main').innerText.includes('demonstration')")
            self.step(2)
            self.assertTrue(b.js("__click('Freeze this demonstration')"), d.name)
            b.until("document.querySelector('main').innerText.includes('The record')")
            self.step(3)
            rec = json.loads((d / "bundle.json").read_text(encoding="utf-8"))
            runs, pairs = len(rec["outputs"]), len(rec["judge"])
            self.assertTrue(b.js(f"document.querySelector('main').innerText.includes('{runs} ok · 0 failed or timed out · 0 still to come')"), d.name)
            self.assertTrue(b.js(f"document.querySelector('main').innerText.includes('runs, {pairs} judge verdicts')"), d.name)
            self.step(4)
            b.js("document.getElementById('initials').value = 'R'; __click('Start')")
            b.js(JS_HELPERS)
            self.assertEqual(b.js("__judgeAll(() => 'About the same')"), pairs, d.name)
            self.step(5)
            self.assertIn("Did the evaluation move when it should?", b.js("document.getElementById('stage').innerText"), d.name)

    def test_fast_judging(self):
        """Fast judging: one click records with no reason, Skip leaves a pair unjudged, the dots go back to it, and keys work."""
        b = self.b
        b.js("__click('Reset')")
        b.set_files("#bundle-file", [EXAMPLES / "recorded" / "demo-one-line" / "bundle.json"])
        b.until("document.querySelector('main').innerText.includes('demonstration')")
        self.step(2)
        self.assertTrue(b.js("__click('Freeze this demonstration')"))
        self.step(4)
        b.js("document.getElementById('initials').value = 'ROOM'; __click('Start')")
        b.js(JS_HELPERS)
        b.js("document.getElementById('fast').click(); true")
        self.assertTrue(b.js("S.fast === true"))
        self.assertTrue(b.js("__click('Left is better')"), "one click records")
        self.assertEqual(b.js("S.judgments.filter(j => j.judge === 'ROOM').length"), 1)
        self.assertEqual(b.js("S.judgments[S.judgments.length - 1].reason"), "")
        self.assertIn("You chose the left one.", b.js("document.getElementById('stage').innerText"))
        self.assertTrue(b.js("__click('Next pair →')"))
        self.assertTrue(b.js("__click('Skip →')"), "a pair can be skipped")
        self.assertEqual(b.js("S.judgments.filter(j => j.judge === 'ROOM').length"), 1, "skipping records nothing")
        self.assertEqual(b.js("document.querySelectorAll('.stops span.skipped').length"), 1)
        b.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'r'})); true")
        self.assertEqual(b.js("S.judgments.filter(j => j.judge === 'ROOM').length"), 2, "R records")
        b.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowRight'})); true")
        self.assertIn("You skipped 1 pair.", b.js("document.getElementById('stage').innerText"))
        self.assertTrue(b.js("__click('Back to the skipped pairs')"))
        self.assertTrue(b.js("__click('About the same')"))
        self.assertEqual(b.js("S.judgments.filter(j => j.judge === 'ROOM').length"), 3)
        b.js("document.querySelectorAll('.stops span')[0].click(); true")
        self.assertIn("You chose", b.js("document.getElementById('stage').innerText"), "a judged pair's dot shows its reveal")
        self.step(5)
        self.assertIn("Did the evaluation move when it should?", b.js("document.getElementById('stage').innerText"))

    def test_recorded_suites_load(self):
        b = self.b
        b.set_files("#bundle-file", [EXAMPLES / "recorded" / "personal-suites" / "bundle.json"])
        b.until("S.mode === 'suites'")
        self.step(4)
        text = b.js("document.getElementById('stage').innerText")
        self.assertIn("Suite report: graph-briefs", text)
        self.assertIn("MISSED", text, "the recorded run's findings show")

    def test_practice_pack(self):
        b = self.b
        self.assertTrue(b.js("__click('Use the class assistant’s intake')"))
        self.assertTrue(b.js("document.querySelector('main').innerText.includes('Nothing is missing.')"))
        self.step(2)
        self.assertTrue(b.js("__click('Freeze')"))
        b.until("document.querySelector('main').innerText.includes('The record')")
        self.step(3)
        self.assertTrue(b.js("__click('Load the made-up practice outputs')"))
        self.assertTrue(b.js("document.querySelector('main').innerText.includes('31 ok · 1 failed or timed out')"))
        self.step(4)
        b.js("document.getElementById('initials').value = 'TW'; __click('Start')")
        b.js(JS_HELPERS)
        n = b.js("__judgeAll((l, r) => l.length > r.length ? 'Left is better' : l.length < r.length ? 'Right is better' : 'About the same')")
        self.assertEqual(n, 24)
        self.step(5)
        res = json.loads(b.js("JSON.stringify(resultsJson())"))
        self.assertTrue(res["made_up_outputs"])
        rows = list(csv.DictReader(io.StringIO(b.js("judgmentsCsv()"))))
        x = tomllib.loads((EXAMPLES / "class-assistant" / "experiment.toml").read_text())
        dev, seed = x["prompts"]["development"], x["seed"]
        score = lambda v: 1 if v == "B" else 0.5 if v == "tie" else 0
        groups = [g for g in ([score(r["result"]) for r in rows if r["route"] == "human" and r["config"] == "A|B"
                               and r["item"].split("/")[0] == p] for p in dev) if g]
        want = bootstrap(groups, seed)
        got = res["improvement"]["people"]["interval_95"]
        self.assertAlmostEqual(got["lo"], want["lo"], places=12)
        self.assertAlmostEqual(got["hi"], want["hi"], places=12)


if __name__ == "__main__":
    unittest.main()


SUITE_JS = r"""
window.__suiteAll = async (choice) => {
  for (let n = 0; n < 400; n++) {
    const stage = document.getElementById('stage').innerText;
    if (stage.includes('You and the LLM') || stage.includes('You have judged every')) return n;
    if (__click('Next case →') || __click('Next pair →') || __click('Finish')) continue;
    if (!__click(choice)) throw new Error('no button ' + choice + ' in: ' + stage.slice(0, 300));
    const r = document.getElementById('s-reason'); r.value = 'test: ' + choice; r.dispatchEvent(new Event('input'));
    if (!__click('Record')) throw new Error('could not record');
  }
  throw new Error('too many cases');
};
true
"""


@unittest.skipUnless(CHROME and os.name == "posix", "headless Chrome is not available")
class ChecksOnlyJourney(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import sys as _sys
        _sys.path.insert(0, str(REPO))
        import run_ab as R
        cls.R = R
        os.chmod(FAKE, 0o755)
        cls.root = tmpdir()
        cls.out = cls.root / "packet"
        r = run_ab("suite", EXAMPLES / "personal-suites" / "suites.yaml", "--out", cls.out, "--claude", FAKE)
        assert r.returncode == 0, r.stdout + r.stderr

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def setUp(self):
        self.b = Browser(CHROME)
        self.b.goto(WIZARD.as_uri())
        self.b.js("localStorage.clear()")
        self.b.goto(WIZARD.as_uri())
        self.helpers()

    def helpers(self):
        self.b.js(JS_HELPERS)
        self.b.js(SUITE_JS)

    def tearDown(self):
        errors = list(self.b.errors)
        self.b.close()
        self.assertEqual(errors, [], "console errors in the wizard")

    def step(self, n):
        self.b.js(f"document.querySelectorAll('#steps button')[{n - 1}].click(); true")
        self.helpers()

    def start(self, initials):
        self.b.js(f"document.getElementById('s-initials').value = '{initials}'; __click('Start') || __click('Switch')")
        self.helpers()

    def downloaded(self, label, name):
        import time
        self.assertTrue(self.b.js(f"__click({json.dumps(label)})"), label)
        path = Path(self.b.downloads) / name
        for _ in range(100):
            if path.exists() and not (Path(self.b.downloads) / (name + ".crdownload")).exists():
                return path.read_text(encoding="utf-8")
            time.sleep(0.05)
        self.fail(name + " was not downloaded")

    def test_reference_ratings_and_report(self):
        b = self.b
        b.set_files("#bundle-file", [self.out / "bundle.json"])
        b.until("S.mode === 'suites'")
        self.assertIn("board-drafts", b.js("document.getElementById('stage').innerText"))
        self.step(2)
        self.start("SL")
        self.assertNotIn("The LLM", b.js("document.getElementById('stage').innerText"), "the LLM's decisions stay hidden")
        for test, n in (("facts-match-the-source", 11), ("steps-follow", 9)):
            b.js(f"__click({json.dumps(test)})")
            self.helpers()
            self.assertEqual(b.js("__suiteAll('Pass')"), 2 * n)
            self.assertIn("You and the LLM", b.js("document.getElementById('stage').innerText"))
        self.step(3)
        for test, n in (("sendable", 11), ("sound-process", 9)):
            b.js(f"__click({json.dumps(test)})")
            self.helpers()
            self.assertEqual(b.js("__suiteAll('3')"), 2 * n)
        self.step(4)
        text = b.js("document.getElementById('stage').innerText")
        self.assertIn("Suite report: board-drafts", text)
        self.assertIn("Did each test do what the control cases expect?", text)
        rows_text = self.downloaded("Export judgments.csv", "judgments.csv")
        rows = list(csv.DictReader(io.StringIO(rows_text)))
        self.assertEqual(sum(r["route"] == "human" for r in rows), 40, "20 reference judgments and 20 ratings")
        self.assertEqual(sum(r["check"].endswith("-reference") for r in rows), 20)
        S = self.R.Suites(self.out / "suites.yaml")
        for s in S.suites:
            name = f"{s['id']}-{s['version']}.md"
            mine = self.downloaded(f"Export {name}", name)
            want = self.R.suite_report(s, rows, "WHEN")
            norm = lambda t: re.sub(r"Written \S+ by [^.]+(\.\d+\.\d+)*[^.]*\.", "Written.", t)
            self.assertEqual(norm(mine), norm(want), f"the wizard's report for {s['id']} differs from run_ab.py's")
        self.assertIn("SL's reference judgments agree on", mine)

    def test_comparison_records_the_side(self):
        copy = self.root / "compare"
        shutil.copytree(self.out, copy)
        y = (copy / "suites.yaml").read_text()
        y = y.replace("        form: rating\n        question: Would you trust a brief made this way?",
                      "        form: comparison\n        pairs: [[reference, fault-no-search], [dana-brief-1, dana-brief-2]]\n        question: Would you trust a brief made this way?")
        (copy / "suites.yaml").write_text(y)
        r = run_ab("suite", copy / "suites.yaml", "--no-llm")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        b = self.b
        b.set_files("#bundle-file", [copy / "bundle.json"])
        b.until("S.mode === 'suites'")
        self.step(3)
        self.start("TW")
        b.js("__click('sound-process')")
        self.helpers()
        self.assertEqual(b.js("__suiteAll('Left is better')"), 4)
        rows = list(csv.DictReader(io.StringIO(b.js("sCsv()"))))
        comp = [r for r in rows if r["check"] == "sound-process" and r["route"] == "human"]
        self.assertEqual(len(comp), 2)
        for r in comp:
            self.assertIn(r["shown_left"], r["item"].split("|"))
            self.assertEqual(r["result"], r["shown_left"], "the left one won, and the side is recorded")

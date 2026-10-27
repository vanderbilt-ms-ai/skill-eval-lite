"""The designers in wizard.html: the experiment designer (Shared I) and the
suite designer (Personal I).

Offline: the embedded examples are up to date (dev/embed_examples.py).
In headless Chrome:
- the class start, the demonstrations and the worked example, written out
  unchanged, match examples/ (tomllib and run_ab.py's YAML reader);
- the TOML and YAML writers keep awkward text exactly;
- the designers' copies of `run_ab.py check` and `suite --check` say what
  run_ab.py says, word for word, on broken files;
- journeys, by the page's own buttons and fields: (a) an experiment from the
  class start, changed; (b) one from blank, with an assistant's folder, a
  custom prompt and a starting file; (c) a suites file from blank. Each is
  saved as a ZIP, unzipped into a copy of skill-eval-lite, and passes
  `check` (and, for (b), runs with the fake claude), or `suite --check` and
  `suite` with the fake claude, whose bundle loads in the checks-only mode;
  (a) also saves through a stand-in for the folder picker, and loads in
  step 1 and freezes;
- every screen fits 390 px with no sideways scroll, and every field has a
  label; no console errors.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cdp import Browser, find_chrome  # noqa: E402
from helpers import EXAMPLES, FAKE, KB_PY, REPO, git, tmpdir  # noqa: E402

sys.path.insert(0, str(REPO))
import run_ab as R  # noqa: E402

WIZARD = REPO / "wizard.html"
CHROME = find_chrome() if os.name == "posix" else None
CLASS = EXAMPLES / "class-assistant"
PACKET = EXAMPLES / "personal-suites"

JS = r"""
window.__btn = (t, root) => [...(root || document).querySelectorAll('button')].find(b => b.textContent.trim() === t && !b.disabled);
window.__click = (t, root) => { const b = __btn(t, root); if (!b) throw new Error('no button: ' + t); b.click(); return true; };
window.__id = id => { const e = document.getElementById(id); if (!e) throw new Error('no element #' + id); return e; };
window.__fire = e => { e.dispatchEvent(new Event('input', { bubbles: true })); e.dispatchEvent(new Event('change', { bubbles: true })); return true; };
window.__set = (id, v) => { const e = __id(id); e.value = v; return __fire(e); };
window.__open = () => document.querySelector('.dz-item.open');
window.__in = suffix => { const e = document.querySelector('.dz-item.open [id$="' + suffix + '"]'); if (!e) throw new Error('no field ' + suffix + ' in the open card'); return e; };
window.__setIn = (suffix, v) => { const e = __in(suffix); e.value = v; return __fire(e); };
window.__screen = n => { document.querySelectorAll('#dz-screens button')[n].click(); return true; };
window.__text = () => document.getElementById('designer').innerText;
window.confirm = () => true;
true
"""


# A stand-in for the browser's folder picker: a folder called `name`, holding
# the folders `has`, that keeps what is written to it in window.__fs.
MOCK_PICKER = r"""window.__picker = (name, has) => { window.__fs = {};
  const dirH = (nm, path) => ({ kind: 'directory', name: nm,
    async getDirectoryHandle(n, o) { const p = path + n + '/'; if (!(o && o.create) && !has.includes(p.slice(0, -1)) && !Object.keys(__fs).some(k => k.startsWith(p))) throw new DOMException('none', 'NotFoundError'); return dirH(n, p); },
    async getFileHandle(n, o) { const p = path + n; if (!(o && o.create) && !(p in __fs)) throw new DOMException('none', 'NotFoundError');
      return { kind: 'file', name: n, async createWritable() { const parts = []; return { async write(d) { parts.push(d); }, async close() { __fs[p] = new TextDecoder().decode(parts[0]); } }; } }; } });
  window.showDirectoryPicker = async () => dirH(name, ''); return true; };
"""


def files_of(folder: Path, skip=()) -> dict:
    return {p.relative_to(folder).as_posix(): p.read_text(encoding="utf-8") for p in sorted(folder.rglob("*"))
            if p.is_file() and p.relative_to(folder).as_posix() not in skip and "__pycache__" not in p.parts}


def without(d: dict, *keys) -> dict:
    return {k: v for k, v in d.items() if k not in keys}


def write_tree(root: Path, files: dict):
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")


class Embedded(unittest.TestCase):
    def test_examples_are_up_to_date(self):
        r = subprocess.run([sys.executable, str(REPO / "dev" / "embed_examples.py"), "--check"], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class Page(unittest.TestCase):
    """A browser on the wizard, with the helpers above."""

    @classmethod
    def setUpClass(cls):
        cls.root = tmpdir()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def setUp(self):
        self.b = Browser(CHROME, timeout=60)
        self.b.goto(WIZARD.as_uri())
        self.b.js("localStorage.clear()")
        self.b.goto(WIZARD.as_uri())
        self.b.js(JS)

    def tearDown(self):
        errors = list(self.b.errors)
        self.b.close()
        self.assertEqual(errors, [], "console errors in the wizard")

    def js(self, code):
        return self.b.js(code)

    def downloaded(self, name):
        path = Path(self.b.downloads) / name
        for _ in range(200):
            if path.exists() and not (Path(self.b.downloads) / (name + ".crdownload")).exists():
                time.sleep(0.05)
                return path
            time.sleep(0.05)
        self.fail(f"{name} was not downloaded ({os.listdir(self.b.downloads)})")

    def skill_eval_lite(self, where: Path) -> Path:
        """A copy of skill-eval-lite: the runner and its version."""
        sel = where / "skill-eval-lite"
        sel.mkdir(parents=True)
        for name in ("run_ab.py", "VERSION"):
            shutil.copy(REPO / name, sel / name)
        return sel

    def sel(self, copy: Path, *args, timeout=300):
        e = {k: v for k, v in os.environ.items() if not k.startswith("FAKE_CLAUDE_")}
        return subprocess.run([sys.executable, str(copy / "run_ab.py"), *map(str, args)], capture_output=True, text=True, cwd=copy, env=e, timeout=timeout)

    def unzip(self, zpath: Path, into: Path, top: str) -> dict:
        with zipfile.ZipFile(zpath) as z:
            self.assertIsNone(z.testzip(), "every file's CRC is right")
            names = z.namelist()
            self.assertTrue(all(n.startswith(top + "/") for n in names), names)
            z.extractall(into)
        if shutil.which("unzip"):
            r = subprocess.run(["unzip", "-tq", str(zpath)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return {n[len(top) + 1:]: (into / n).read_text(encoding="utf-8") for n in names}


@unittest.skipUnless(CHROME, "headless Chrome is not available")
class Writers(Page):
    def test_class_start_writes_the_class_experiment(self):
        out = self.js("ED = edFromStart('class'); JSON.stringify(edOutput(ED).files)")
        files = json.loads(out)
        got, want = tomllib.loads(files.pop("experiment.toml")), tomllib.loads((CLASS / "experiment.toml").read_text())
        self.assertEqual(without(got, "provenance"), without(want, "provenance"))
        # rounds/one-line/ is the round file of demo-one-line.toml (the live session's demonstration), not the class experiment's.
        want_files = {k: v for k, v in files_of(CLASS, skip=("experiment.toml",)).items() if not k.startswith("rounds/one-line/")}
        self.assertEqual(files, want_files, "the round and starting files, byte for byte")
        # The page's own TOML reader reads it as tomllib does.
        page = json.loads(self.js("JSON.stringify(parseToml(edOutput(ED).text))"))
        self.assertEqual(page, json.loads(json.dumps(got)))
        self.assertEqual(self.js("JSON.stringify(edProblems(ED).filter(p => p.level !== 'ok'))"), "[]")

    def test_demonstrations_pass_check(self):
        for demo in sorted(p.stem for p in EXAMPLES.glob("demo-*.toml")):
            files = json.loads(self.js(f"JSON.stringify(edOutput(edFromStart('{demo}')).files)"))
            folder = self.root / "demos" / demo
            write_tree(folder, files)
            exp = R.Experiment(folder / "experiment.toml")
            errors, _ = exp.problems()
            self.assertEqual(errors, [], demo)
            self.assertTrue(exp.data["demo"])
            want = tomllib.loads((EXAMPLES / f"{demo}.toml").read_text())
            self.assertEqual([r["id"] for r in exp.data["rounds"]], [r["id"] for r in want["rounds"]], demo)
            self.assertEqual(exp.data["prompts"], want["prompts"], demo)

    def test_worked_example_writes_the_example_packet(self):
        files = json.loads(self.js("SD = sdFromExample(); JSON.stringify(sdOutput(SD).files)"))
        self.assertEqual(R.parse_yaml(files.pop("suites.yaml")), R.parse_yaml((PACKET / "suites.yaml").read_text()))
        want = files_of(PACKET, skip=("suites.yaml", "README.md"))
        self.assertEqual(sorted(files), sorted(want))
        for name, text in want.items():
            if name.endswith("expect.json"):
                self.assertEqual(json.loads(files[name]), json.loads(text), name)
            else:
                self.assertEqual(files[name], text, name)
        self.assertEqual(self.js("JSON.stringify(sdProblems(SD))"), "[]")

    def test_awkward_text_kept_exactly(self):
        awkward = {"title": 'He said "hi" \\ and """three""" quotes', "purpose": 'tab\there\nline with \\ a backslash, \u0001 and a last quote"',
                   "criterion": '""""', "judging_question": "Which is better? # not a comment"}
        self.js("ED = edFromStart('class'); Object.assign(ED, " + json.dumps(awkward) + "); ED.prompts[0].reference = 'ends with \"\\\\\"'; true")
        text = self.js("edOutput(ED).text")
        got = tomllib.loads(text)
        for k, v in awkward.items():
            self.assertEqual(got[k], v, k)
        self.assertEqual(got["prompt"][0]["reference"], 'ends with "\\"')
        self.assertEqual(json.loads(self.js("JSON.stringify(parseToml(edOutput(ED).text))"))["purpose"], awkward["purpose"])
        odd = {"what": 'Key: value # and "quotes", then\n# a line like a comment\n  indented\n---\n', "question": "a: b, c [d] {e} #f",
               "criterion": "x" * 30 + " " + "word " * 30 + "end", "scale1": "1: the lowest", "item": "007"}
        self.js("SD = sdFromExample(); const o = " + json.dumps(odd) + "; const s = SD.suites[0]; s.what = o.what; s.tests[0].question = o.question; s.tests[0].criterion = o.criterion;"
                " s.tests[2].scale['1'] = o.scale1; s.items[0].id = o.item; s.tests[0].check.text = ['a, b', '[x]', ' trailing ', 'q\"q']; true")
        d = R.parse_yaml(self.js("sdOutput(SD).text"))
        s = d["suites"][0]
        self.assertEqual(s["what"], odd["what"])
        self.assertEqual(s["tests"][0]["question"], odd["question"])
        self.assertEqual(s["tests"][0]["criterion"], odd["criterion"].strip())
        self.assertEqual(s["tests"][2]["scale"]["1"], odd["scale1"])
        self.assertEqual(str(s["items"][0]), "007")
        self.assertEqual(s["tests"][0]["check"]["text"], ["a, b", "[x]", " trailing ", 'q"q'])


def class_variants():
    text = (CLASS / "experiment.toml").read_text()
    files = files_of(CLASS, skip=("experiment.toml",))
    yield "as it is", text, files
    yield "a round's file missing", text, without(files, "rounds/B/.claude/identity/voice.md")
    yield "an unknown how", text.replace('how = "removed"', 'how = "deleted"'), files
    yield "an unknown part", text.replace('part = "knowledge-graph"', 'part = "the-graph"'), files
    yield "a Codex model for Claude Code", text.replace('model = "claude-sonnet-5-5"\nallowed', 'model = "gpt-6.1-sol"\nallowed'), files
    yield "no runner", text.replace('runner = "claude-code"', 'runner = "gemini"'), files
    yield "no checks", re.sub(r"\[\[checks\]\][\s\S]*?(?=\[judge\])", "", text), files
    yield "no comparisons", re.sub(r'\[\[comparisons\]\]\nbaseline = "A"\nnew = "[BCD]"\n+', "", text), files
    yield "a prompt on both lists", text.replace('held_out = ["ellis-board-note", "reply-to-school"]', 'held_out = ["ellis-board-note", "reply-to-sam"]'), files
    yield "a prompt with no text", text.replace('development = ["reply-to-priya"', 'development = ["no-such-prompt", "reply-to-priya"'), files
    yield "a starting file missing", text, without(files, "prompts/reply-to-sam/files/input/sam-message.md")
    yield "an odd role", text.replace('role = "control-should-not-change"', 'role = "control"'), files
    yield "no prediction", text.replace('expected = { direction = "same" }\n', ""), files
    yield "few prompts, no judge prompt", re.sub(r'prompt = """[\s\S]*?"""\n', "", text).replace('held_out = ["ellis-board-note", "reply-to-school"]', "held_out = []"), files
    yield "no schema, no title", text.replace('schema = "skill-eval-lite/experiment@1"\n', "").replace("title = ", "old_title = "), files
    yield "a round with no file", text.replace(', file = "rounds/D/.claude/identity/voice.md"', ""), files


@unittest.skipUnless(CHROME, "headless Chrome is not available")
class CheckMirror(Page):
    def test_experiment_check_says_what_run_ab_says(self):
        for i, (name, text, files) in enumerate(class_variants()):
            folder = self.root / "mirror" / str(i)
            write_tree(folder, dict(files, **{"experiment.toml": text}))
            errors, warns = R.Experiment(folder / "experiment.toml").problems()
            norm = lambda xs: [x.replace(str(folder), "BASE") for x in xs]
            got = json.loads(self.js(f"JSON.stringify(checkProblems(parseToml({json.dumps(text)}), {json.dumps(files)}, 'BASE'))"))
            self.assertEqual(got["errors"], norm(errors), name)
            self.assertEqual(got["warns"], norm(warns), name)

    def test_suite_check_says_what_run_ab_says(self):
        mutations = {
            "as it is": "",
            "a case with no files": "SD.suites[0].items.push({ uid: 'x', id: 'ghost', files: {} });",
            "an unknown object": "SD.suites[1].object = 'run';",
            "a prompt file missing": "SD.suites[0].tests[1].texts.prompt = null;",
            "a mechanical test with no check": "SD.suites[0].tests[0].check = null;",
            "an unknown check": "SD.suites[0].tests[0].check.kind = 'spell';",
            "an unknown kind": "SD.suites[1].tests[2].kind = 'robot';",
            "a control with an odd role": "SD.suites[0].controls[0].role = 'odd';",
            "too few controls and runs": "SD.suites[0].controls = SD.suites[0].controls.slice(0, 2); SD.suites[1].items = SD.suites[1].items.slice(0, 2);",
            "no human test": "SD.suites[1].tests = SD.suites[1].tests.slice(0, 2);",
        }
        for i, (name, code) in enumerate(mutations.items()):
            got = json.loads(self.js("(() => { SD = sdFromExample(); " + code + " const o = sdOutput(SD); const c = suiteCheck(SD, o.files);"
                                     " return JSON.stringify({ files: o.files, errors: c.errors.map(e => e.t), notes: c.notes.map(e => e.t) }); })()"))
            folder = self.root / "suites-mirror" / str(i)
            write_tree(folder, got["files"])
            S = R.Suites(folder / "suites.yaml")
            self.assertEqual(got["errors"], S.errors, name)
            self.assertEqual(got["notes"], [w for s in S.suites for w in s["warnings"]], name)


def own_assistant(root: Path) -> Path:
    """A small assistant of a student's own: CLAUDE.md importing two identity
    files, a voice file with three sections, a knowledge graph and two skills."""
    a = root / "sams-assistant"
    files = {
        "CLAUDE.md": "# Sam's assistant\n\nYou draft replies for Sam Lee (made up).\n\n@.claude/identity/voice.md\n@.claude/identity/soul.md\n\n"
                     "Search before you write about anyone: `kb/kb search <words>`.\n",
        ".claude/identity/voice.md": "# How Sam writes\n\nPlain and short.\n\n## Greetings\n\nStart with the person's first name.\n\n"
                                     "## Length\n\nKeep replies under 120 words.\n\n## Sign-off\n\nEnd with Sam, and nothing else.\n",
        ".claude/identity/soul.md": "# Who you are\n\nCalm and exact.\n",
        ".claude/skills/knowledge-graph/SKILL.md": "---\nname: knowledge-graph\ndescription: Look things up in kb/.\n---\n",
        ".claude/skills/greeter/SKILL.md": "---\nname: greeter\ndescription: Writes a greeting card.\n---\n# Greeter\n",
        "kb/kb.py": KB_PY,
        "kb/kb": '#!/bin/sh\nexec python3 "$(cd "$(dirname "$0")" && pwd)/kb.py" "$@"\n',
        "kb/wiki/Jo Park.md": "# Jo Park\n\nSam's neighbour. Lends the ladder.\n",
    }
    write_tree(a, files)
    os.chmod(a / "kb" / "kb", 0o755)
    git("init", "-q", "-b", "main", cwd=a)
    git("add", "-A", cwd=a)
    git("commit", "-q", "-m", "Sam's assistant", cwd=a)
    return a


@unittest.skipUnless(CHROME, "headless Chrome is not available")
class ExperimentJourneys(Page):
    def open_designer(self, start):
        self.js("document.getElementById('gs-open-designer').click(); true")
        self.assertTrue(self.js("!document.getElementById('designer').hidden"))
        self.js(f"__id('dz-start-{start}').click(); true")

    def test_a_class_start_changed_saved_checked_frozen(self):
        b = self.b
        self.open_designer("class")
        self.js("__set('dz-name', 'board-signoff')")
        self.js("__screen(3)")
        self.js("__id('dz-B-how-revise').click(); true")
        self.assertIn("# Morgan Reyes - Voice and Style Guide", self.js("__id('dz-B-text').value"), "the class experiment's round B file is in the editor")
        self.js("__set('dz-B-text', __id('dz-B-text').value + '\\n## Board memo sign-off\\n\\nEnd a board memo with Morgan alone.\\n')")
        self.js("__set('dz-B-label', 'Board memo sign-off written')")
        self.js("__screen(5)")
        for pid, where in (("reply-to-sam", "held"), ("prep-priya-call", "dev")):
            self.js(f"__id('dz-p-' + ED.prompts.find(p => p.id === '{pid}').uid + '-set-{where}').click(); true")
        self.js("__screen(6)")
        self.js("__id('dz-add-word-count').click(); true")
        n = self.js("ED.checks.length - 1")
        self.js(f"__set('dz-c-{n}-max', '400')")
        self.js("__screen(8)")
        self.assertIn("Nothing is missing.", self.js("__text()"))
        self.js("__id('dz-save-zip').click(); true")
        zpath = self.downloaded("board-signoff.zip")
        root = self.root / "a"
        copy = self.skill_eval_lite(root)
        files = self.unzip(zpath, copy / "experiments", "board-signoff")
        self.assertEqual(sorted(files), sorted(["experiment.toml", "rounds/B/.claude/identity/voice.md", "rounds/D/.claude/identity/voice.md",
                                                 *[f for f in files_of(CLASS) if f.startswith("prompts/")]]))
        self.assertIn("End a board memo with Morgan alone.", files["rounds/B/.claude/identity/voice.md"])
        r = self.sel(copy, "check", "experiments/board-signoff/experiment.toml")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Nothing is missing.", r.stdout)
        self.assertIn("Frozen: not yet", r.stdout)
        x = tomllib.loads(files["experiment.toml"])
        self.assertEqual(x["prompts"]["development"], ["reply-to-priya", "summarize-committee-notes", "prep-dana-checkin", "prep-priya-call"])
        self.assertEqual(x["prompts"]["held_out"], ["reply-to-sam", "ellis-board-note", "reply-to-school"])
        self.assertEqual(next(c for c in x["checks"] if c["kind"] == "word-count" and c.get("max") == 400)["object"], "product")
        self.assertEqual(x["rounds"][1]["label"], "Board memo sign-off written")
        # The same folder, saved through the folder picker (a stand-in for it here).
        self.js(MOCK_PICKER + "__picker('experiments', [])")
        self.js("__id('dz-save-folder').click(); true")
        b.until("ED.saved && ED.saved.how === 'folder'", timeout=20)
        saved = json.loads(self.js("JSON.stringify(__fs)"))
        self.assertEqual(saved, {"board-signoff/" + k: v for k, v in files.items()})
        self.assertIn("Saved in experiments/board-signoff/", self.js("__text()"))
        self.assertIn("run_ab.py check experiments/board-signoff/experiment.toml", self.js("__text()"))
        # Step 1 loads the saved file, and step 2 freezes it.
        self.js("__click('The wizard’s steps')")
        b.set_files("#intake-file", [copy / "experiments" / "board-signoff" / "experiment.toml"])
        b.until("document.querySelector('main').innerText.includes('Nothing is missing.')")
        self.js("document.querySelectorAll('#steps button')[1].click(); true")
        self.js("__click('Freeze')")
        b.until("document.querySelector('main').innerText.includes('The record')")
        self.js("__click('Export the frozen experiment')")
        frozen = self.downloaded("experiment.toml")
        shutil.copy(frozen, copy / "experiments" / "board-signoff" / "experiment.toml")
        r = self.sel(copy, "check", "experiments/board-signoff/experiment.toml")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Frozen: yes", r.stdout)

    def new_prompt(self, title, text, reference, tags, behavior, held=False):
        self.js("__id('dz-new-prompt').click(); true")
        self.js(f"__setIn('-title', {json.dumps(title)})")
        self.js(f"__setIn('-text', {json.dumps(text)})")
        self.js(f"__setIn('-ref', {json.dumps(reference)})")
        for t in tags:
            self.js(f"(() => {{ const e = __in('-newtag'); e.value = {json.dumps(t)}; e.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Enter', bubbles: true }})); return true; }})()")
        self.js(f"document.querySelector('.dz-item.open [id$=\"-b-greets-by-name-{behavior}\"]').click(); true")
        if held:
            self.js("document.querySelector('.dz-item.open [id$=\"-set-held\"]').click(); true")

    def test_d_a_long_file_stays_in_its_box(self):
        """Step 2: picking a folder and opening a part shows the start of its
        file; a long file with long lines scrolls inside its box, wrapped
        (Simon, 2026-10-26: the file's text overflowed on the real class
        assistant)."""
        b = self.b
        asst = own_assistant(self.root / "d")
        long_line = "Always draft, never send; " * 12
        (asst / "CLAUDE.md").write_text("# Sam's assistant\n\n" + "\n".join(f"{i}. {long_line}" for i in range(80))
                                       + "\n\n@.claude/identity/voice.md\n@.claude/identity/soul.md\n")
        self.open_designer("blank")
        self.js("__set('dz-name', 'long-file')")
        self.js("__screen(1)")
        b.set_files("#dz-asst-input", [asst])
        b.until("ED.system.parts.length >= 5", timeout=20)
        self.js("__id('dz-part-v-standing-rules').click(); true")
        b.until("document.querySelector('pre.dz-filetext') !== null", timeout=10)
        box = json.loads(self.js("""JSON.stringify((() => { const pre = document.querySelector('pre.dz-filetext'), box = pre.parentElement;
          const p = pre.getBoundingClientRect(), q = box.getBoundingClientRect(), cs = getComputedStyle(pre);
          return { inside: p.bottom <= q.bottom + 1 && p.right <= q.right + 1, scrolls: pre.scrollHeight > pre.clientHeight,
                   overflowY: cs.overflowY, wrap: cs.whiteSpace, wide: pre.scrollWidth <= pre.clientWidth + 1,
                   cut: pre.textContent.includes('the rest of the file is not shown') }; })())"""))
        self.assertTrue(box["inside"], box)
        self.assertTrue(box["scrolls"], box)
        self.assertIn(box["overflowY"], ("auto", "scroll"))
        self.assertEqual(box["wrap"], "pre-wrap")
        self.assertTrue(box["wide"], box)
        self.assertTrue(box["cut"], box)

    def test_b_blank_own_assistant_custom_prompt_and_starting_file(self):
        b = self.b
        root = self.root / "b"
        asst = own_assistant(root)
        (root / "invite.md").write_text("From: Jo Park\n\nBarbecue at ours on Saturday at 4? Bring nothing.\n")
        self.open_designer("blank")
        self.js("__set('dz-name', 'sam-voice')")
        self.js("__screen(1)")
        b.set_files("#dz-asst-input", [asst])
        b.until("ED.system.parts.length >= 5", timeout=20)
        parts = {p["id"]: p for p in json.loads(self.js("JSON.stringify(ED.system.parts)"))}
        self.assertEqual(sorted(parts), ["character", "knowledge-graph", "skill-greeter", "standing-rules", "voice"])
        self.assertEqual(parts["voice"]["reaches_model"], "imported by CLAUDE.md")
        self.assertEqual(parts["knowledge-graph"]["paths"], ["kb/", ".claude/skills/knowledge-graph/"])
        self.assertIn("It is a git project", self.js("__text()"))
        self.js("__set('dz-sys-name', 'Sam’s assistant (made up)')")
        self.js("__screen(2)")
        self.js("__set('dz-title', 'Does a greetings rule make Sam’s replies sendable?')")
        self.js("__set('dz-purpose', 'Replies that Sam sends to friends and neighbours.')")
        self.js("__set('dz-criterion', 'Sam would send it without changes: it answers what was asked, briefly, in Sam’s voice.')")
        self.js("__set('dz-jq', 'Which reply would Sam rather send as it is?')")
        self.js("__screen(3)")
        self.js("__id('dz-part-B-voice').click(); true")
        self.js("__id('dz-B-how-write').click(); true")
        self.assertIn("## Greetings", self.js("__id('dz-B-text').value"), "the editor starts from the folder's voice.md")
        self.js("__set('dz-B-text', __id('dz-B-text').value + '\\n## Invitations\\n\\nSay yes or no in the first line.\\n')")
        self.js("__screen(4)")
        self.js("__click('Remove the knowledge graph')")
        self.js("__click('Reorder a file’s sections')")
        self.assertIn("Not a word changed", self.js("__text()"))
        self.js("__screen(5)")
        self.js("__click('Add a behavior')")
        self.js("__set('dz-b-0-id', 'greets-by-name')")
        self.js("__set('dz-b-0-desc', 'Starts with the person’s first name; not in a note to Sam.')")
        self.new_prompt("Answer Jo about Saturday", "Jo's invitation is in input/invite.md. Yes, we're coming. Draft a reply. Save it in drafts/.",
                        "Jo,\n\nYes, we'd love to come on Saturday at 4.\n\nSam", ["reply", "neighbour"], "should")
        self.js("document.querySelector('.dz-item.open input[id$=\"-addfile\"]').id = 'dz-test-addfile'; true")
        b.set_files("#dz-test-addfile", [root / "invite.md"])
        b.until("ED.prompts.some(p => p.files.length && p.files[0].content)", timeout=10)
        self.new_prompt("Thank Ana for the plants", "Ana left plants on the step. Thank her. Save it in drafts/.", "Ana,\n\nThank you for the plants.\n\nSam", ["reply"], "should")
        self.new_prompt("Note to self about the bins", "Write me a note to put the bins out on Tuesday. Save it in notes/.", "Bins out on Tuesday.", ["note"], "should_not")
        self.new_prompt("Remind me about the dentist", "Write me a reminder of the dentist on Friday at 9. Save it in notes/.", "Dentist, Friday at 9.", ["note"], "should_not")
        self.new_prompt("Answer Lee about the ladder", "Lee wants the ladder back. Say I'll bring it tonight. Save it in drafts/.", "Lee,\n\nI'll bring the ladder back tonight.\n\nSam", ["reply"], "should", held=True)
        self.new_prompt("Note about the boiler", "Write me a note to call about the boiler. Save it in notes/.", "Call about the boiler.", ["note"], "should_not", held=True)
        self.js("__screen(6)")
        self.js("__id('dz-add-not-contains').click(); true")
        self.js("__set('dz-c-0-text', 'TODO\\nLorem')")
        self.js("__id('dz-add-trace-no-tool-outside').click(); true")
        self.js("__click('Write it from the template')")
        self.js("__screen(8)")
        text = self.js("__text()")
        self.assertIn("Nothing is missing.", text, text[:3000])
        self.js("__id('dz-save-zip').click(); true")
        copy = self.skill_eval_lite(root)
        files = self.unzip(self.downloaded("sam-voice.zip"), copy / "experiments", "sam-voice")
        x = tomllib.loads(files["experiment.toml"])
        pid = x["prompts"]["development"][0]
        self.assertEqual(files[f"prompts/{pid}/files/input/invite.md"], (root / "invite.md").read_text())
        self.assertIn("## Invitations", files["rounds/B/.claude/identity/voice.md"])
        d = files["rounds/D/.claude/identity/voice.md"]
        self.assertLess(d.index("## Sign-off"), d.index("## Greetings"), "D reorders the sections")
        self.assertEqual(sorted(l for l in d.splitlines() if l.strip()), sorted(l for l in (asst / ".claude/identity/voice.md").read_text().splitlines() if l.strip()))
        r = self.sel(copy, "check", "experiments/sam-voice/experiment.toml")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Nothing is missing.", r.stdout)
        os.chmod(FAKE, 0o755)
        r = self.sel(copy, "run", "experiments/sam-voice/experiment.toml", "--assistant", asst, "--claude", FAKE, "--jobs", "4", "--out", root / "runs")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        bundle = json.loads((root / "runs" / "bundle.json").read_text())
        self.assertEqual(len(bundle["outputs"]), 4 * 4 * 2)
        self.assertTrue(all(o["status"] == "ok" for o in bundle["outputs"]), [o["status"] for o in bundle["outputs"]])


@unittest.skipUnless(CHROME, "headless Chrome is not available")
class SuiteJourney(Page):
    def cases(self, folder: Path, n: int, process: bool) -> Path:
        for i in range(1, n + 1):
            c = folder / f"{'run' if process else 'reply'}-{i}"
            c.mkdir(parents=True)
            (c / "context.md").write_text(f"# What it was for\n\nA reply to neighbour {i}.\n")
            (c / "output.md").write_text(f"Hello neighbour {i},\n\nYes, Saturday works.\n\nSam\n")
            if process:
                steps = [{"tool": "Bash", "detail": f"kb/kb search neighbour {i}", "error": False, "result": "Neighbour page"},
                         {"tool": "Read", "detail": "kb/wiki/neighbour.md", "error": False}, {"tool": "Write", "detail": "drafts/reply.md", "error": False}]
                (c / "trace.jsonl").write_text("".join(json.dumps(s) + "\n" for s in steps))
        return folder

    def add_test(self, i, kind, tid, q, c):
        self.js(f"__id('sz-{i}-add-{kind}').click(); true")
        self.js(f"__setIn('-id', {json.dumps(tid)})")
        self.js(f"__setIn('-q', {json.dumps(q)})")
        self.js(f"__setIn('-c', {json.dumps(c)})")
        self.js("__setIn('-w', 'It suits this kind of question.')")

    def add_control(self, i, role, start, note, expect, edit=None):
        uid = self.js(f"SD.suites[{i}].uid")
        self.js(f"__set('sz-{uid}-from', {json.dumps(start)})")
        self.js(f"__id('sz-{uid}-add-{role}').click(); true")
        self.js(f"__setIn('-note', {json.dumps(note)})")
        for ti, want in enumerate(expect):
            if want:
                self.js(f"__setIn('-x{ti}', '{want}')")
        if edit:
            edit()

    def test_c_suites_from_blank(self):
        b = self.b
        root = self.root / "c"
        replies, runs = self.cases(root / "replies", 6, False), self.cases(root / "runs", 3, True)
        self.js("document.getElementById('gs-open-suite-designer').click(); true")
        self.js("__id('sz-start-blank').click(); true")
        self.js("__set('sz-packet', 'my-packet')")
        self.js("__set('sz-title', 'Sam’s replies and how they are made')")
        self.js("__screen(1)")
        self.js("__set('sz-0-id', 'replies')")
        self.js("__set('sz-0-what', 'Replies that Sam sends to neighbours.')")
        self.js("__set('sz-1-id', 'lookups')")
        self.js("__set('sz-1-what', 'Whether the assistant looks people up before it writes.')")
        self.js("__screen(2)")
        for i, folder, n in ((0, replies, 6), (1, runs, 3)):
            uid = self.js(f"SD.suites[{i}].uid")
            b.set_files(f"#sz-{uid}-dir", [folder])
            b.until(f"SD.suites[{i}].items.length === {n}", timeout=20)
        self.js("__screen(3)")
        self.add_test(0, "mechanical", "no-todo", "Does a TODO reach the reply?", "Passes when the reply has no TODO.")
        self.js("__setIn('-ct', 'TODO')")
        self.add_test(0, "llm", "reads-well", "Does the reply answer what was asked?", "Passes when it answers the invitation.")
        self.js("__click('Write it from the template', __open())")
        self.add_test(0, "human", "sendable", "Would Sam send it as it is?", "A rating of 3 or 4 passes.")
        for p, anchor in enumerate(["Rewrite it.", "Big edits.", "Small edits.", "Send it as it is."], start=1):
            self.js(f"__setIn('-s{p}', {json.dumps(anchor)})")
        self.add_test(1, "mechanical", "searched-first", "Did the run search before writing?", "Passes when a kb/kb search ran.")
        self.js("__setIn('-ck', 'trace-ran-command')")
        self.js("__setIn('-cp', 'kb/kb search*')")
        self.add_test(1, "llm", "steps-follow", "Does each step follow from the one before?", "Passes when the steps make sense in order.")
        self.js("__click('Write it from the template', __open())")
        self.add_test(1, "human", "trust", "Would you trust a reply made this way?", "A rating of 3 or 4 passes.")
        for p in range(1, 5):
            self.js(f"__setIn('-s{p}', 'Point {p}.')")
        self.js("__screen(4)")

        def plant(text):
            def edit():
                self.js("[...__open().querySelectorAll('.dz-row')].find(r => r.querySelector('code') && r.querySelector('code').textContent === 'output.md').querySelector('button').click(); true")
                self.js(f"__setIn('-f-output-md', {json.dumps(text)})")
            return edit

        def drop_search():
            self.js("[...__open().querySelectorAll('.dz-row')].find(r => r.querySelector('code') && r.querySelector('code').textContent === 'trace.jsonl').querySelector('button').click(); true")
            self.js("__open().querySelector('[aria-label=\"Delete step 1\"]').click(); true")

        self.add_control(0, "reference", "reply-1", "A good reply.", [])
        self.add_control(0, "fault", "reference", "A TODO left in.", ["fail", "pass", "fail"], plant("Hello,\n\nTODO: answer.\n\nSam\n"))
        self.add_control(0, "fault", "reference", "Answers the wrong question.", ["pass", "fail", "fail"], plant("Hello,\n\nThe bins go out on Tuesday.\n\nSam\n"))
        self.add_control(0, "variation", "reference", "The same reply, reworded.", [], plant("Hello neighbour 1,\n\nSaturday works, yes.\n\nSam\n"))
        self.add_control(0, "variation", "reference", "The same reply, with a blank line more.", [], plant("Hello neighbour 1,\n\n\nYes, Saturday works.\n\nSam\n"))
        self.add_control(1, "reference", "run-1", "A clean run.", [])
        self.add_control(1, "fault", "reference", "The search deleted.", ["fail", "fail", "fail"], drop_search)
        self.add_control(1, "fault", "reference", "Written before the lookups.", ["pass", "fail", "fail"])
        self.add_control(1, "variation", "reference", "The same run, another search word.", [])
        self.add_control(1, "variation", "reference", "The same run again.", [])
        self.js("__screen(5)")
        text = self.js("__text()")
        self.assertIn("Nothing to fix.", text, text[:3000])
        self.js("__id('sz-save-zip').click(); true")
        copy = self.skill_eval_lite(root)
        files = self.unzip(self.downloaded("my-packet.zip"), root, "my-packet")
        self.js(MOCK_PICKER + "__picker('workspace', ['skill-eval-lite'])")
        self.js("__id('sz-save-folder').click(); true")
        b.until("SD.saved && SD.saved.how === 'folder'", timeout=20)
        self.assertEqual(json.loads(self.js("JSON.stringify(__fs)")), {"my-packet/" + k: v for k, v in files.items()})
        self.assertIn("run_ab.py suite ../my-packet/suites.yaml --check", self.js("__text()"))
        self.assertIn("controls/lookups/fault/trace.jsonl", files)
        self.assertNotIn("kb/kb search", files["controls/lookups/fault/trace.jsonl"], "the planted fault has no search")
        self.assertIn("{{case}}", files["tests/reads-well/prompt.md"])
        r = self.sel(copy, "suite", "../my-packet/suites.yaml", "--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("2 suites (replies: 11 cases, 3 tests, lookups: 8 cases, 3 tests). Nothing to fix.", r.stdout)
        self.assertNotIn("note:", r.stdout)
        os.chmod(FAKE, 0o755)
        r = self.sel(copy, "suite", "../my-packet/suites.yaml", "--claude", FAKE)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        b.goto(WIZARD.as_uri())
        self.js(JS)
        self.js("set({ view: 'steps', step: 1 }); true")
        b.set_files("#bundle-file", [root / "my-packet" / "bundle.json"])
        b.until("S.mode === 'suites'")
        self.assertIn("replies", self.js("document.getElementById('stage').innerText"))


@unittest.skipUnless(CHROME, "headless Chrome is not available")
class Layout(Page):

    def test_fields_are_readable_in_dark_mode(self):
        """Every field on every designer screen has enough contrast in dark
        mode (Simon, 2026-10-26: the "How far is the same" box on Controls
        was too bright for its text)."""
        CONTRAST = r"""JSON.stringify((() => {
          const rgb = c => (c.match(/[\d.]+/g) || []).map(Number);
          const lum = ([r, g, b]) => { const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); }; return .2126 * f(r) + .7152 * f(g) + .0722 * f(b); };
          const bg = e => { for (let x = e; x; x = x.parentElement) { const c = rgb(getComputedStyle(x).backgroundColor); if (c.length >= 3 && (c.length < 4 || c[3] > .5)) return c; } return [255, 255, 255]; };
          const bad = [];
          document.querySelectorAll('#designer input:not([type=checkbox]):not([type=radio]):not([type=file]), #designer textarea, #designer select').forEach(e => {
            if (!e.getClientRects().length) return;
            const a = lum(rgb(getComputedStyle(e).color)), b = lum(bg(e)), r = (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
            if (r < 4.5) bad.push((e.id || e.tagName) + ' ' + r.toFixed(2));
          });
          return bad; })())"""
        for opener, start, screens in (("gs-open-designer", "dz-start-class", 9), ("gs-open-designer", "dz-start-blank", 9),
                                       ("gs-open-suite-designer", "sz-start-example", 6), ("gs-open-suite-designer", "sz-start-blank", 6)):
            self.js("localStorage.clear()"); self.b.goto(WIZARD.as_uri()); self.js(JS); self.js("S.theme = 'dark'; applyTheme(); true")
            self.js(f"document.getElementById('{opener}').click(); true")
            self.js(f"__id('{start}').click(); true")
            for n in range(screens):
                self.js(f"__screen({n})")
                self.assertEqual(json.loads(self.js(CONTRAST)), [], f"{start}, screen {n + 1}")
    def screens(self, kind, start, n):
        self.js(f"dzOpen('{kind}'); true")
        self.js(f"__id('{'dz' if kind == 'experiment' else 'sz'}-start-{start}').click(); true")
        for i in range(n):
            self.js(f"__screen({i})")
            yield i

    def test_phone_width_and_labels(self):
        self.b.send("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True}, session=True)
        for kind, start, n in (("experiment", "class", 9), ("suites", "example", 6)):
            for i in self.screens(kind, start, n):
                wide = self.js("document.documentElement.scrollWidth")
                self.assertLessEqual(wide, 390, f"{kind} screen {i + 1} scrolls sideways at 390 px")
                unlabelled = self.js("""[...document.querySelectorAll('#designer input, #designer textarea, #designer select')]
                  .filter(e => e.type !== 'file' && !(e.labels && e.labels.length) && !e.getAttribute('aria-label')).map(e => e.id || e.outerHTML.slice(0, 80))""")
                self.assertEqual(unlabelled, [], f"{kind} screen {i + 1}: fields without a label")

    def key(self, key, code, vk, text=None):
        down = {"type": "keyDown", "key": key, "code": code, "windowsVirtualKeyCode": vk}
        if text:
            down["text"] = text
        self.b.send("Input.dispatchKeyEvent", down, session=True)
        self.b.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": key, "code": code, "windowsVirtualKeyCode": vk}, session=True)

    def test_keyboard(self):
        self.js("dzOpen('experiment'); true")
        self.js("__id('dz-start-class').focus(); true")
        self.key("Enter", "Enter", 13, "\r")
        self.b.until("ED && ED.start === 'class'")
        self.js("__id('dz-name').focus(); __id('dz-name').select(); true")
        self.b.send("Input.insertText", {"text": "by-keyboard"}, session=True)
        self.key("Tab", "Tab", 9)
        time.sleep(0.3)
        self.assertEqual(self.js("ED.name"), "by-keyboard")
        self.assertNotIn(self.js("document.activeElement.tagName"), ("BODY",), "Tab moves on, and the focus is not lost")
        self.assertNotEqual(self.js("document.activeElement.id"), "dz-name", "Tab leaves the field")
        self.js("__screen(3); true")
        self.assertEqual(self.js("document.activeElement.id"), "dz-heading", "a new screen starts at its heading")
        self.js("__id('dz-part-B-character').focus(); true")
        self.key(" ", "Space", 32, " ")
        self.b.until("ED.rounds.B.part === 'character'")
        self.assertEqual(self.js("document.activeElement.id"), "dz-part-B-character", "the focus stays on the part")

    def test_from_getting_started_and_step_1(self):
        self.assertTrue(self.js("!!document.getElementById('gs-make')"), "Getting started offers the designers")
        self.js("document.querySelectorAll('.gs-path')[2].click(); true")
        self.js("document.querySelector('#gs-make button + button').click(); true")
        self.assertTrue(self.js("S.path === 'group' && S.gs.write === 'intake'"))
        self.assertIn("/experiment-intake", self.js("document.getElementById('start').innerText"))
        self.js("__click('With the designer, on screen')")
        steps = self.js("[...document.querySelectorAll('ol.gs-steps > li h3')].map(h => h.textContent)")
        self.assertIn("2. Open the experiment designer.", steps)
        self.assertNotIn("Start the intake.", " ".join(steps))
        cmds = self.js("[...document.querySelectorAll('ol.gs-steps .gs-cmd code')].map(c => c.textContent)")
        self.assertIn("unzip -o ~/Downloads/<name>.zip -d experiments", cmds)
        self.js("set({ view: 'steps', step: 1 }); true")
        self.js("__id('step1-designer').click(); true")
        self.assertTrue(self.js("S.view === 'design' && S.designer === 'experiment'"))


if __name__ == "__main__":
    unittest.main()

Skill Eval Lite 0.1.0 is published as a public repository,
https://github.com/vanderbilt-ms-ai/skill-eval-lite, released 27 October
2026 as one commit squashed from the course's private development
history.

## What the release contains

| Path | What it is |
| --- | --- |
| `README.md` | What it is, the walkthrough, the experiment file, the run folder, the commands, what was tested, the limits |
| `SAFETY.md` | The isolation flags, what each excludes, and what was verified |
| `VERSION` | The version, in one place (`run_ab.py` reads it; a test checks `wizard.html`'s copy) |
| `run_ab.py` | The runner: `setup`, `doctor`, `check`, `plan`, `run`, `judge`, and for Personal I `suite` (Python 3.11+, standard library), with Claude Code or Codex (`--runner codex`); `status`, `ask` and `new` for students who are stuck |
| `HELPER.md`, `.claude/skills/skill-eval-helper/SKILL.md` | The helper's instructions, which `ask` gives Claude Code or Codex (the same text twice) |
| `wizard.html` | The wizard: one offline page, with the class intake and a made-up practice pack embedded; Shared I's five steps, and Personal I's checks-only mode (four steps) when a suite bundle is loaded; and two designers that make the files on screen: the experiment designer (nine screens, saving `experiments/<name>/`) and the suite designer (six screens, saving a packet), each into a folder the student picks or as a ZIP |
| `dev/embed_examples.py` | Writes the designers' starting points into `wizard.html`: the class experiment's round and starting files, the four demonstrations, and the worked example of Personal I (`--check` says whether they are up to date) |
| `.claude/skills/experiment-intake/SKILL.md`, `AGENTS.md` | The intake instructions, for Claude Code and for Codex |
| `class-assistant/overlay/` | What `setup` lays over the AI 5100 template: `overlay.toml` (the pinned commit and the copies) and 26 knowledge-graph pages |
| `examples/class-assistant/` | The class intake: `experiment.toml`, round files B and D, starting files |
| `examples/demo-*.toml` | The four demonstrations (`demo-one-line` added 2026-10-27 for the live session) |
| `examples/personal-suites/` | Personal I's worked example: two suites (a product, six real drafts; a process, four real runs), each with a reference, two planted faults, two harmless variations and three tests |
| `examples/recorded/` | Real runs of the four demonstrations, with the judge (`demo-one-line` made 2026-10-27), and of the worked example's suites, with eight real LLM test runs (made 2026-10-26); and a real Codex run of the first demonstration, with its judge (`demo-graph-removed-codex/`) |
| `tests/` | The tests, with stand-ins for `claude` and `codex` and a small Chrome DevTools client |
| `dev/fresh-trial.sh` | The pre-release check below (not in the student walkthrough) |
| `starting.html`, `tutorial/` | The guided tour for new students: 22 stops in six chapters, with the class assistant as its worked example, built from the recorded runs (`tutorial/build.py`, `tutorial/excerpts.json`) |
| `docs/diagrams/`, `dev/diagrams.mjs` | The Getting started pictures as standalone SVGs (light and dark), for the README and other pages; `dev/diagrams.mjs` writes them, and the README's step lists, from the drawing code in `wizard.html` (`--check` says whether they are up to date) |

## What was verified

- `python3 -m unittest`: all 98 tests pass, on Python 3.14 and 3.11 (the
  pipeline offline with the fake `claude`; the wizard's TOML reader against
  `tomllib`; the wizard in headless Chrome on a runner's bundle, the five
  recorded demonstrations and the practice pack, with no console errors and
  its bootstrap matching Python; fast judging; the intake skill and
  `AGENTS.md` in step; the privacy scan of every file).
- The real runs: three of the demonstrations, 12 Claude Code runs and 6
  judgments with `claude-sonnet-5-5` on Claude Code 2.1.310, logged in to a
  Claude plan (README, "Tested"); `demo-one-line` (2026-10-27), 6 runs and
  3 judgments on Claude Code 2.1.311 with an API key, in four fresh trials;
  and 8 real LLM test runs of the worked
  suites, which found two flawed control cases in the example (kept, and
  explained in `examples/personal-suites/README.md`).
- The checks-only mode: `tests/test_suites.py` (the YAML reader; `suite`
  with the fake `claude`; rows only added; versions; a missed control
  marked; agreement counts; every LLM run kept) and the Chrome journeys in
  `tests/test_wizard.py` (reference judgments, ratings, a comparison with
  its side recorded, and reports that match `run_ab.py`'s line for line).
- The designers (`tests/test_designer.py`, 13 tests, in headless Chrome):
  the class start, the demonstrations and the worked example written out
  unchanged match `examples/`; the designers' copies of `check` and `suite
  --check` agree with `run_ab.py` word for word on broken files; three
  journeys by the page's own controls (the class start changed; blank, with
  an assistant's folder, a new prompt and a starting file; a packet from
  blank), each saved as a ZIP and through a stand-in folder picker, which
  pass `check` (and 32 runs with the fake `claude`) or `suite --check` and
  `suite`; the saved experiment loads in step 1 and freezes; every screen
  fits 390 px, every field has a label, and Enter, Tab and Space work as they should. Not yet tried by a student, or
  with the real folder picker (Chrome's dialog can't be driven headless).
- Codex (`tests/test_codex.py`, 24 tests, with the stand-in `codex`): runs,
  the judge, a suite's LLM tests and `doctor`; only the runner's config and
  a link to the login reach Codex, no API key unless asked; a global
  `AGENTS.md`, a personal skill, an MCP tool or an MCP call stops a run;
  runners never mixed in one folder. For real, on Codex 0.164.0 with a
  ChatGPT plan: `doctor --runner codex`, the first demonstration (4 runs)
  and its judge (2 pairs) with `gpt-6.1-sol`, and isolation against a test
  Codex folder with a canary of each kind (SAFETY.md, "Codex"). The intake
  was checked with Codex as a dry run only: Codex started in this folder
  loads `AGENTS.md` (rendered with `codex debug prompt-input`, no model
  called).
- `status`, `ask` and `new` (`tests/test_status.py`, 10 tests): the next
  step at each stage, `new` from the class experiment and from a
  demonstration, and the command `ask` builds for each tool (no launch).
  For real, with the API keys unset: `ask` opened Claude Code 2.1.311 and
  Codex 0.164.0 in a terminal; each greeted the student, said where they
  were and asked its first question, explained the setup check before
  running it, and asked for approval before running it (Claude Code in
  `manual` permission mode; Codex with its approval prompt, declined). One
  question with `ask "..."` was answered by each (15 s and 32 s).
- Isolation: with and without the flags, on an account with claude.ai
  connectors, a user MCP server, plugins and personal skills (SAFETY.md,
  "What was verified"); the check on every run's first event; `doctor`'s
  probe.
- `setup` from GitHub (the template at `3ed9049`), and the knowledge graph
  builds.
- Nothing personal in any file (`tests/test_privacy.py`): no home-folder
  paths, user or host names, real e-mail addresses, session or account IDs,
  account usage, key-like strings, or paths of the course's private
  repository. The recorded runs were made with the runner's redaction and
  checked by the same scan.

## The pre-release check: `dev/fresh-trial.sh`

Run it on a computer with your usual Claude Code, several times:

    dev/fresh-trial.sh

It makes `~/skill-eval-lite-trials/trial-<date-time>/` with a fresh home
folder, installs Claude Code there with the official installer (it needs the
network), points the README's clone URL at this repository's `origin`
remote (only pushed commits are cloned), and opens a shell, marked
`[skill-eval-lite trial]`, with the walkthrough's steps on screen. Your own
`~/.claude` and Claude Code install are not touched, and `ANTHROPIC_API_KEY`
is dropped unless you add `--keep-api-key`, so the first step is the login a
student sees. `dev/fresh-trial.sh --list` lists the trials and `--clean`
removes them.

It was run here with `--no-shell` on 2026-10-26: the official installer put
Claude Code 2.1.310 in the trial's home, the README's clone command cloned
this repository from the private remote through the rewritten URL, `setup`
cloned the template from GitHub, and `doctor` and `run` stopped at the
login, as below. On 2026-10-27 it was run four times with `--keep-api-key`
(Claude Code 2.1.311, the API key instead of a login), and the walkthrough
followed with `demo-one-line` (the last of them on to the wizard's exports,
in headless Chrome): about 30 s of machine time a trial (clone 1 s, `doctor`
2 to 3 s, `setup` 1 s, the runs 16 s, the judge 6 to 7 s), $0.31 to $0.34 a
trial. The login itself, on a
Claude plan, is for Simon to try.

What a fresh install does, as far as could be tested without logging in:
`claude auth status` reports `"loggedIn": false`; `claude -p` in a new
folder answers "Not logged in · Please run /login" (print mode skips the
trust and onboarding prompts); `run_ab.py doctor`, `run` and `judge` detect
this and say: run `claude`, log in, type `/exit`, and try again.

## Known limits

- Tested on Linux only.
- Codex: a run reads the assistant through an `AGENTS.md` written from
  `CLAUDE.md` with its imports inlined, and its skills copied to
  `.agents/skills/`, so Codex results are not comparable with Claude Code's
  (the runner keeps them in separate folders). Verified on Codex 0.164.0;
  only one demonstration was run for real; `--use-api-key` and the suites'
  LLM tests on Codex were tested with the stand-in only. The GPT-6 models
  are offered subagent tools that can't be switched off (same isolation).
- The isolation flags were verified on Claude Code 2.1.310. A later version
  is checked on every run (a run that loads anything personal stops).
- The wizard keeps its state in the browser's storage, per browser.
- The checks-only mode's human tests are collected in the browser, one
  rater per browser; agreement needs the second rater's exported
  `judgments.csv` imported.

## Open decisions

1. **License.** Not added; it is Simon's decision. Facts that bear on it:
   - The AI 5100 assistant template is CC BY-NC-SA 4.0. It is cloned from
     GitHub when `setup` runs, not copied into this repository.
   - This repository holds material adapted from the template's fictional
     example: the 26 knowledge-graph pages in `class-assistant/overlay/`
     (course-authored, about the example's people), the round files
     `examples/class-assistant/rounds/B`, `D` and `one-line` (the example's
     `voice.md`, with a section written, reordered, or one line added),
     their copies in `examples/recorded/*/versions/`, and the short excerpts
     of the template's files that `starting.html` quotes
     (`tutorial/excerpts.json`). ShareAlike would apply to those if they are
     adaptations: CC BY-NC-SA 4.0 with attribution to the template.
   - The code (`run_ab.py`, `wizard.html`, `tests/`, `dev/`) can take any
     license; a software license (for example MIT) suits it better than a
     Creative Commons one.
2. **Owner and visibility.** Decided: `vanderbilt-ms-ai`, public.
3. **The intake for Codex groups.** `AGENTS.md` and the intake skill tell
   the agent to write `runner = "claude-code"`. A group on Codex can run
   that file with `--runner codex` (a Claude model name is replaced by
   Codex's default), but the intake could ask which runner the group uses
   and write `runner = "codex"` with a Codex model. Those files belong to
   the onboarding work, so they were not changed here.
4. **The course's briefs.** The Shared I brief says to put the intake
   instructions "in the assistant's folder"; Skill Eval Lite runs them from
   its own folder beside the assistant (and leaves them out of every run if
   they are copied in). The brief could say "beside".

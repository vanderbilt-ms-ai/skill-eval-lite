Skill Eval Lite is published as a public repository,
https://github.com/vanderbilt-ms-ai/skill-eval-lite. Version 0.1.0 was
released on 27 October 2026, and version 0.1.1 on 3 November 2026. Each
release is one commit on the public `main`, made from the course's private
development history and tagged `v0.1.0` and `v0.1.1`.

## 0.1.1, 3 November 2026

Nine fixes to how Skill Eval Lite reads and checks a process, freezes an
experiment and reads a verdict, from the course's proposal of 3 November
(revision 2), and a version check.

### If you are on 0.1.0

1. In your `skill-eval-lite` folder, type `git pull`. Your `experiments/`
   and `runs/` folders are yours, not part of the repository, and are left
   as they are.
2. Shared I: if your group copied the class experiment (`new <name> --from
   class`) before 0.1.1, its `stayed-in-bounds` check has the old list,
   which fails nearly every run. Before you freeze, copy the new `allowed`
   list from `examples/class-assistant/experiment.toml` into your file.
3. Shared I: `run` now runs only a frozen experiment. A file frozen with
   0.1.0 still counts as frozen, with a note that its fingerprint can't be
   checked. If you change it, freeze it again, and keep the earlier file,
   dated.
4. Personal I: run `python3 run_ab.py suite <your packet>/suites.yaml
   --check` again. It now says more about each process case's record. If
   an LLM test's verdict was "unknown" because its last line was
   `Verdict: PASS`, the next `suite` reads it again, with no new run.

### What changed

| # | In 0.1.0 | In 0.1.1 |
| --- | --- | --- |
| 1 | A process case's record under any name but `transcript.jsonl` or `trace.jsonl` was silently ignored. `suite --check` said "Nothing to fix", the trace tests said n/a, and the example's program said fail | `suite --check` says it is a "must fix" when a case has no record, a record under another name (it names the file), or a line that isn't JSON (with its number). It says the same of a `trace.jsonl` whose lines have no `"tool"` (a session saved under the wrong name). It notes a record with no steps, and a suites file without both a product or stage suite and a process suite. The suite designer says the same, word for word. A built-in trace test's n/a names the folder |
| 2 | A case with both record files was read two ways: `transcript.jsonl` by the built-in checks, `trace.jsonl` by the example's `check.py` | `suite --check` and the designer refuse such a case. `check.py` reads in `read_trace`'s order, `transcript.jsonl` first. The README says so |
| 3 | An LLM test whose last line was `Verdict: PASS` or `Final answer: FAIL` was scored unknown | One rule for the suites' LLM tests and the judge (`last_line_word`). It reads the exact word, a labelled word, or the one word in the line with no `not` before it. Otherwise it is unknown, and the run record (`decision_note`) and the row's reason say why. A stored unknown run that the rule now reads as pass or fail gets one new row ("re-read with 0.1.1's rule; no new run"), and the report marks it "(re-read)". A skill-based test now asks for "one line that says only PASS, FAIL or UNKNOWN" |
| 4 | `run` printed a note and ran an unfrozen experiment | `run` refuses unless the experiment is frozen and unchanged, or is a demonstration. Held-out runs are refused too. `--unfrozen` runs it anyway, and marks each run, its `run.json` and the bundle `"frozen": false`. The wizard's steps 3 to 5 then say "These runs were made before the experiment was frozen" |
| 5 | `trace-ran-command` matched only the whole command as written: `./kb/kb search Dana` was not a search | A pattern also matches the command with a leading `./`, the directories before its own program, `NAME=value` settings, or `command`, `exec` or `time` taken off. A pattern ending in ` *` also matches the bare command (`ls *` matches `ls`). A match inside a chain says so: "(in a chain: the step's success is its last command's)" |
| 6 | `stayed-in-bounds` failed every recorded run, in every round, and counted steps Claude Code refused | Refused steps are marked `"refused": true`: in a run, a result beginning "Permission for this tool use was denied"; in a saved interactive session, a step the person rejected ("The user doesn't want to proceed with this tool use"). They are not counted, and are listed in the reason. A command that writes a file through `>` or `>>` is allowed only by a pattern with `>`. The class experiment's list, and the three demonstrations', adds `ls`, `cat`, `head`, `find`, `rg`, `wc`, `git log` and `git status` (not `echo` or `printf`) |
| 7 | Nothing compared the freeze's fingerprint with the file, and the fingerprint couldn't be rebuilt from the frozen file | The fingerprint is `sha256c:` and the SHA-256 of the file without its `[frozen]` table (for JSON, without `frozen`, keys sorted). The wizard and the runner compute it the same way, and the wizard's own SHA-256 needs no secure context. `check` says "must fix" when the file has changed since it was frozen, and so do `status`, `run` and the wizard's step 2. A 0.1.0 fingerprint (`sha256:` and 64 hex digits, or `fnv1a:` and 8) is read as frozen, with a note; any other hash is not a freeze. The wizard's export finds the `[frozen]` table as the fingerprint does |
| 8 | The example's program test said **fail** on a case with no record | It says `n/a no transcript.jsonl or trace.jsonl in <folder>/`. `suite` reads a program's `n/a` as n/a, with its reason. The READMEs say a program prints `n/a` when it can't test a case |
| 9 | Commands were split at every `;`, `\|`, `&&` and new line, quoted or not | Split outside quotes (`$'...'` included), escapes, `$(...)`, backticks and heredoc bodies, and at a lone `&` too. The commands in a `( ... )` or `{ ...; }` group are checked one by one. `>& file` counts as a write. A command inside `$(...)` is not checked on its own (a limit, in the README) |
| | | `doctor` and `status` say "Skill Eval Lite 0.1.2 is out; you have 0.1.1. In this folder, run git pull." when the public repository's `VERSION` is newer (one HTTPS request; offline, nothing) |

The shell splitter, the command matching, both trace checks and the
fingerprint are in `run_ab.py` and `wizard.html`, as before. They are held
to one set of answers in `tests/fixtures/shell.json` and
`tests/fixtures/fingerprints.json` (`tests/test_shared.py`). The guided
tour's builder now uses `run_ab.py`'s checks instead of a third copy.

### Recorded verdicts, before and after

Every process check was rerun on every recorded run, with no new model
calls. Where a run's own experiment has the check, it keeps that file's
0.1.0 list, as it was recorded. Those verdicts, the ones the wizard and the
tour show for `examples/recorded/`, are the same as in 0.1.0. Only their
reasons are more exact: the command outside the list, rather than the whole
step, and the chain note. The worked example's `search-before-write` gives
the same nine results.

The class experiment's checks, with 0.1.1's list, on every recorded Shared I
run (`searched-the-graph` only where the run's prompt is tagged `in-graph`):

| Recorded run | `searched-the-graph` | `stayed-in-bounds`, 0.1.0 | `stayed-in-bounds`, 0.1.1 | 0.1.1's reason |
| --- | --- | --- | --- | --- |
| demo-board-memo ellis-board-note/A/1 | pass | fail | pass | every step that ran was on the list; 1 refused |
| demo-board-memo ellis-board-note/B/1 | pass | fail | pass | every step that ran was on the list; 1 refused |
| demo-board-memo summarize-committee-notes/A/1 | - | fail | pass | every step that ran was on the list; 1 refused |
| demo-board-memo summarize-committee-notes/B/1 | - | fail | pass | every step that ran was on the list; 1 refused |
| demo-graph-removed prep-dana-checkin/A/1 | pass | fail | fail | outside the list: Bash echo --- |
| demo-graph-removed prep-dana-checkin/C/1 | pass | fail | fail | outside the list: Bash cd . |
| demo-graph-removed prep-priya-call/A/1 | pass | fail | fail | outside the list: Bash cd kb/wiki |
| demo-graph-removed prep-priya-call/C/1 | pass | fail | pass | every step that ran was on the list; 2 refused |
| demo-graph-removed-codex prep-dana-checkin/A/1 | pass | fail | fail | outside the list: Bash mkdir -p notes |
| demo-graph-removed-codex prep-dana-checkin/C/1 | fail | fail | fail | outside the list: Bash pwd |
| demo-graph-removed-codex prep-priya-call/A/1 | pass | fail | fail | outside the list: Bash pwd |
| demo-graph-removed-codex prep-priya-call/C/1 | pass | fail | fail | outside the list: Bash pwd |
| demo-one-line reply-to-priya/A/1 | - | fail | pass | every step that ran was on the list; 1 refused |
| demo-one-line reply-to-priya/B/1 | - | fail | pass | every step that ran was on the list; 1 refused |
| demo-one-line reply-to-sam/A/1 | - | fail | pass | every step on the list |
| demo-one-line reply-to-sam/B/1 | - | fail | fail | outside the list: Bash mkdir -p drafts |
| demo-one-line reply-to-school/A/1 | - | fail | pass | every step that ran was on the list; 1 refused |
| demo-one-line reply-to-school/B/1 | - | fail | pass | every step that ran was on the list; 1 refused |
| demo-voice-reordered reply-to-priya/A/1 | pass | fail | pass | every step on the list |
| demo-voice-reordered reply-to-priya/D/1 | pass | fail | pass | every step on the list |
| demo-voice-reordered summarize-committee-notes/A/1 | - | fail | pass | every step that ran was on the list; 1 refused |
| demo-voice-reordered summarize-committee-notes/D/1 | - | fail | pass | every step that ran was on the list; 1 refused |

So `stayed-in-bounds` now moves. With 0.1.1's list it passes 14 of the 22
runs, against none before. The demonstrations' rounds A and B, and A and D,
pass alike, as they should. What still fails is a command that only prints
or moves (`echo ---`, `cd`, `pwd`), which the list leaves out, or a
directory made through the shell (`mkdir`). In `demo-one-line`
`reply-to-sam/B/1`, that `mkdir` came before a draft written with `printf …
> drafts/…`, which the check is meant to catch. The four 0.1.0 failures of
`demo-graph-removed` stay in the tour, as recorded, as the lesson: a check
whose list didn't match what the system may do, caught because it failed
the round that should have passed (`starting.html`, "A check that didn't
move").

### What was verified for 0.1.1

- `python3 -m unittest`: all 125 tests pass, on Python 3.14 and 3.11. The 27
  new ones:
  - `tests/test_shared.py`: both copies against the fixtures. That covers
    36 shell steps (chains, quoted pipes and semicolons, an escaped pipe,
    heredocs, command substitutions, groups), 19 pattern matches (the four
    forms in fix 5, `cd sub && ./kb/kb node X`, `echo "kb/kb search"`), 36
    trace check results (`echo x > notes.md` fails) and 13 fingerprints. The wizard runs in headless Chrome.
  - `tests/test_freeze.py`: `check`, `status` and `run` on frozen, changed,
    0.1.0 and unfrozen files, `--unfrozen` and its marks in the bundle and
    the wizard, the wizard's step 2 on a changed file, and the version
    check, read from a file.
  - `tests/test_suites.py`: the record states through `suite --check`, the
    example's `check.py` against `read_trace` on every case, the last-line
    tables for verdicts and decisions, every recorded verdict read the same
    as before, the refusals marked in the four recorded graph-removed runs
    and the worked example, and a stored unknown re-read once and not again.
  - `tests/test_designer.py`: the designer's copy of `suite --check` agrees
    word for word with `run_ab.py` on thirteen more broken packets.
  - `tests/test_onboarding.py` and `tests/test_wizard.py`: a file frozen in
    the wizard and exported verifies in `check`.
- `dev/embed_examples.py --check`, `node dev/diagrams.mjs --check` and
  `tutorial/build.py --check`: all up to date.
- The wizard's SHA-256 against Node's on six strings, ASCII to emoji.
- An independent review (a separate Claude session, reading the diff). It
  ran about 100,000 random inputs through both copies of the splitter, the
  matching and the checks, and froze and re-read files the wizard's way.
  It found ten problems, all fixed above with tests: a rejected step in an
  interactive session, made-up hashes, a session saved as `trace.jsonl`,
  re-reading again when a folder's name has "(", a traceback on odd
  records, the export's `[frozen]` table, the folder loader's marks,
  emoji in reasons, three shell forms, and a verdict in a code fence.
- One `dev/fresh-trial.sh --no-shell --keep-api-key` (2026-11-03), cloned
  from the 0.1.1 commit. It used Claude Code 2.1.317 from the official
  installer, in a fresh home, with an API key. Then the walkthrough as
  typed:
  - `doctor` passed. Its probe took 1.9 s and $0.0004, and its version
    check reached GitHub and said nothing, since GitHub still had 0.1.0.
  - `setup` worked.
  - `run` refused the class experiment, unfrozen, with the message above.
  - `demo-one-line` ran 6 of 6 in 15 s ($0.30), and the judge its 3 pairs
    ($0.03).
  - Every refused `mkdir -p drafts && cat > … <<'EOF'` was marked
    `refused` in the bundle and in `trace.jsonl`, and the wizard showed it
    so.
  - The class experiment was frozen in the wizard (headless Chrome) and
    exported. Then `check` said `Frozen: yes`, `status` said "frozen, ready
    to run", and one real run of it worked ($0.05).

### Decided for 0.1.1

- **Fix 4: `run` refuses unfrozen runs**, as the Shared I brief says
  ("frozen before you look at any output"). If the brief's freezing rule is
  relaxed, the refusal could become a note again; `--unfrozen` already lets
  a group run first, with the runs marked.
- **Fix 6: the recommended option.** Count only the steps that ran, and
  widen the class list with the proposal's eight read-only commands.
  `echo` and `printf` stay off the list.

### Open, for Simon

- `echo`, `cd` and `pwd` are off the class list, so `demo-graph-removed`'s
  two round A runs still fail `stayed-in-bounds` (`echo ---`, `cd kb/wiki`).
  With the redirection rule, `Bash echo *` would allow only an `echo` that
  writes no file. Adding `Bash echo *`, `Bash cd *` and `Bash pwd` would
  pass all four graph-removed Claude Code runs. It would not pass the four
  Codex runs, which still fail on Codex's own MCP resource tools
  (`ListMcpResources`, `ListMcpResourceTemplates`) or a `mkdir`. Nor would
  it pass `demo-one-line`'s `reply-to-sam/B/1`, which fails on a `mkdir`
  before a draft written through the shell.
- Not in 0.1.1, as the proposal says: giving program tests the normalised
  steps (`SKILL_EVAL_STEPS`); the course's project pages, packs and
  announcement.

## What the release contains

As of 0.1.1 (the files 0.1.1 added: `tests/test_shared.py`, `tests/test_freeze.py` and `tests/fixtures/`).

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

## What was verified for 0.1.0

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
- The trace checks don't look inside `$(...)` or backticks, and refused
  steps are marked in Claude Code's records only, not yet in Codex's.
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

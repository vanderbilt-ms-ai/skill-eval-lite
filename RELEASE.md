Skill Eval Lite is published as a public repository,
https://github.com/vanderbilt-ms-ai/skill-eval-lite. Version 0.1.0 was
released on 27 October 2026, versions 0.1.1, 0.1.2 and 0.1.3 on
3 November 2026, version 0.1.4 on 4 November 2026 and version 0.2.0 on
7 November 2026. Each release is one commit on the public `main`, made from
the course's private development history and tagged (`v0.1.0` to
`v0.2.0`).

## 0.2.0, 7 November 2026

Doing it all in Claude. Students open this folder in the Claude desktop
app's Code tab and type messages, never commands. Fifteen skills take them
through Shared I and Personal I, from getting the computer ready to the ZIP
they submit. Claude runs every command (Simon, 7 November: "I think we
should focus wholly on doing all of the work through Claude, not through
the terminal"; "I'd also like to author skills in Skill Eval Lite to help
students do their entire Personal I and Shared I projects"; "add skills to
check whether the Shared I and Personal I folders are up to date (and that
skill-eval-lite is up to date) ... so if we push further changes, students
can pull them in and keep running"). Cowork can't
run the runner. Since 6 October 2026 its tasks run their code in a sandbox
on Anthropic's computers; the runner has to start `claude` on the
student's own.

### If you are on 0.1.4 or earlier

1. Open your `skill-eval-lite` folder in the desktop app's Code tab and ask
   Claude: "Please update Skill Eval Lite to the newest version without
   losing any of my work." (In a terminal: `git pull` in this folder.)
2. Then type `/get-ready`. Your experiments, runs and packets carry over as
   they are. From now on `/check-updates` brings in each new version.

### What changed

| # | Before | In 0.2.0 |
| --- | --- | --- |
| 1 | Three skills: the intake, the helper and check-authoring | Fifteen. New: `get-ready` (Python, git, the `claude` command and its login, `doctor`, the class assistant, Claude's reach over the workspace), `wizard` (opens it, says what to click, brings the exports back from Downloads), `critique` (a design of tests against the brief and rubric), `packet` (the submission folder and its ZIP), `shared-i` and `personal-i` (each project's guide, keeping `progress.md` and `ai-use-log.md` in its brief folder), `run-experiment`, `read-results` (the results, failures traced to a part, the next round, the held-out prompts), `suites-intake`, `control-cases`, `llm-test` and `run-suites` |
| 2 | The intake told students to type `setup` in a terminal and to type `/exit`, `check` and the move of the frozen file | The intake (version 4, `AGENTS.md` too) runs `setup` after a yes and hands over to `/critique`, `/wizard` and `/run-experiment`; the student types nothing |
| 3 | The helper offered to run each command, or to let the student type it | The helper (version 4, `HELPER.md` too) runs every command and names the skill for each step; check-authoring (version 2, `CHECKS.md` too) also writes Personal I's mechanical tests |
| 4 | The runner left three of Skill Eval Lite's skills out of a run, by their folder names | It leaves out every skill whose `SKILL.md` carries Skill Eval Lite's mark (`<!-- skill-eval-lite <name>, version N ... -->`), under any folder name, as well as the three by name; an assistant's own skills stay |
| 5 | The README's "Doing it all in Claude Code" | "Doing it all in Claude": where to open the folder, why not Cowork and a table of every skill; pointed to from the top and from "Getting started" |
| 6 | `status` gave Personal I's first run as every mechanical and LLM test together | `status` gives the mechanical tests first (`suite --no-llm`), then the student's own reference judgments in the wizard, then the LLM tests: `suite` prints each LLM verdict as it runs, so the student would see them before judging. The README's "Personal I: suites" steps follow the same order |
| 7 | `main()` built the argument parser | `parser()` builds it and `main()` uses it, so that the tests can check that every command and option a skill names exists |
| 8 | Only `doctor` and `status` said when a newer Skill Eval Lite was out. Nothing checked the brief folders | `run_ab.py updates` checks Skill Eval Lite against GitHub and each brief folder beside it against the course site's manifest (`<project>-for-ai.json`, which the course now publishes beside each ZIP, with a `pack.json` in the ZIP): newer, a new revision, the same revision with files changed, an older folder with no `pack.json`, up to date or couldn't check. It remembers its answer for a day in `.state/` (which git ignores) and sends nothing of the student's. `run_ab.py update --self` brings in a newer Skill Eval Lite (`git pull`, or the newest ZIP for a copy downloaded as a ZIP, keeping `experiments/`, `runs/` and `.claude/settings.local.json`); `update --brief <folder>` brings in a brief folder's newer copy, keeping the student's files and putting each replaced course file in its `previous/`. A new skill, `check-updates`, does both with a yes, then says what changed and records the revision the student goes by. `get-ready`, `shared-i`, `personal-i` and the helper check first |
| 9 | `.claude/settings.json` set permissions only: "no hooks" | It also sets one SessionStart hook, `run_ab.py updates --hook` (tried with `python3`, then `py`, then `python`, then nothing), which puts a line at the top of a session when something is newer and stays silent otherwise. It checks at most once a day, gives up after a few seconds and always exits 0. `updates` is allowed without a prompt; `update` asks |
| 10 | The wizard built its blind pairs and results from the development prompts only, so the held-out prompts could be run (`--held-out`) but not judged blind in it | Once the bundle has runs on the held-out prompts, step 3 shows them and step 4 adds their pairs as a set of their own, *Held out: the confirmation*: the baseline (A) against each round run on them, judged blind as before; the development pairs are unchanged. Step 5 reports the confirmation beside the development result (the people's share with its interval, resampling the held-out prompts; the judge's; each check's difference) and `results.json` gains `held_out`; the development result stays as it was. In `judgments.csv` their rows say `blind-preference-held-out` and `llm-judge-held-out` (no new column; an older wizard leaves them out on import). `judge --held-out` judges the same pairs, so the frozen file needs no A-to-final comparison |
| 11 | The wizard's *Getting started*, its guided tour and the README told students to type each command in a terminal, and Personal I's path ran the LLM tests before the student's reference | Each step is a message to Claude in the desktop app's Code tab, with the terminal's command folded under it. The first-time path installs the app, opens the course folder in the Code tab and types `/get-ready`. Personal I's path runs the mechanical tests, then the reference, then the LLM tests; the group path ends with the held-out confirmation. The step pictures show the Code tab. The README's ", and" joins are gone |
| 12 | The runner's next steps and fixes gave a command to type ("Next, run the LLM judge:  python3 run_ab.py judge runs/x"; "Fix the lines marked FIX, then run this again:  python3 run_ab.py doctor"); `claude_version` said "type `claude --version` in a terminal"; `status` gave each step as a command, its login step `claude` then `/exit`; `doctor` and `status` said "run git pull" for a newer version | Every message that says what to do next or how to fix something has one form: what to do, then the skill that does it, then the command for a terminal ("Next, run the LLM judge. In Claude, type /run-experiment (in a terminal: python3 run_ab.py judge runs/x).", `run_ab.py`'s `in_claude`). Each names the skill whose text covers the step: `/get-ready` for setup, `doctor` and the login, `/wizard` for the wizard, `/run-experiment` for a group's runs, judge and `score`, `/skill-eval-helper` for the demonstrations (which aren't frozen) and for an experiment's "must fix" lines, `/run-suites` for the suites, `/shared-i`, `/experiment-intake` and `/personal-i` for a new experiment or packet, `/check-updates` for updates (`update --self`, which works for a ZIP copy too). `status` shows the skill first with the command under it; `status --json` gives each step a `skill` ("/run-suites") beside `command`. The login step is `claude auth login`. With Codex the messages give their own commands alone and `skill` is null. A new test reads every message in `run_ab.py`'s source and what the commands print |

### What was verified for 0.2.0

- `tests/test_updates.py`: every state of `updates` against a stand-in for
  GitHub and the course site on this computer (no network), what it sends
  (the two addresses and nothing else), offline, the hook once a day and
  again after a folder changes, the hook never failing (an address that
  refuses, a state folder it can't write, a workspace that isn't there) and
  the settings' hook command run in `sh`, with and without Python on the
  PATH; `update --brief` on a new revision (the student's files kept, a
  course file it no longer has set aside, `--dry-run` changing nothing) and
  on an older folder with no `pack.json`; a ZIP with a path outside its
  folder refused; `update --self` on a ZIP copy (`experiments/`, `runs/` and
  the local settings kept, the replaced files kept in `.state/`) and on a
  git copy (refused while an own file has changes, then pulled).
- `tests/test_messages.py` (M4): every message in `run_ab.py`'s source that gives a command (each `say`,
  `Fail`, step text, constant and returned string, each branch of a condition on its own) names a real
  skill before it, except Codex's; every `status` step has a `skill`; and `setup`, `doctor` (ready,
  logged out, an API key, no `claude`), `new`, `check`, `plan`, `run`, `judge`, `score`, `suite` and
  `status` print it so, with the stand-in for `claude`. `tests/test_status.py` checks the `skill` field;
  its login step is now `claude auth login`.
- `python3 -m unittest`: all 207 tests pass. New: `tests/test_case_helper.py`
  (the suites-intake skill's `case.py`: saved sessions listed, a session
  copied with only its user and assistant lines and the same steps, a
  case's steps and text, what may be private found and masked, all in a
  home folder of the test's own); a test in `tests/test_status.py` for the
  new order; and `tests/test_skills.py`
  (every skill's front matter, its version mark, every `run_ab.py` command
  and option it names against the parser, no sentence asking the student to
  type a command in a terminal except signing `claude` in, the three guides
  in step with their skills, the README's table and copies of every skill
  left out of a run under any name while an assistant's own skill stays).
- Every command the Shared I skills name was run in a scratch workspace,
  with the stand-in for `claude` for those that call a model: `doctor
  --no-probe` (ok; without `claude`; logged out), `status`, `new --from
  class`, `check` (not frozen; frozen; changed since frozen), `plan --rounds
  A,B --jobs 4`, `run --rounds A,B`, then `C,D`, a run made again (nothing
  run twice), a failed run kept, `judge`, `score` (no program checks), a
  round E added and frozen again (`run --rounds E`, `judge --comparisons
  B-E`), a changed judging prompt (`run` refreshes the run folder's copy;
  `judge --again` uses it) and the held-out prompts (`run --rounds A,B
  --held-out`, `judge --held-out --comparisons A-B`).
- Not verified: anything in the desktop app itself (its Code tab, its
  prompts, `claude auth login` run from a session, whether the app and the
  `claude` command share a login), on macOS or Windows. A rehearsal on each
  is needed before release.
- **Held-out pairs can't be judged blind in the wizard yet.** The wizard
  builds its blind pairs and its results from the development prompts
  only, so the held-out runs and the AI judge's verdicts on them are made,
  but the members can't judge them in step 4. `read-results` says so.

## 0.1.4, 4 November 2026

Doing it all in Claude Code. Many students would rather not type commands,
so Claude Code can run them, and this folder now tells it which ones it may
run without asking. Requested for AI 5500's week 4 tutorials, which run
Skill Eval Lite entirely through Claude Code (Simon, 4 November: "I'm not
sure a lot of students will know how to use the terminal commands").

### If you are on 0.1.3 or earlier

1. In your `skill-eval-lite` folder, type `git pull`.
2. Nothing else. No result, file or command changes. Claude Code asks you
   less often: see below.

### What changed

| # | Before | In 0.1.4 |
| --- | --- | --- |
| 1 | In Claude Code in this folder (or `ask`), every command asked for permission, `status` and `check` included | `.claude/settings.json` lets Claude Code run, without asking, only the commands that read or check: `status`, `check`, `plan`, `doctor`, `suite ... --check`, `--help` and `--version`, with `python3` or `py`. `run`, `judge`, `suite`, `setup`, `score`, `new` and `ask` still ask, so each prompt a student sees is for a command that uses their plan or changes something. A command chained onto an allowed one still asks. The file sets nothing else: no hooks, no environment, no permission mode. A run never reads it: the runner runs the assistant in a copy of its own folder, with `--setting-sources project` there |
| 2 | The helper ran commands only after asking, but said nothing about Claude Code's own prompts, chained extra commands onto them, and could guess the assistant's folder | The helper (version 3, in `HELPER.md` too) offers to run each command, says before `run`, `judge`, `suite`, `setup` or `score` that Claude Code's prompt will appear, runs each command on its own as written, always gives the assistant's folder as `../<folder>`, and offers to open the wizard and to move the frozen experiment back from the Downloads folder |
| 3 | The README told students to type each command | A new section, "Doing it all in Claude Code", under "Stuck? Ask for help": what to say, what runs without asking and what asks, and the two steps that stay in the wizard (freezing, and your own judgments) |

### What was verified for 0.1.4

- `python3 -m unittest`: all 158 tests pass. New: `tests/test_settings.py`
  (five tests: the file sets only `permissions.allow`; every rule is a
  read-only runner command; nothing that spends or changes is allowed;
  `python3` and `py` have the same rules; the README names the file).
- `dev/embed_examples.py --check`, `node dev/diagrams.mjs --check` and
  `tutorial/build.py --check`: all up to date.
- With Claude Code 2.1.318, in a copy of this folder, `claude -p
  --setting-sources project`, asked to run ten commands exactly as written:
  `status`, `check`, `plan`, `suite ... --check` and `run --help` ran;
  `run`, `judge`, `suite`, `setup`, and a `check` with `; touch ...`
  chained on, were refused (in an interactive session, each would ask).
  The same with `--permission-mode manual`, as `ask` starts Claude Code.
- A whole Shared I experiment done in Claude Code from one request in a
  student's words (check, run in the background, judge), on 0.1.3, before
  these changes: it worked, with the two stumbles that fix 2 addresses.
- **Trust comes first.** Claude Code applies a folder's allow rules only
  after its trust question is answered Yes, and asks it per git project: in
  a fresh clone, every command asked until then. Its question lists the
  rules, says they "will apply without asking", and starts on "No, exit"
  (down arrow, then Enter, for Yes). The README says so.
- The helper's new text, in a whole session on a fresh clone of 0.1.4 in a
  trusted folder, on the class assistant with an experiment frozen as the
  wizard freezes it: `check` ran without a prompt; it opened the wizard,
  explained the freeze, read and moved the exported file back (each with a
  prompt, since Downloads is outside the folder), ran `check` again
  (`Frozen: yes`), and ran rounds A and B, then C and D, then `judge`, each
  after a yes, in the background, one command at a time, with
  `../class-assistant` each time. 32 runs and 24 pairs, $2.07; the helper
  about $0.45.
- Not yet: a `dev/fresh-trial.sh` of 0.1.4.

## 0.1.3, 3 November 2026

Five fixes from a fresh Personal I trial of 0.1.1 (3 November; the course's
proposal "Skill Eval Lite 0.1.3: five fixes from a fresh Personal I
trial"): `status` follows a Personal I packet and says who pays for a run;
a planted fault can name the case it was made from; the suite report says
when a control shows nothing; and the worked example's board reference is
repaired, with a second real run. Built on 0.1.2, released the same day.

### If you are on 0.1.2 or earlier

1. In your `skill-eval-lite` folder, type `git pull`.
2. Personal I: **what your suite report says can change.** In its controls
   table, a variation, or a fault whose `varies` names the reference, now
   reads `shows nothing: the test fails reference too (got ...)` when the
   test doesn't pass the reference, where earlier versions said `ok` or
   `MISSED`. A note under the table names the test. No result changes: the
   rows in `judgments.csv` are the same, and only the table reads them
   differently. If you have exported a report, export it again (the
   wizard's Report step, or `suite` again), and say in your write-up which
   version wrote it.
3. Personal I, if you copied the worked example before 0.1.3: its board
   reference, and the four controls made from it, had three facts wrong.
   If you build on that suite, copy the repaired files from
   `examples/personal-suites/controls/board-drafts/`, and run its LLM test
   again on them: `python3 run_ab.py suite <your packet>/suites.yaml
   --suite board-drafts --again`.
4. A fault you planted in the reference can say so: add
   `"varies": "reference"` (the reference's id) to its `expect.json`.

### What changed

| # | Before | In 0.1.3 |
| --- | --- | --- |
| 1 | `status` never looked at the Personal I packets when it chose the next step: in a Personal I pack it said "Set up the class assistant", even after the packet had run, and then the Shared I demonstration | With a packet beside Skill Eval Lite and no experiment of the student's own, the next step is Personal I's, for the packet, with its exact command: fix it (`suite --check`, with the count), run it, run it again when a test or file has changed, the wizard (reference judgments, then ratings), then the export. Wren is never asked for. With a packet and an experiment, `status` gives a step for each, headed "Next step, Shared I" and "Next step, Personal I", and `--json` adds `next_steps` (each with its `project`; `next` is still the first). With neither, Wren and the first demonstration stay first, with "On Personal I? You don't need Wren. Copy the worked example ..." under the command. A missing Wren reads "not set up yet (Shared I and the demonstrations need it; Personal I's suites don't)". `status --project shared\|personal` and `ask --project ...` force one project |
| 2 | The demonstration step said "each run uses your plan" whatever the login | One phrase from the status's own login: "each run is billed to your API key" (Claude Code's `api_key` login, or Codex's API key) or "each run uses a little of your plan", in the demonstration step and Personal I's run steps. The setup line says "logged in (api_key): runs are billed to the key". The README says `status` "calls no model" |
| 3 | The worked example's `fault-shorthand` expected the facts test to pass, but it is the reference with shorthand planted, so it carried the reference's wrong facts | `fault-shorthand` says `"varies": "reference"` and expects `same` for `facts-match-the-source`, with a new note. The suite designer lets a fault name the case it was made from (a fault made from a case names it by default) and expect "the same as the case it varies", and saves both. The example's README tells the story |
| 4 | A control's cell read `ok` when the test failed the reference too, so it showed nothing about the test | A control made from the reference (a variation, or a fault whose `varies` names it) reads `shows nothing: the test fails reference too (got ...)`, or `shows nothing: the test can't tell on reference (got ...)`, when the test doesn't pass the reference. It is neither `ok` nor `MISSED`. Under the table: "`<test>` fails the reference, so its results on the faults and variations show little until the reference or the test is fixed. Look at why first." In `run_ab.py`'s report and the wizard's, word for word; the wizard's Report step shows the note too. `fault-wrong-date` says `"varies": "reference"` |
| 5 | The case students copy as their board reference had three facts wrong ("Ellis Park"; "the committee asks the full board to decide"; the camp supplies "were bought in September"), and every board control was copied from it | Option A: the reference and its four controls say what the notes say. Its LLM test was run again for real on all eleven cases, recorded in `examples/recorded/personal-suites-2026-11-03/`, beside the 26 October recording, which is kept as it was. The example's README tells it as history |
| | `status --root` with a relative folder found no packets | The folder is resolved first (only the tests pass `--root`) |

Fixes 3 and 4 meet on one cell. The proposal's fix 3 expected `ok (same as
reference, got fail)` on `fault-shorthand` while the reference still
failed; fix 4 makes that cell `shows nothing`, since the reference failing
is exactly when the control shows nothing. With fix 5's repaired reference,
the second real run shows `ok (same as reference, got pass)`.

### What was verified for 0.1.3

- `python3 -m unittest`: all 153 tests pass, on Python 3.14 and 3.11.
  The new ones: seven in `tests/test_status.py` (fixes 1 and 2), one in
  `tests/test_suites.py` (fixes 3 and 4: the `shows nothing` cells and notes,
  `unknown`, a fault that doesn't name its case, and the repaired
  reference), two cases in `tests/test_wizard.py` (the wizard's report
  word for word with `run_ab.py`'s on a reference that fails, and the new
  recording), and one assertion in `tests/test_designer.py` (a fault made
  from a case names it). The designer's "written out unchanged" test
  covers `fault-shorthand`'s `varies` and `same`.
- `dev/embed_examples.py --check`, `node dev/diagrams.mjs --check` and
  `tutorial/build.py --check`: all up to date.
- Fix 5's real run (2026-11-03): the board suite on all eleven cases, with
  Claude Code 2.1.318 and an API key, model `claude-sonnet-5-5`, 4 to 11 s
  a case, $0.16 in all. The reference passed `facts-match-the-source`;
  `fault-shorthand` and both variations passed with it; `fault-wrong-date`
  failed on its two changed dates. Every board control reads `ok` for both
  automatic tests. Four of the six real drafts failed the facts test.
- Not yet: a `dev/fresh-trial.sh` of 0.1.3.

### Decided for 0.1.3

- **Fix 5: option A** (Simon, 3 November): repair the copy students start
  from, and keep the flawed one as the recorded lesson.
- **0.1.2 and 0.1.3 are two releases**, the same day: 0.1.2 the program
  checks, 0.1.3 these fixes on top.
- **The unknown case.** The proposal gave the words for a reference that
  fails; for one that gives `unknown`, the cell reads `shows nothing: the
  test can't tell on reference (got ...)` and the note "can't tell on the
  reference (unknown)".
- **A fault made from a case in the suite designer names it** (`varies`),
  so that a new fault planted in the reference gets fix 4's reading.

### Open, for Simon

- The class experiment's reference for `summarize-committee-notes`, and the
  same text in `demo-board-memo.toml` and `demo-voice-reordered.toml`, still
  have the three facts that were repaired in the Personal I example. Shared
  I uses it for its product checks, which it passes; it was left as it is.
- The course's own steps from the proposal: the 0.1.1 deploy of the project
  pages and packs, and dating 0.1.2 and 0.1.3 under `tools: skill-eval-lite:
  releases:` in `term.yaml`.

## 0.1.2, 3 November 2026

Program checks: a check that is a short Python program of the group's own,
for what the seven built-in kinds can't see (the order of a run's steps;
"only these amounts"; a date copied from the starting file), with a guide
for writing one, for Claude Code, Codex and people.

### If you are on 0.1.1

1. In your `skill-eval-lite` folder, type `git pull`. Nothing in an
   experiment needs to change: the built-in checks work as before.
2. Personal I: a program test that prints something other than `pass`,
   `fail` or `n/a` still gets `n/a`, but its reason no longer repeats the end
   of its own line; one that prints nothing says "the program printed
   nothing", with its error.

### What changed

| # | What | In 0.1.2 |
| --- | --- | --- |
| 1 | The experiment file | A check can be `kind = "program"`, with `program` (`checks/<folder>/<name>.py`, in the experiment's folder), `sha256` (the program's), and optionally `params` (a table the program reads) and `timeout_seconds` (1 to 600; 60). `files_from` now covers `checks/` too. Two checks with one id are a "must fix", for every kind |
| 2 | `check` | Says what is wrong with a program check without running it: its id, its path, a missing program, a missing or wrong `sha256` (it prints the line to write), `params`, `timeout_seconds`, and no fixture the program should fail (a "to do"). Then runs each program on every reference it applies to (product checks), which must pass, and on each of its fixtures (`checks/<id>/fixtures/<case>/expect.json`), which must give what they say. A `program:` line for each check |
| 3 | `run` | Tests the programs as `check` does before the first run, and doesn't start if one fails. Runs each program check on every output at the end. Keeps the results in the bundle (`program_results`, `program_reference_results`), beside each output (`outputs/.../checks/<id>.json`), and the programs in the run folder (`checks/`). Each output records the versions of the program checks it was made with. A run made again with `--again` is scored again |
| 4 | `score` (new) | `python3 run_ab.py score EXPERIMENT [--out RUN_FOLDER] [--checks ID,ID] [--again]` runs the program checks on saved outputs that have no result for the check as it is now, with no runs and no model. A result for a check the runs weren't made with is marked `added_after_run`, and `score` says its results are exploratory |
| 5 | How a program runs | In a fresh folder per case: the output, reference, trace, transcript, the files the run wrote, the starting files and `context.json`, but never the round, the repeat or the run's folder. `python3 -I -B -X utf8`, in that folder, with no API keys or tokens, and a time limit. The first line is the answer: `pass`, `fail` or `n/a` and a reason; anything else is `n/a`. A failed run isn't given to it. The assistant never sees a program check's folder (SAFETY.md, "Program checks") |
| 6 | The wizard | Shows the bundle's results as checks, everywhere the built-in ones are: the run drawer, the results, the controls, `judgments.csv` (with the runner's version, and `<program> (run_ab.py)` as who ran it). A result for another version of the check, or for an earlier run, is `n/a` with why. Step 3 says when a bundle has results the experiment loaded in step 1 doesn't have. A check added after the runs is marked "added after the runs". The freeze list and the references panel say that `check` runs the programs on the references |
| 7 | The designer | Keeps a program check it is given, with its folder, and saves them; its copy of `check` says what `run_ab.py` says about program checks, word for word (it works out the program's SHA-256 itself). It doesn't write or edit programs: its checks screen points to the guide |
| 8 | The guide | `CHECKS.md`, and the same text as the check-authoring skill (`.claude/skills/check-authoring/SKILL.md`, `/check-authoring` in Claude Code): when a program is the right tool (and when it is the judge's question instead), where the files go, what the program gets and prints, a template, fixtures, testing with `check`, and what changes after the freeze and after the runs. The intake (version 3) and the helper (version 2) point to it. The runner leaves the skill and `CHECKS.md` out of every run, as it does the intake and the helper |
| 9 | A demonstration | `examples/demo-program-check.toml` (`demo-graph-removed`'s design) with two program checks in `examples/class-assistant/checks/`: `looked-up-first` (on the process: a lookup in the knowledge graph before the first write; adapted from Personal I's `search-before-write`) and `no-made-up-amounts` (on the product, with `params`), each with fixtures |
| 10 | `status` and `new` | `status` says when your experiment's program checks have results missing or out of date on its runs, and gives the `score` command. `new` copies the program checks' folders an experiment uses |

### What was verified for 0.1.2

- `python3 -m unittest`: all 144 tests pass, on Python 3.14 and 3.11. The
  19 new ones are in `tests/test_programs.py` (README, "Tested").
- `dev/embed_examples.py --check`, `node dev/diagrams.mjs --check` and
  `tutorial/build.py --check`: all up to date.
- With the fake `claude`, `demo-program-check`: `looked-up-first` passed
  both of round A's briefs and failed both of round C's (the graph removed;
  "no lookup in the knowledge graph before the first write (step 2)"), and
  `no-made-up-amounts` passed all four and both references.
- Not yet: a run of `demo-program-check` with a real model, and a
  `dev/fresh-trial.sh`.

### Decided for 0.1.2

These were the plan's open questions; each took the plan's recommendation.

- **The freeze covers a program through its `sha256`** in the experiment
  file, so the fingerprint itself didn't change. A program's fixtures, the
  round files and the starting files are still not covered (a limit, in the
  README).
- **Python only**, standard library, one file: it runs with the runner's own
  Python on every system. A suite's program test can still be any program.
- **The designer keeps program checks but doesn't write them.** Writing one
  is the guide's job, with Claude Code or Codex, and `check` tests it.
- **A program may read the reference**, and the prompt's starting files.

### Open, for Simon

- Writing a program check in the designer, as the suite designer lets a
  student write a program test.
- An LLM check per output (the suites' LLM test, in an experiment).
- Fingerprinting the round files, the starting files and the fixtures.
- A small library of vetted program checks that groups can copy.

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

As of 0.1.3 (0.1.3 adds `examples/recorded/personal-suites-2026-11-03/`; the files 0.1.2 added: `CHECKS.md`, `.claude/skills/check-authoring/`, `examples/demo-program-check.toml`, `examples/class-assistant/checks/` and `tests/test_programs.py`; 0.1.1 added `tests/test_shared.py`, `tests/test_freeze.py` and `tests/fixtures/`).

| Path | What it is |
| --- | --- |
| `README.md` | What it is, the walkthrough, the experiment file, the run folder, the commands, what was tested, the limits |
| `SAFETY.md` | The isolation flags, what each excludes, and what was verified |
| `VERSION` | The version, in one place (`run_ab.py` reads it; a test checks `wizard.html`'s copy) |
| `run_ab.py` | The runner: `setup`, `doctor`, `check`, `plan`, `run`, `judge`, `score` (program checks), and for Personal I `suite` (Python 3.11+, standard library), with Claude Code or Codex (`--runner codex`); `status`, `ask` and `new` for students who are stuck |
| `HELPER.md`, `.claude/skills/skill-eval-helper/SKILL.md` | The helper's instructions, which `ask` gives Claude Code or Codex (the same text twice) |
| `wizard.html` | The wizard: one offline page, with the class intake and a made-up practice pack embedded; Shared I's five steps, and Personal I's checks-only mode (four steps) when a suite bundle is loaded; and two designers that make the files on screen: the experiment designer (nine screens, saving `experiments/<name>/`) and the suite designer (six screens, saving a packet), each into a folder the student picks or as a ZIP |
| `dev/embed_examples.py` | Writes the designers' starting points into `wizard.html`: the class experiment's round, starting and check files, the demonstrations, and the worked example of Personal I (`--check` says whether they are up to date) |
| `.claude/skills/experiment-intake/SKILL.md`, `AGENTS.md` | The intake instructions, for Claude Code and for Codex |
| `CHECKS.md`, `.claude/skills/check-authoring/SKILL.md` | How to write a program check, for Claude Code, Codex and people (the same text twice) |
| `class-assistant/overlay/` | What `setup` lays over the AI 5100 template: `overlay.toml` (the pinned commit and the copies) and 26 knowledge-graph pages |
| `examples/class-assistant/` | The class intake: `experiment.toml`, round files B and D, starting files; and `checks/`, the program checks of `demo-program-check` |
| `examples/demo-*.toml` | The five demonstrations (`demo-one-line` added 2026-10-27 for the live session; `demo-program-check` for 0.1.2) |
| `examples/personal-suites/` | Personal I's worked example: two suites (a product, six real drafts; a process, four real runs), each with a reference, two planted faults, two harmless variations and three tests |
| `examples/recorded/` | Real runs of the four demonstrations, with the judge (`demo-one-line` made 2026-10-27), and of the worked example's suites, with eight real LLM test runs (made 2026-10-26) and, after its board reference was repaired, eleven more (2026-11-03, `personal-suites-2026-11-03/`); and a real Codex run of the first demonstration, with its judge (`demo-graph-removed-codex/`) |
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
- A program check runs on the student's computer with their permissions,
  in Python's isolated mode with a time limit, but not in a sandbox
  (SAFETY.md, "Program checks"). The wizard can't run one, and the designer
  doesn't write one.
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

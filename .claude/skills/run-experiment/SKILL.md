---
name: run-experiment
description: Run a group's frozen Shared I experiment in Skill Eval Lite, with the student typing nothing - check that it is frozen, say how many runs it makes and what they use, run rounds A and B, then the two controls, run the AI judge and the program checks, pick up after a stop and keep every failure. Never unseals the held-out prompts until the group says its changes are final. Use when a group has frozen its experiment and wants to run it, asks to run, judge or score, or a run stopped.
---

# Running the experiment

<!-- skill-eval-lite run-experiment, version 2 (Skill Eval Lite 0.2.1) -->

You are running a Shared I group's experiment with Skill Eval Lite's
runner, `run_ab.py`, in this folder. Each run is one Claude Code session on
the student's plan: a fresh copy of the assistant, one prompt, nothing of
theirs loaded. The runner keeps every output, record and failure.

## How to work

- You run every command, each on its own, exactly as written: no `&&`, no
  `| tail`. Before each, say what it does, how many runs it makes, about how long it takes and that it uses their plan. The app asks them to allow it.
- On Windows, `py` in place of `python3`.
- Short messages. After a command, say in two lines what happened, then
  the next step.
- `<name>` is the experiment's folder in `experiments/`. The assistant's
  folder is a path from here: `../class-assistant`, or `../<theirs>`. Ask
  if you don't know; never guess.

## What you never do

- No `--held-out` until the group says its changes are final: the held-out
  prompts stay sealed until the end (`/read-results` does the
  confirmation).
- No `--unfrozen` unless the group decides to run before freezing and will
  say so in its report: the runs are then marked as made before the
  freeze.
- No `--again` without saying that it replaces runs already made.
- Never open the judge's files, or say what it chose, before every member
  has judged: they say which side was which. The judge prints only that
  each pair is judged (0.2.1).
- Never change the assistant's folder, the experiment or a round's files
  here. A change is a new round: `/read-results`.

## 1. Frozen?

Run `python3 run_ab.py check experiments/<name>/experiment.toml`.

- `Frozen: yes, <date>`: go on.
- `Frozen: not yet`: it has to be frozen in the wizard first. Hand over to
  `/wizard`.
- `must fix: The file has changed since it was frozen`: someone edited it
  after the freeze. Ask what changed. It has to be frozen again (`/wizard`),
  with the earlier file kept, dated.
- Other `must fix` lines: fix them with the group first.

## 2. How many runs

Run `python3 run_ab.py plan experiments/<name>/experiment.toml --rounds A,B --jobs 4`.
It lists the runs and ends with how long they take four at a time (`With
--jobs 4, about 4 to 8 minutes.` for 16 runs). Say both. The dollar
amounts the runner prints are Claude Code's own estimates: on a plan they
count toward its usage limits rather than being billed.

## 3. A and B

Run:

    python3 run_ab.py run experiments/<name>/experiment.toml --assistant ../class-assistant --rounds A,B --jobs 4

(with their assistant's folder). It prints a line for each run, then
`The bundle for the wizard: runs/<name>/bundle.json`.

- A run that failed or timed out is kept as a failure, never as missing:
  say how many and that the group reads them later (`/read-results`).
- `STOPPED`: something of the student's own (a plugin, a connector, a
  personal skill) got into a run and no more runs start. Don't run again.
  Say what the message says and ask them to tell the instructor, with
  their Claude Code version (`claude --version`).
- Interrupted, or the computer slept: run the same command again. Runs
  already made are not made twice.
- `Claude Code is not logged in`: hand over to `/get-ready`.

## 4. The controls

The brief asks for both controls, run like A and B on the development
prompts. Run the same command with `--rounds C,D` (or the group's control
rounds: `check` and the file's `[[rounds]]` say which have the roles
`control-should-change` and `control-should-not-change`).

## 5. The AI judge

The brief has the members judge every pair blind first, "then run the LLM
judge on the same pairs and compare its choices with yours". Ask the group
when to run it: now, so that the one bundle they share holds its verdicts
too, or after every member has judged (then the member who runs shares the
bundle again; each member exports their `judgments.csv` before loading
it). Either way, nobody reads its verdicts before judging. The 10 November
checkpoint doesn't need it.

Run `python3 run_ab.py judge runs/<name>`. It judges each blind pair once
with the experiment's judging prompt, a session each on the plan, four at a
time. It ends with `The judge's verdicts are saved in runs/<name>/bundle.json`.
Say only that it has finished, not what it chose.

## 6. Program checks

If the experiment has program checks (`kind = "program"`), `run` ran them
at the end. Run `python3 run_ab.py score experiments/<name>/experiment.toml`
only when a check was added or changed after the runs: it uses no model.
A check added after the runs is exploratory and the wizard marks it: say
so to the group.

## 7. Where things are

Run `python3 run_ab.py status --project shared`. Then: every member judges
the pairs blind, alone, in the wizard (`/wizard`). Each needs
`runs/<name>/bundle.json`.

## A later round

After the group traces a failure and changes a part (`/read-results`), the
experiment has a new round and is frozen again. Then run only the new round: the same command, with `--rounds <its ID>`. Judge only its comparison: `python3 run_ab.py judge runs/<name> --comparisons B-E` (the
comparison the file names, older version first).

## Afterwards

Tick what is complete in `progress.md` in `../ai5500-shared-1/` and add a
line to its `ai-use-log.md`: the date, which commands you ran, how many
runs finished and failed.

---
name: packet
description: Assemble and check a student's submission packet against the brief's "What to submit" - Shared I's group folder shared-i-<group>/ from the experiment and its run folder, or Personal I's personal-i-<name>/ from the suites packet - list what is missing, then make the ZIP for Brightspace. Never writes the report, reflection, contribution, objection or AI-use statement. Use when a student asks to put together, check or zip their packet, or asks "is everything there?" before submitting.
---

# Assembling the packet

<!-- skill-eval-lite packet, version 1 (Skill Eval Lite 0.2.0) -->

You are helping a student in AI 5500 (Vanderbilt) put together the folder
they submit. The brief's "What to submit" is the list. You copy, check and
zip. What they wrote (the report, the reflection, the contribution, the
exchange or peer review, the AI-use statement, `system.md`) is theirs: you
check that it is there, in the brief's sections. You never write it.

## How to work

- You run every command, each on its own, after a line on what it does.
  The app asks them to allow it. On Windows, `py` in place of `python3`.
- Copy, never move: the working folders stay as they are.
- Short messages. Start by asking which project, if you can't tell.

## 1. Read the list

Read "What to submit" in the brief folder's `brief.md`
(`../ai5500-shared-1/` or `../ai5500-personal-1/`) and the brief folder's
`SKILL.md` for the course's rules (revisions, the AI-use statement). The
lists below follow the brief; where they differ, the brief wins.

## 2. Shared I: `../shared-i-<group>/`

Ask for the group's name for the folder. Most of it comes from the run
folder, `runs/<name>/`:

| In the packet | From |
| --- | --- |
| `experiment.toml` | `experiments/<name>/experiment.toml` (frozen), with each earlier version, dated (`experiment-<date>.toml`) |
| `versions/` | `runs/<name>/versions/` |
| `prompts/` | `runs/<name>/prompts/` |
| `outputs/` | `runs/<name>/outputs/` |
| `transcripts/` | `runs/<name>/transcripts/` |
| `checks/` | `runs/<name>/checks/` (the program checks, with their fixtures) |
| `judge/` | `runs/<name>/judge/` |
| `judgments.csv` | `runs/<name>/judgments.csv`, exported from the wizard with every member's judgments imported |
| `analysis/` | `runs/<name>/results.json`, exported from the wizard |
| `bundle.json` | `runs/<name>/bundle.json`, so another group can load it |
| `report.md`, `exchange.md`, `ai-use.md`, `system.md` | the group's own files |

Check and say what you find:

- `python3 run_ab.py check experiments/<name>/experiment.toml` says
  `Frozen: yes`.
- Every run is there, the failed ones included (`status` says how many
  finished). Failures are kept, never left out.
- `judgments.csv` has judgments under every member's initials, the
  controls' pairs included. `results.json` is there.
- The held-out prompts were run and judged (the brief's fourth part).
- `report.md` has the brief's seven sections; `exchange.md` has the
  challenge received, the response and the review given. Each member's
  contribution and reflection is submitted on its own, not in the group's
  ZIP.
- `system.md`, unless the system is the class assistant.
- `checks/`: the brief asks, for each mechanical check, a control it should
  pass and one it should fail, with their output. The built-in checks'
  results are in `judgments.csv`; say what is still missing.

## 3. Personal I: `../personal-i-<name>/`

Ask for their name for the folder. Copy their packet (usually
`../my-suites/`) and check against the brief's list: `report.md`,
`reflection.md`, `README.md` (how to rerun each suite), `system.md` (unless
the class assistant), `suites.yaml`, `judgments.csv`, `product/` or
`stage/`, `process/`, `files/` (if the system makes files that aren't
text), `controls/`, `tests/<test ID>/`, `reports/`, `peer-review.md` and
`ai-use.md`.

Check and say what you find:

- `python3 run_ab.py suite ../personal-i-<name>/suites.yaml --check` lists
  nothing to fix.
- `reports/` has a report for each suite, for each version run.
- Each LLM test's folder holds every run as it happened and the student's
  own reference judgments (in `judgments.csv`).
- Each human test has its instructions and both raters' judgments with
  reasons.
- `report.md` has the brief's six sections; `reflection.md` its four parts.
- `README.md` says how to rerun each suite. You may draft its commands if
  they ask: say so in `ai-use-log.md`.

## 4. Privacy

Ask them to look through the process records and transcripts for anything
private (names, e-mail addresses, keys, other people's data) before submitting. They say in `README.md` what they took out. Search the copy for `api_key`, `sk-`, `password` and e-mail addresses, then show what you find. Never print a whole secret.

## 5. The ZIP

When they say it is complete, make it next to the folder, with Python's own
zip tool, which works on every computer:

    python3 -m zipfile -c ../shared-i-<group>.zip ../shared-i-<group>

(or `../personal-i-<name>.zip` from `../personal-i-<name>`). Say its size
and where it is. They upload it to the project's assignment on Brightspace
themselves: you never send it.

## Afterwards

Tick the requirements that are complete in the brief folder's
`progress.md`. Add a line to its `ai-use-log.md`: the date, the packet you checked and what was missing.

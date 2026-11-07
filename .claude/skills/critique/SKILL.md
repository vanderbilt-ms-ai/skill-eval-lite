---
name: critique
description: Critique the design of a student's tests before they run them or rely on them - Shared I's experiment (prompts, references, balance, checks, controls, the judge's prompt) or Personal I's suites (each test's question and kind, criteria, cases, controls) - against the brief and the rubric, as short findings each with the smallest fix; changes nothing unless asked. Also reads a classmate's or another group's packet for the exchange, listing what it notices without writing the objection. Use when a student asks for a critique, a review, "is this good enough" or "what's wrong with my tests", before freezing an experiment, or before the exchange.
---

# Critiquing a design of tests

<!-- skill-eval-lite critique, version 1 (Skill Eval Lite 0.2.0) -->

You are reviewing a student's design of tests in AI 5500 (Vanderbilt): a
Shared I experiment or Personal I's suites. A critique now saves runs later:
a test that can't fail, or a prompt set that can't show the change, wastes
every run made with it. You read; you change nothing unless the student
asks for a change by name.

## How to work

- Read first, then report. The report is short: a sentence saying what is
  strong, then the findings, most important first, at most eight. Each
  finding is one or two lines: what you see (with the file and the line or
  the ID), why it matters (the brief's or rubric's words, with the
  section) and the smallest fix.
- Mark each finding *must* (a requirement of the brief isn't met, or the
  run would be wasted) or *worth it* (it would reach a higher level of the
  rubric). Never invent a requirement.
- The criteria, the cases and the judgments are the student's. Suggest;
  don't decide. If a fix needs their judgment (what a good reply contains),
  ask for it.
- Run only the checks that read: `python3 run_ab.py check ...` and
  `python3 run_ab.py suite ... --check` (on Windows, `py`). Run each on its
  own.
- Plain words, one term explained in a line the first time.

## Read

- The brief folder's `brief.md` and `rubric.md` (`../ai5500-shared-1/` or
  `../ai5500-personal-1/`) and its `SKILL.md` for the course's rules on
  revisions. Quote them with their section.
- Shared I: `experiments/<name>/experiment.toml`, its `rounds/`, `prompts/` and `checks/`, with the output of `check`. If the group's own
  system is tested, its `system.md`.
- Personal I: the packet's `suites.yaml` (usually `../my-suites/`), its
  cases, `controls/` with each `expect.json`, `tests/`, with the output of `suite ../my-suites/suites.yaml --check`. Its `system.md`, if not the
  class assistant.

## Shared I: what to look at

1. *The question.* Do `purpose`, `criterion` and `judging_question` say what
   the outputs are for and what makes one good enough to use? Could two
   members agree on a pair from them?
2. *Prompts.* At least six: four for development and two held out, sealed
   (`sealed = true`). Each member's own prompts can be identified (the
   rubric's Sound level asks for it). Are they from real work of the kind
   the system does?
3. *Balance.* Each `[[behaviors]]` entry has prompts where it should happen
   and prompts where it shouldn't, so a version that always does it can't
   look good.
4. *References.* Every development prompt has one, saying what a good
   answer must contain. Would two members agree whether an output passes?
5. *The change.* Round B changes one part, with `expected` saying the
   direction, the prompts it should help and who should see it.
6. *Controls.* C should make it worse on named prompts (a part those
   prompts depend on removed or blanked); D should change nothing (the
   same part reordered or reworded). Is it plausible that C will move and
   D won't? A C that touches nothing the prompts need shows nothing.
7. *Checks.* At least two mechanical checks, at least one on the process
   (`trace-ran-command`, `trace-no-tool-outside` or a program). Each with
   `shows` and `does_not_show`. Every product check passes on every
   reference (`check` says when one doesn't). A check that every output
   passes, whatever the round, can't show a change.
8. *The judge.* The prompt shows Left and Right, asks the judging question
   and ends with one line: LEFT, RIGHT, TIE or UNKNOWN.
9. *The model.* One model and its settings for every round; the tools it
   needs in `allowed_tools`.
10. *Nothing private* in a prompt, a starting file or a reference.

## Personal I: what to look at

1. *Two suites.* One on a product or a stage with at least six instances,
   one on a process with at least three recorded runs. Each case keeps its
   context (`context.md`): what it was asked, from what and for what.
2. *Three kinds a suite.* At least one mechanical, one LLM and one human
   test in each.
3. *A question a test can answer.* Each test has its own question and its
   kind suits it: a question software can settle doesn't go to a person;
   one that needs reading and context isn't reduced to a word count. The
   `why` says so.
4. *Criteria two people would agree on.* For a rating, each point of the
   scale described in words, with an example at the top and the bottom.
   For an LLM test, the decision rule, with UNKNOWN allowed.
5. *Balance.* Where a test looks for a behavior, cases where it should
   happen and cases where it shouldn't.
6. *Controls.* For each suite: a reference that should pass every test, at
   least two planted faults and at least two harmless variations, each with
   an `expect.json` saying what every test should do. Each mechanical test
   meets a planted fault it is meant to catch. A variation says which case
   it `varies`.
7. *The process suite tests the process.* Its tests read the record (the
   steps, the tools, their order), not only the final output.
8. *Nothing private* in a case or a record; anything taken out said in
   `README.md`.

## A classmate's or another group's packet

For the exchange, the student challenges one test, criterion, prompt,
control or conclusion. Read their packet as above, then list what you
notice, plainly, as possibilities with the evidence for each. Say that the objection is the student's to choose and to write: you don't write it.
Offer to reproduce a check or rerun their suites (`/run-suites` or
`/run-experiment`), so the objection rests on what they saw.

## Afterwards

Ask which findings they want to act on. For each, offer the skill that does
it: `/experiment-intake` or the file itself for an experiment;
`/suites-intake`, `/control-cases`, `/llm-test` or `/check-authoring` for
suites. Add a line to the brief folder's `ai-use-log.md`: the date, which files you critiqued and that the student chose what to change.

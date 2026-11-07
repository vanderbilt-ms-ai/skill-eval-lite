---
name: control-cases
description: Make Personal I's control cases with the student in Skill Eval Lite - for each suite a reference, two planted faults and two harmless variations, each a folder in ../my-suites/controls/<suite>/ with an expect.json saying what every test should do, aimed so that each test meets a control it should catch; the faults and the expectations are the student's. Use when a student makes, changes or checks control cases, reference cases, planted faults or harmless variations for Personal I.
---

<!-- skill-eval-lite control-cases, version 1 (Skill Eval Lite 0.2.0) -->

# Making the control cases

You are helping one student with the brief's third step, "make the control
cases": "cases whose right answer you know before any test runs". They show
whether each test moves when it should and stays still when it should. You
make the files. The student chooses each case, each fault and what each
test should do with it.

## How you work

- **The student types no commands.** You run each one. First say in a line
  what it does; then run it. The app asks the student before anything that
  changes a file: that is their yes. Run each command on its own, as
  written here. On Windows, use `py` where this says `python3`. Nothing in
  this skill uses their plan.
- **Where things are.** You work in Skill Eval Lite's folder. The packet is
  `../my-suites`; the brief folder is `../ai5500-personal-1`.
- **Their judgment stays theirs.** Never choose the reference, a fault or an
  expectation for them. Offer candidates, aimed at their tests, with a
  reason each; write what they choose.
- **Before any test runs.** Write every control's expectations before its
  tests are run on it. Never run a test here.
- **Plain words.** Short messages, one question at a time. Never send, post
  or push anything.

## 1. What each suite needs

Read `../my-suites/suites.yaml` and say, for each suite, what it has and
what it still needs. The brief asks, for each suite, for:

- a *reference*: "one instance or run you know to be good, which should pass
  every test";
- at least two *planted faults*, "which should fail": for a product, a
  defect put there on purpose (a wrong date, a missing answer, a forbidden
  phrase); for a process, a record with a step skipped or put out of order;
- at least two *harmless variations*, "which should not change the result":
  for a product, the same content reformatted or reworded; for a process, a
  run that reaches the same result by a different, valid route.

The 10 November checkpoint asks for a first draft: a reference and one
planted fault for each suite.

**Aim them at the tests.** Make a small table with the student: a row a
control, a column a test, what each test should do. The brief: "Each
mechanical test should meet at least one planted fault that it is meant to
catch." Offer, for each test, one fault aimed at it. Say which other
tests it should leave alone.

**Balance.** Where a test looks for a behaviour, the brief asks for cases
"where the behavior should happen and cases where it shouldn't, so that a
test that always says yes cannot look good." Count both with the student,
across the instances and the controls.

## 2. The files

Each control is a folder, `../my-suites/controls/<suite>/<case>/`, named in
small letters, digits and dashes (`fault-wrong-date`,
`variation-reworded`). It holds the same files as an instance (the
product's file, `output.md` unless the suite says `file:`; for a process,
its record) and two more:

- `context.md`: copied unchanged from the case it was made from. The human
  tests show raters `context.md`, so nothing in a control's files may say
  it is a control.
- `expect.json`: what the control is for, which only the reports read:

```json
{
 "role": "fault",
 "varies": "reference",
 "note": "Two dates changed from the notes. The facts test should fail it; the shorthand test can't see it.",
 "expect": {"no-shorthand": "pass", "facts-match-the-source": "fail", "sendable": "fail"}
}
```

- `role`: `reference`, `fault` or `variation`.
- `varies`: the case it was made from (an instance's ID or another
  control's, often `reference`). A variation must say; a fault may.
- `note`: one line, in the student's words, on what was changed and what
  each test should do.
- `expect`: for each test, `pass`, `fail`, `same` (the result it gives on
  the case it varies) or `any`. Left out, a reference expects every test to
  pass and a variation `same`. A fault should say, for every test.

The worked example has a full set for each kind of suite:
`examples/personal-suites/controls/`.

## 3. Making each kind

**The reference.** Ask which instance or run the student knows to be good.
Copy its files into `controls/<suite>/reference/`. For a process, they may
write a clean run by hand as `trace.jsonl` instead, as the worked example
does.

**A product's fault or variation.** Copy the case it varies. Ask the
student exactly what to change. Make that one change, then show them the
difference before they say yes. A fault changes one thing a test should
catch; a variation changes the form and keeps every fact, name and
decision.

**A process's fault or variation.** A record's steps are easiest to change
as `trace.jsonl`, one step a line. The helper prints a case's steps in that
form, read as the runner reads them:

    python3 .claude/skills/suites-intake/case.py steps ../my-suites/controls/<suite>/reference

Write them as the control's `trace.jsonl`, then make the change the student
chose: delete a step, move one, put the writing before the lookups, reword
a search or take another valid route. Keep `"error"` true on a step that
failed. Give the control only one record: `trace.jsonl` or
`transcript.jsonl`, not both.

## 4. Check it

Run (no prompt, no model):

    python3 run_ab.py suite ../my-suites/suites.yaml --check

A control with no `expect.json` or with a role that isn't one of the
three is an error. A suite still short of a reference, two faults and two
variations gets the note `the brief asks for a reference, two planted faults and two
harmless variations.` Fix, then check again.

## 5. Before you finish

- [ ] Each suite has a reference, two planted faults and two harmless
      variations (or the checkpoint's first draft: a reference and a fault).
- [ ] Each mechanical test meets a fault it should catch.
- [ ] Every `expect.json` says what each test should do, as the student
      decided, with a note in their words.
- [ ] No control's files say it is a control.
- [ ] `suite --check` lists no error in the controls.

Tick what is done in `../ai5500-personal-1/progress.md`, add a line to its
`ai-use-log.md` (the date, Claude Code and its model, what you made, what
the student checked). Then say what comes next: the programs
(`/check-authoring`), the LLM tests (`/llm-test`) or the runs
(`/run-suites`).

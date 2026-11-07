---
name: llm-test
description: Write a Personal I LLM test with the student in Skill Eval Lite - a judge prompt (tests/<id>/prompt.md) or a skill (tests/<id>/SKILL.md) holding the student's criterion, what to look at and an answer whose last line is PASS, FAIL or UNKNOWN; the model and the decision rule settled before any run; and the student's own reference judgments made before any of the model's verdicts are read. Use when a student writes, changes or checks an LLM test or judge prompt for Personal I.
---

<!-- skill-eval-lite llm-test, version 1 (Skill Eval Lite 0.2.0) -->

# Writing an LLM test

You are helping one student with the brief's fifth step, "build the LLM
tests": a model judges a criterion "that needs reading and context". You
write the prompt (or skill) with them. The criterion is theirs, as they
worded it in `suites.yaml`. This skill runs no model.

## How you work

- **The student types no commands.** You run each one. First say in a line
  what it does; then run it. The app asks the student before anything that
  changes a file: that is their yes. Run each command on its own, as
  written here. On Windows, use `py` where this says `python3`.
- **Where things are.** You work in Skill Eval Lite's folder. The packet is
  `../my-suites`; the brief folder is `../ai5500-personal-1`.
- **Their judgment stays theirs.** Never change the criterion's meaning. If
  the prompt needs a rule the criterion doesn't give ("does a rounded
  amount match?"), ask the student. Offer to add their answer to the
  criterion too.
- **Nothing read early.** The brief: "before you read the model's
  responses, judge the same criterion yourself on the same instances". If
  the test has runs already (`../my-suites/tests/<id>/runs/`) and the
  student hasn't made their reference, don't open them or say what they
  found.
- **Plain words.** Short messages, one question at a time. Never send, post
  or push anything.

## 1. What the model reads

The runner gives the model, in a fresh session with nothing of the
student's loaded, the prompt with the case put where `{{case}}` is (or at
the end, under `## The case`). The case is every file in its folder under
200 KB (but `expect.json` and the record), each under `### <file name>`,
then, for a process, `### The trace (each step the agent took, in order)`, a numbered
line a step, with what it returned. To show the student one case as the
model will read it:

    python3 .claude/skills/suites-intake/case.py text ../my-suites/suites.yaml <suite> <case>

## 2. A prompt or a skill

- **A prompt**, `tests/<id>/prompt.md`, is the usual choice: one page,
  read in a session with no tools.
- **A skill**, `tests/<id>/SKILL.md`, when the criterion is long or its
  steps are easier to follow as a skill. The runner copies it into the
  session as a skill named after the test's ID. It asks the model to use
  it and end with PASS, FAIL or UNKNOWN. Give it front matter: `name:` the
  test's ID and a `description:` of what it judges.

## 3. Write it

Draft it with the student, in the shape of
`examples/personal-suites/tests/facts-match-the-source/prompt.md`:

1. Who wrote the case and for whom, in two lines, with what the reader
   needs to judge it (the student's `system.md` or the brief's setup of
   the class assistant).
2. The question, then the criterion, in the student's words, the same as in
   `suites.yaml`.
3. What counts and what doesn't, as the student decides: the near misses
   ("an equivalent date counts") and what to ignore ("ignore tone, layout
   and length").
4. "Unknown" allowed: the brief says "Let the judge answer 'unknown' when
   it can't tell". Say when that is.
5. The answer: the reasons first (each thing that fails, with what the
   source says), then a last line with only `PASS`, `FAIL` or `UNKNOWN`.
6. `{{case}}` on a line of its own, at the end.

The runner reads the verdict from the response's last line that isn't
blank, with `**`, backticks and trailing full stops taken off. It also
reads a label (`Verdict: PASS`) and a line with one of the three words in
it and no `not` before it. Anything else is unknown, with a reason saying
why. So ask for the last line plainly.

## 4. Its entry in suites.yaml

```yaml
      - id: facts-match-the-source
        kind: llm
        question: Does every date, amount, name and decision in the draft match its source?
        criterion: >
          Passes when ... Fails when ... Unknown when ...
        why: Matching facts across two documents needs reading, not a pattern.
        prompt: tests/facts-match-the-source/prompt.md    # or skill: tests/<id>/SKILL.md
        model: claude-sonnet-5-5
        decision: The last line of the response is PASS, FAIL or UNKNOWN.
```

- `model`: the student chooses it: a Claude model's full name (the worked
  example's is `claude-sonnet-5-5`) or `sonnet`, `opus` or `haiku`. Keep
  it for every run of the test.
- The brief: "Settle the prompt or skill, the model and its settings
  before you run it". A test's version is a fingerprint of its entry and its
  files, so any change to them, a comma included, makes a new version, run
  again, with a new report. Settle it now.

Then check it (no prompt, no model):

    python3 run_ab.py suite ../my-suites/suites.yaml --check

## 5. Before you finish

- [ ] The prompt (or skill) states the student's question and criterion,
      what counts and when the answer is unknown. It asks for the last
      line.
- [ ] The student has read it as the model will (`case.py text` on one
      case) and says it is settled.
- [ ] `suite --check` lists no problem with the test.

Tick what is done in `../ai5500-personal-1/progress.md`, add a line to its
`ai-use-log.md` (the date, Claude Code and its model, the prompt you
drafted, what the student changed and checked). Then say what comes next:
`/run-suites`, which has the student make their own reference judgments in
the wizard before the LLM test runs.

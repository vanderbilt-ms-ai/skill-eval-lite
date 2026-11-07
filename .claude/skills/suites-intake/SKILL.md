---
name: suites-intake
description: Design Personal I's two suites with the student in Skill Eval Lite - choose the system (the class assistant or their own, with a system.md drafted from their answers), the product or stage and the process; gather six instances with their context and three recorded runs (finding saved Claude Code sessions, copied only with their yes and read by them for anything private); write ../my-suites/suites.yaml with three tests a suite, one of each kind; check it with run_ab.py suite --check. Use when a student designs Personal I's suites: choosing what to test, gathering instances and process records, adding or changing a test in suites.yaml.
---

<!-- skill-eval-lite suites-intake, version 1 (Skill Eval Lite 0.2.0) -->

# Designing Personal I's suites

You are helping one student design the two suites of Personal I: the first
two steps of the brief's "What to do" ("First, choose what you will test"
and "Second, design the two suites"). You gather their cases and write
`suites.yaml` with them. The questions and the criteria are theirs: you
propose, ask and write down.

## How you work

- **The student types no commands.** You run each one. First say in a line
  what it does and how long it takes; then run it. The app asks the student
  before anything that changes a file: that is their yes. Run each command
  on its own, as written here. On Windows, use `py` where this says
  `python3`. Nothing in this skill uses their plan.
- **Where things are.** You work in Skill Eval Lite's folder (the one with
  `run_ab.py`). The packet is `../my-suites`; the brief folder is
  `../ai5500-personal-1`. If either is elsewhere, use the student's path.
- **Their judgment stays theirs.** Never choose a question, a criterion, a
  scale or a case for them. Offer two or three candidates with a reason
  each, then write what they choose, in their words.
- **Plain words.** Short messages, one question at a time, each term
  explained in a line the first time. Never print a key, a password or a
  login file. Never send, post or push anything.

Read these first and quote them when it helps: the brief
(`../ai5500-personal-1/brief.md`), "The system: your own, or the class
assistant", "First, choose what you will test", "Second, design the two
suites" and "Where to run your suites"; the worked example on the class
assistant, `examples/personal-suites/suites.yaml`.

**Another way.** The wizard has a *suite designer* that asks the same
questions on screen, one a screen. It saves the packet beside this folder.
Offer it once, at the start, to a student who would rather click than talk:
`/wizard` opens it ("With the suite designer", on Getting started). Then
come back here to check the packet.

## 1. The system

Ask which system they will test: one of their own (any AI system or
project, such as a set of skills and the application they make up, or
their AI 5100 assistant) or the *class assistant*, Wren, Morgan Reyes's
assistant (made up). The brief: "There is no penalty for this: a project on the class
assistant can earn full marks". Remind them to use only material they may
share with the class and with AI tools.

**A system of their own needs `system.md`**, 200 to 400 words, "so that
someone who has never seen the system could judge its outputs without
asking you." Ask its six points one at a time, in the brief's words: who
uses it and what for; what goes in and what comes out; its parts and where
the product or stage and the process sit among them; one typical request
and the result it should give; the rules or background needed to judge an
output; what they took out or made up to keep private details out. Then
offer to draft `../my-suites/system.md` from their answers, in their
words. Head it `Draft from my answers, written by Claude: to rewrite in my
own words.` Say that they should rewrite it. Log it.

## 2. What the suites test

Explain the three objects in a line each, from the brief:

- a *product*: an output judged by what it is (a reply, a summary, a JSON
  record);
- a *stage*: one step of a system with several, judged by what it hands on
  to the next step;
- a *process*: the way the work was done, judged from its record (the steps
  an agent took, the tools it called, the checks it ran before it answered).

Ask which product or stage the first suite tests. Then ask which process
the second tests. On the class assistant the brief suggests its replies (a
product), its searches of the knowledge graph before it replies (a stage)
and its recorded sessions (a process).

## 3. Gather the instances (at least six)

Each instance is a folder, `../my-suites/product/<item>/` (or
`stage/<item>/`), named in small letters, digits and dashes (`reply-1`).
It holds:

- `output.md`: the instance itself (another file name if the suite says
  `file:`);
- `context.md`: "what it was asked to do, from what input, and what it is
  for", with the input itself if it is short. Write it with the student.

Where to find them:

- **Their own system**: outputs they have saved. Ask where, look with them,
  and copy each one in only after they say yes. A file that isn't text (a
  deck, a PDF, a spreadsheet): the brief asks for a text version as
  `output.md`, the real file in `../my-suites/files/`, named in
  `context.md`.
- **The class assistant**: the recorded runs that come with Skill Eval Lite,
  `examples/recorded/*/outputs/<prompt>/<round>/<repeat>/output.md`, with
  each request in `examples/recorded/*/prompts/<prompt>/`; the runs of the
  student's Shared I group, in `runs/<name>/outputs/`; or new runs of Wren.
  The worked example's six board drafts come from these recorded runs. If
  the student copies the worked example, say plainly that its tests and
  controls are the example's: the brief asks them to design their own.

Where a test will look for a behaviour, the brief asks for instances "where
the behavior should happen and cases where it shouldn't". Say so now, so
that the six aren't all one kind.

## 4. Gather the process records (at least three)

Each run is a folder, `../my-suites/process/<item>/`, with `context.md`
(what the run was asked to do) and its record: `transcript.jsonl` (a
Claude Code or Codex session's events) or `trace.jsonl` (one step a line:
`{"tool", "detail", "error"}`). Its output, if any, goes beside them as
`output.md`.

**Their own Claude Code sessions.** Claude Code keeps each session as a
`.jsonl` file under `~/.claude/projects/`, in a folder named after the
project's path. The helper beside this skill lists them without printing
what is in them:

    python3 .claude/skills/suites-intake/case.py sessions ../their-system

(with no folder, it lists every project that has sessions). Each line gives
the date, the size, the number of steps and the first words of the first
request. Ask the student which sessions did the task; read nothing else.
Then, with their yes, copy each one:

    python3 .claude/skills/suites-intake/case.py copy ~/.claude/projects/<folder>/<session>.jsonl ../my-suites/process/<item>

This keeps only the session's `user` and `assistant` lines, which hold
every step the runner reads; the rest is the app's own bookkeeping, which
can hold their settings and instructions. For a Codex session or another
tool's log, ask where it is and copy it in as `transcript.jsonl` or
`trace.jsonl`. Then `suite --check` says whether it reads.

**The class assistant**: the recorded runs' `trace.jsonl` beside each
`output.md` above or the sessions in `examples/recorded/*/transcripts/`
(`<prompt>__<round>__<repeat>.jsonl`, copied as `transcript.jsonl`).

**Then the student reads each record for anything private.** Run

    python3 .claude/skills/suites-intake/case.py private ../my-suites/process

It lists, masked, lines that hold their home folder's path, an e-mail
address or something that looks like a key. Go through them with the
student. Change what they choose, with their yes, to a made-up stand-in,
and note what was taken out: the brief asks for it in the packet's
`README.md`. Say that a name or a detail the helper can't see may be
private too, so they should read each record themselves.

## 5. The tests

Each suite needs at least three tests, one of each kind. The brief: "The
design is the choice of which question goes to which kind of test." Explain
the kinds in a line each:

- *mechanical*: a program decides it (a word limit, a field present, a
  forbidden phrase, an allowed list of tools, a step before another);
- *LLM*: a model judges a criterion that needs reading and context;
- *human*: a person judges what needs context, experience or taste.

For each test, offer two or three candidate questions drawn from their
instances, then ask the student to choose one and to word, in their words:

- `id`: small letters and dashes (`reply-length`, `process-allowed-tools`);
- `question`: what it asks of each case;
- `criterion`: what counts as a pass (or the scale, with what each point
  means). Test it with them: "Would two people reach the same verdict on the
  same case?" If not, ask them to sharpen it;
- `why`: why this kind of test suits this question.

Then each kind's own fields:

- **Mechanical**: a built-in check, `check: {kind: ..., ...}`, one of
  `contains` (`text`), `not-contains` (`text`), `matches` (`pattern`),
  `word-count` (`min`, `max`), `json-parses`, `trace-ran-command`
  (`pattern`, on a process) and `trace-no-tool-outside` (`allowed`, on a
  process): README "The experiment file" says how each works. A trace
  check's pattern is a glob that matches a *whole* command, not a part of
  one: `kb/kb search*`, not `kb search`. Before you write one, print a
  record's steps (`python3 .claude/skills/suites-intake/case.py steps
  ../my-suites/process/<item>`) and write the
  pattern from a command that is really there. Or a
  program, `program: tests/<id>/check.py`: hand over to `/check-authoring`.
- **LLM**: `prompt: tests/<id>/prompt.md` (or `skill: tests/<id>/SKILL.md`),
  `model` and `decision`: hand over to `/llm-test` for the prompt.
- **Human**: `form` (`rating` or `comparison`), `scale` (each point and what
  it means, with an example for the top and bottom points), `pass_at` (the
  lowest passing rating), `instructions: tests/<id>/instructions.md`.
  Offer to draft the instructions from their scale and criterion, for a
  classmate to follow "without asking you"; they read and change it.

## 6. Write suites.yaml

Write `../my-suites/suites.yaml` in the worked example's shape:

```yaml
schema: skill-eval-lite/suites@1
title: <a line saying what the two suites test>

suites:
  - id: <suite-id>
    object: product            # or stage or process
    what: >
      <what this suite tests, from which system; where the cases came from>
    file: output.md
    items: [reply-1, reply-2, reply-3, reply-4, reply-5, reply-6]
    tests:
      - id: <test-id>
        kind: mechanical
        question: <...>
        criterion: <...>
        why: <...>
        check: {kind: word-count, max: 150}
```

The file reads a small part of YAML: mappings, lists, quoted and plain
values, `|` and `>` blocks. Quote any value with `: ` or `#` in it. Show the
student the whole file before you write it.

Then check it (no prompt, no model):

    python3 run_ab.py suite ../my-suites/suites.yaml --check

It prints either `Nothing to fix.` with each suite's count of cases and
tests. Or it prints `The suites file can't be run yet.` with a line for
each problem. Its `note:` lines say what the brief asks for and is still
missing ("the brief asks for a reference, two planted faults and two
harmless variations", "at least six"). An LLM test's prompt or a program
not yet written shows as `does not exist`: that is expected until
`/llm-test` and `/check-authoring` have made them. Explain each line, fix
what is yours to fix. Check again.

## 7. Before you finish

- [ ] The system is chosen; `system.md` is drafted and marked if it is
      their own.
- [ ] At least six instances, each with `context.md`; at least three runs,
      each with a record that `suite --check` reads.
- [ ] Every record has been read by the student for anything private.
- [ ] Each suite has a test of each kind, each with its own question, a
      criterion and a reason, worded by the student.
- [ ] `suite --check` has no problem left but files still to be written.

Tick what is done in `../ai5500-personal-1/progress.md`, add a line to its
`ai-use-log.md` (the date, Claude Code and its model, what you did, the
files you wrote, what the student checked). Then say what comes next: the
control cases (`/control-cases`), then the programs (`/check-authoring`)
and the LLM tests' prompts (`/llm-test`).

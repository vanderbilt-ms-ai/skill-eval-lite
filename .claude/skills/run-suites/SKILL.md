---
name: run-suites
description: Run Personal I's suites with the student in Skill Eval Lite, in the order that keeps their judgment first - run_ab.py suite --check, the mechanical tests (--no-llm), the student's reference judgments in the wizard, then the LLM tests on their plan, then the human tests with a second rater; read each suite report with them (the controls table, the agreement); run again after a test changes; run a classmate's packet in the exchange. Use when a student wants to run or rerun their suites or one test, read a suite report, get a second rater's judgments in or run a classmate's packet.
---

<!-- skill-eval-lite run-suites, version 2 (Skill Eval Lite 0.2.3) -->

# Running the suites

You are helping one student run Personal I's two suites and read what they
show: the brief's sixth and seventh steps. It also runs a classmate's
packet in the exchange, if the student does it (it is optional, for extra
credit).
The runner, `run_ab.py suite`, runs the mechanical and LLM tests on every
case and writes a report a suite. The wizard collects the student's own
judgments.

## How you work

- **The student types no commands.** You run each one. First say in a line
  what it does, how long it takes and whether it uses their plan; then run
  it. The app asks the student before anything that changes a file or uses
  their plan: that is their yes. Run each command on its own, as written
  here (no chains, no `| tail`: the runner prints what matters). On Windows,
  use `py` where this says `python3`.
- **Where things are.** You work in Skill Eval Lite's folder. The packet is
  `../my-suites`; the brief folder is `../ai5500-personal-1`.
- **Their judgment first.** The brief: "before you read the model's
  responses, judge the same criterion yourself on the same instances". The
  runner prints each LLM verdict as it runs, so an LLM test runs only after
  the student has made their reference judgments for it (step 3). Never
  read out, sum up or hint at an LLM test's verdicts, runs or report column
  before then. The ratings and the reasons are the student's; never make
  them. Never suggest one for a case.
- **Keep every row.** Rows in `judgments.csv` are only ever added. The
  wizard forgets its judgments when it loads another bundle, so bring its
  `judgments.csv` back into the packet before you load another bundle or
  run `suite` again.
- **Plain words.** Short messages, one question at a time. Never send, post
  or push anything.

## 1. Check the packet

    python3 run_ab.py suite ../my-suites/suites.yaml --check

No prompt, no model. It should end `Nothing to fix.`, with each suite's
cases and tests. Otherwise fix each line with the student
(`/suites-intake`, `/control-cases`, `/llm-test` or `/check-authoring`),
and check again.

## 2. The mechanical tests

    python3 run_ab.py suite ../my-suites/suites.yaml --no-llm

It runs every mechanical test on every case, instances and controls alike,
and calls no model: a few seconds. It adds a row a result to
`judgments.csv`, writes `bundle.json` for the wizard and a report a suite in
`reports/`, then prints a table a suite, a column a test (`-` where a test
hasn't run). Read the mechanical columns with the student now: which
planted faults each one caught and any instance it failed.

## 3. The student's reference judgments

For each LLM test that has no reference judgments yet, hand over to
`/wizard`:

1. Load `../my-suites/bundle.json` in step 1.
2. In step 2, *Reference*, the student types their initials, picks an LLM
   test and chooses *Pass*, *Unknown* or *Fail* for every case, with a
   one-line reason. The wizard hides the LLM's answers until they have
   judged every case.
3. In step 4, *Report*, *Export judgments.csv*. It holds every row, the
   runner's and theirs. Bring it back into `../my-suites/`.

Then check that the reference is in: in `../my-suites/judgments.csv`, each
LLM test should have a row for every case with `check` set to
`<test>-reference`. Count them; say the count, nothing else.

## 4. The LLM tests

Say first how many runs it makes (each LLM test times its suite's cases,
less those already run for the test's current version), that each is a
fresh, isolated Claude Code session on the student's plan, a few seconds
each. Say that the verdicts will show as they come. Then:

    python3 run_ab.py suite ../my-suites/suites.yaml

It prints `LLM tests: <n> runs with Claude Code, 4 at a time.`, a line a
run with its verdict, the tables again, then where it added the rows and
the reports. Every run is kept as it happened in
`tests/<test>/runs/<case>__<time>.json` (its input, the full response, the
model, the date, the test's version and the decision read from it).

- To run one test only (the 10 November checkpoint asks for "one test of
  each kind run, at least one of them on the process"), add
  `--tests <test-id>`: only that test runs. `--suite <suite-id>` runs one
  suite.
- A test already run for its current version is not run again. `--again`
  runs it again; ask first, since it uses the plan.
- `not logged in`: hand over to `/get-ready`. `STOPPED: an LLM test's run
  was not isolated`: don't run again; tell the student to report it to the
  instructor with their Claude Code version.

## 5. The human tests

Hand over to `/wizard`, with the `bundle.json` the last run wrote:

1. **The second rater.** The brief asks for one classmate to judge on their
   own. The classmate needs a `bundle.json` that holds none of the
   student's ratings: the one the last `suite` run wrote, before the
   student's ratings were brought back and `suite` was run again. Send it
   before or after the student rates, as long as it is that bundle. The
   classmate loads it in their own wizard, rates in step 3 under their
   initials and sends back their `judgments.csv`.
2. **The student's ratings.** Step 3, *Human tests*: their initials, then
   each case, shuffled with the controls mixed in, rated with a one-line
   reason.
3. In step 4, *Import a classmate’s judgments.csv* when it comes, then
   *Export judgments.csv*. Bring it back into `../my-suites/`.

## 6. The reports

Once the wizard's rows are back, write the reports again from every row:

    python3 run_ab.py suite ../my-suites/suites.yaml --no-llm

No model (it runs the mechanical tests again, which adds their rows). Each
suite's report is `../my-suites/reports/<suite>-<version>.md`. Read it with
the student, part by part:

- **The table**: a row a case, a column a test. A human test's cell lists
  each rater's rating with their initials.
- **Failures** and **Where the tests disagree on the same case**.
- **Controls: did each test do what the control expects?** `ok (fail, got
  fail)` is right. `MISSED (fail, got pass)` is a finding. `shows nothing:
  the test fails reference too` means the control can't show anything until
  the reference passes: look at the reference first. `?` means no result
  yet; `-` means the control expects anything.
- **Agreement**: the LLM and the student's reference ("agree on 9 of 11
  cases", with each disagreement listed) and the two raters ("gave the
  same answer on 8 of 11 cases, within one point on 10").

The brief: "A test that didn't move when it should have, or moved when it
shouldn't have, is a finding: please look at why before you trust its other
results." For each `MISSED`, open the case and the result's reason with the
student. Ask what they think went wrong: the test, the control or the
criterion. For at least one disagreement between the LLM and their
reference, read the run's response together: "who was right, and why?" The
answers are theirs.

**After a change.** A changed test is a new version: run step 4 again (only
the changed test's LLM runs are made) and step 6. Reports are named by the
suite's version, so the old report stays: the brief asks for "each suite's
report, for each version of the suite you ran".

## 7. A classmate's packet (the optional exchange)

Only if the student has chosen to do the exchange, with a partner they
found themselves in `#ai-5500` on Slack. The brief: "Run their suites from
their packet and check that you get their reports, follow their human
instructions on two or three cases, and write the strongest objection you
have to one of their tests".

1. Unzip their packet beside this folder, as `../peer-<their initials>/`.
2. **Read their programs first**, with the student: a mechanical test's
   program runs on this computer. Run nothing you haven't both read.
3. `python3 run_ab.py suite ../peer-<initials>/suites.yaml --check`
4. Run it in a copy, so their own rows and reports stay as they sent them:

       python3 run_ab.py suite ../peer-<initials>/suites.yaml --out ../peer-<initials>-rerun

   Their LLM tests run on the student's plan: say how many first.
5. Compare `../peer-<initials>/reports/` with `../peer-<initials>-rerun/reports/`:
   the mechanical columns should match exactly; an LLM test may differ from
   run to run. Say where they differ.
6. Their human instructions: `/wizard`, with `../peer-<initials>-rerun/bundle.json`
   (it has none of their ratings), two or three cases in step 3.
7. The objection is the student's. `/critique` can list what it notices in
   their tests; the student chooses one and writes it, at least one on the
   process suite.
8. When the partner's objection comes, the student responds: they revise
   the test and keep both versions (step 6, "After a change"), or say why
   it stands. The objection they received, their response and the review
   they gave go in `../my-suites/peer-review.md`. All three are the
   student's.

## 8. Before you finish

- [ ] The student's reference was made before each LLM test ran.
- [ ] Every case has a result from every mechanical and LLM test.
- [ ] The student's ratings and the second rater's are in `judgments.csv`.
- [ ] A report for each suite, written after the last rows came in.
- [ ] Each `MISSED` control and one disagreement read with the student.

Tick what is done in `../ai5500-personal-1/progress.md`, add a line to its
`ai-use-log.md` (the date, Claude Code and its model, what you ran, how many
LLM runs, what the student checked). Then say what comes next: a fix to a
test that missed, `/critique` or the report (the student's), then
`/packet`.

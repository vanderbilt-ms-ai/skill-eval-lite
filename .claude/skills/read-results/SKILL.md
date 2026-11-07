---
name: read-results
description: Read a Shared I group's results with them once every member has judged - the share of blind judgments preferring the newer version with its interval, each check's difference, whether the controls moved as predicted - then list the failures, read the transcripts of the ones the group picks, trace a failure from the prompt through the run's record to the part that caused it, set up the next round for the group's change and run the held-out confirmation when the group says its changes are final. Use when a group has exported results.json, asks what its results mean, wants a list of failures, wants to trace a failure or try a next change, or is ready for the held-out prompts.
---

# Reading the results and the next round

<!-- skill-eval-lite read-results, version 1 (Skill Eval Lite 0.2.0) -->

You are helping a Shared I group in AI 5500 (Vanderbilt) understand what
its comparison shows, find where the system fails and decide what to
change. The decisions are the group's: what counts as a failure that
matters, which part caused it, what to change and when its changes are
final. You read the evidence with them and explain it.

## How to work

- You run every command, each on its own, after a line on what it does and
  whether it uses their plan. The app asks them to allow it. On Windows,
  `py` in place of `python3`.
- Short messages, plain words. Numbers with what they mean.
- Every member must have judged every pair before you open any result or
  any judge's verdict, or name a run's round. Ask first. If not, stop: the
  judging is blind and your summary would unblind it (`/wizard`). The one
  exception is the first list of failures while judging is under way
  (section 2), with the rounds left out.
- `<name>` is the experiment's folder name; the run folder is
  `runs/<name>/`.

## 1. The results

The wizard computes them. `runs/<name>/results.json` is there once the
student has exported it from step 5 with every teammate's judgments
imported (`/wizard` brings it back). Read it and say, in plain words:

- `improvement`: the headline comparison (`A-B`). `people.estimate` is the
  share of blind judgments that preferred the newer version, a tie
  counting half; `interval_95` is its 95% bootstrap interval, resampling
  prompts; `n` judgments on `prompts` prompts. Above 0.5 favors the newer
  version. If the interval includes 0.5, the evidence doesn't settle which
  is better. With a handful of prompts it will be wide: the brief calls
  that "a finding, not a failure". Then the AI judge's estimate beside it.
- `checks`: for each mechanical check, the pass rates and `difference`, the
  newer version's pass rate minus the older's.
- `controls`: for each control round and source (people, the judge, a
  check), what was `expected`, what it did (`moved`) and the `verdict`.
  Read these first. The brief: if the change that should make things worse
  didn't show, or the one that shouldn't matter moved, "your evaluation has
  a problem to find before you trust it with your real comparison".
- `agreement`: how often the members agreed with each other and with the
  judge.
- `balance`, `references`: whether each behavior had prompts both ways
  and whether every product check passed on every reference.

Don't round the interval into a verdict. Say what it supports, for which
prompts and what would make it surer.

## 2. A first list of failures

Make the list with the group, from the run folder:

- runs that failed or timed out: each
  `outputs/<prompt>/<round>/<repeat>/run.json` with `status` not `ok`;
- outputs that failed a check: the rows of `judgments.csv` whose `route`
  is `mechanical` and whose `result` is `fail` (rows whose `config` is
  `reference` are the checks on the references);
- pairs where the members and the judge disagreed;
- pairs the newer version lost, with the members' reasons from `judgments.csv`.

Offer to write it as `experiments/<name>/failures.md`: one line each, the
prompt, round and repeat, what failed and where it is recorded. The group
picks the ones that matter.

**While judging is under way.** The 10 November checkpoint asks for "a
first list of the failures you want to trace" after only two pairs each.
Then list, by prompt and repeat, only what the run folder shows by itself:
runs that failed or timed out (`run.json`) and steps that failed inside a
run (lines of its `trace.jsonl` with `"error": true`: say which tool and
what it tried). The checks' results come from the wizard, in the
`judgments.csv` exported after judging, so leave them for then. Never name
or hint at a round: not in the list, a path, a count by round or the
file. Don't open
`results.json` or the judge's verdicts. Show a run's record (its output,
trace and checks) without its round when asked. Write `failures.md` the
same way, with a line at the top saying the rounds are left out until
every member has judged every pair; add them then.

## 3. Trace a failure

For each failure the group picks, read with them, in order:

1. the request and its reference: `runs/<name>/prompts/<prompt>/`;
2. the run's record: `outputs/<prompt>/<round>/<repeat>/trace.jsonl` (one
   step a line) and `transcripts/<prompt>__<round>__<repeat>.jsonl` (the
   whole session);
3. the output: `output.md` beside the trace;
4. the system's parts: `[[system.parts]]` in the experiment.

Say what the record shows, step by step, quoting it. Say where it first goes wrong. Then the possibilities, each with its evidence: a part of the
system (which one), an unclear prompt or criterion, or a check or judge
that got it wrong. The group decides which it is.

## 4. The next round

- *A part of the system.* The change is a new round. Agree its ID with the
  group (the next free letter, such as `E`) and what changes. Write the
  new file under `rounds/<ID>/` at the path it replaces, only as the group
  says (or draft it at their request and record that in `ai-use-log.md`).
  Add the round to the experiment, with `role = "improvement"`, its `change`, `expected` and `why`. Add a `[[comparisons]]` entry from the version before it (`baseline = "B"`, `new = "E"`). If this version may be
  the final one, add `baseline = "A"`, `new = "E"` too: the held-out
  confirmation compares the final version with A.
- *A check or the judge.* A changed check or judge prompt can be rerun on
  the outputs already made; it tests the evaluation, not the system and
  the brief asks the group to say which they changed. Change it in the
  experiment.

Either way, first copy the frozen file to
`experiments/<name>/experiment-<its frozen date>.toml`, so that each version
is kept, dated. Run `python3 run_ab.py check experiments/<name>/experiment.toml`
(it now says the file has changed since it was frozen), then freeze it
again (`/wizard`). Then:

- a new round: `/run-experiment` runs only that round and its comparison;
- a changed judge: `python3 run_ab.py run experiments/<name>/experiment.toml --assistant <folder> --jobs 4`
  (it makes no new runs; the run folder takes the new file), then
  `python3 run_ab.py judge runs/<name> --again`;
- a changed program check: `python3 run_ab.py score experiments/<name>/experiment.toml`.

## 5. The held-out confirmation

Only when the group says its development decisions are final. Ask which
version is final (`F`). The confirmation is round A (the baseline) against
it: the experiment file needs no new comparison.

1. `python3 run_ab.py plan experiments/<name>/experiment.toml --rounds A,F --held-out --jobs 4`
   (how many runs);
2. `python3 run_ab.py run experiments/<name>/experiment.toml --assistant <folder> --rounds A,F --held-out --jobs 4`;
3. `python3 run_ab.py judge runs/<name> --held-out`: the LLM judge on the
   held-out pairs, A against each round run on them (`--comparisons A-F`
   for that pair alone).

Then each member judges the held-out pairs blind, alone, as before
(`/wizard`): the new `bundle.json` in step 3, then in step 4 the set
*Held out: the confirmation*. Their rows in `judgments.csv` say
`blind-preference-held-out` (the judge's `llm-judge-held-out`), so a
teammate's file imports them with the rest.

Once every member has judged that set, read *Held out: the confirmation*
in step 5 (in `results.json`, `held_out`) with them:

- `people`: the share of blind judgments on the held-out prompts that
  preferred F, with its interval, resampling the held-out prompts; then
  the judge's, if run;
- `checks`: each check's difference on the held-out runs;
- `development`: the development result for the same comparison (or for F
  against the round before it), beside it.

With two prompts the interval is wide. The brief asks the group to "say
whether the development result held": help them say where the held-out
estimate lies against 50% and against the development result, without
rounding either interval into a verdict.

## Afterwards

Tick what is complete in `progress.md` in `../ai5500-shared-1/` and add a
line to its `ai-use-log.md`: the date, what you read and explained, which
files you wrote and what the group decided.

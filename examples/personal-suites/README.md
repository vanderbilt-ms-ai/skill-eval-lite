# Personal I, a worked example: two suites on the class assistant

A packet in the shape Personal I asks for, for Skill Eval Lite's checks-only
mode. Everything in it is about Wren and Morgan Reyes, who are fictional.

- `suites.yaml`: the two suites, `board-drafts` (a product: six drafts for
  the Riverside board) and `graph-briefs` (a process: four recorded runs that
  prepared a brief), with three tests each: mechanical, LLM and human.
- `product/<item>/` and `process/<item>/`: the instances and the runs, each
  with `context.md` (what it was for). The runs keep their transcripts.
- `controls/<suite>/<case>/`: for each suite a reference, two planted faults
  and two harmless variations, each with `expect.json` (its role, the case
  it was made from, and what each test should do).
- `tests/<test>/`: the LLM tests' prompts, the human tests' instructions, and
  the mechanical program `search-before-write/check.py`. The other
  mechanical test, `no-shorthand`, is a built-in check in `suites.yaml`.
  The program reads a case's record as the built-in checks do
  (`transcript.jsonl`, or else `trace.jsonl`), and prints `n/a` when a case
  has neither: with nothing to test, it is not a failure. A program of your
  own should do the same.

To rerun it, from Skill Eval Lite's folder:

    python3 run_ab.py suite examples/personal-suites/suites.yaml --out runs/personal-suites

That runs every mechanical and LLM test on every case, adds a row per result
to `runs/personal-suites/judgments.csv`, keeps every LLM run under
`tests/<test>/runs/`, and writes a report per suite under `reports/`. Then
load `runs/personal-suites/bundle.json` in the wizard for the human tests and
your own reference judgments.

The instances are real outputs of the class assistant, made on 2026-10-26;
the control cases' drafts and traces were written by hand.

## What the real runs found

### The first run (26 October)

The LLM tests were first run for real on eight cases (2026-10-26,
`examples/recorded/personal-suites/`). Two of the control cases did not do
what they were meant to. That run is kept as it was, as a worked example of
the brief's advice that a test that misses a control is a finding to look
into before you trust its other results:

- **`facts-match-the-source` failed the board suite's reference.** The
  reference (the class intake's) got three facts wrong against the meeting
  notes. It named "Ellis Park", where the notes say only "Ellis". It said
  "the committee asks the full board to decide", where the notes say Tom
  suggested the transfer and that it is "not ours to decide, goes to full
  board 19 Nov". And it said that next summer's camp supplies "were bought
  in September", where the notes ask it ("bought in Sept?") for Ellis to
  confirm. (The third was found on 3 November.) The reference was wrong, so
  the test's failures on the real drafts couldn't be read yet.
- **`steps-follow` failed the variation `variation-skill-route`.** The
  variation was meant to reach the reference's result by a different, valid
  route. But it drops the search whose result gave the 50,000 review
  threshold, so the brief's "above the 50,000 that Dana reviews" has no
  source in its trace. The test was right: the control was not harmless.
  It is still in the packet, as it was.

### What that meant for the controls (3 November)

A control copied from the reference carries the reference's facts.
`fault-shorthand`, `fault-wrong-date` and both variations failed
`facts-match-the-source` for the reference's reasons. So while the
reference was wrong, they showed nothing about the test: even
`fault-wrong-date`'s "ok" didn't show that the test catches the changed
dates, since it would have failed that case whatever its dates. Since 0.1.3
the report says so. A control made from a reference that fails a test reads
`shows nothing: the test fails reference too`, with a note under the
table. A planted fault can name the case it was made from
(`"varies": "reference"`), as both board faults now do.

### What was changed, and the second run (3 November)

The reference and the four controls made from it now say what the notes
say: "Ellis"; Tom's suggestion, for the full board to decide on 19
November; and the camp supplies' timing, for Ellis to confirm.
`fault-shorthand` expects `facts-match-the-source` to give what it gives on
the reference. The board suite was then run again for real, on all eleven
cases (2026-11-03, `examples/recorded/personal-suites-2026-11-03/`, $0.16
with `claude-sonnet-5-5`). The reference passed; both variations and
`fault-shorthand` passed with it; and `fault-wrong-date` failed, on its two
changed dates. Every board control now does what it expects. Four of the
six real drafts failed (`summary-2`, `summary-3`, `note-1`, `note-2`):
`summary-2`, for example, gives Ellis's confirmation of the supplies a
deadline the notes don't give it. Now that the test has shown it can be
trusted on its controls, those failures are findings about the drafts.

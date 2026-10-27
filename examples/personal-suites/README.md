# Personal I, a worked example: two suites on the class assistant

A packet in the shape Personal I asks for, for Skill Eval Lite's checks-only
mode. Everything in it is about Wren and Morgan Reyes, who are fictional.

- `suites.yaml`: the two suites, `board-drafts` (a product: six drafts for
  the Riverside board) and `graph-briefs` (a process: four recorded runs that
  prepared a brief), with three tests each: mechanical, LLM and human.
- `product/<item>/` and `process/<item>/`: the instances and the runs, each
  with `context.md` (what it was for). The runs keep their transcripts.
- `controls/<suite>/<case>/`: for each suite a reference, two planted faults
  and two harmless variations, each with `expect.json` (its role, the case a
  variation varies, and what each test should do).
- `tests/<test>/`: the LLM tests' prompts, the human tests' instructions, and
  the mechanical program `search-before-write/check.py`. The other
  mechanical test, `no-shorthand`, is a built-in check in `suites.yaml`.

To rerun it, from Skill Eval Lite's folder:

    python3 run_ab.py suite examples/personal-suites/suites.yaml --out runs/personal-suites

That runs every mechanical and LLM test on every case, adds a row per result
to `runs/personal-suites/judgments.csv`, keeps every LLM run under
`tests/<test>/runs/`, and writes a report per suite under `reports/`. Then
load `runs/personal-suites/bundle.json` in the wizard for the human tests and
your own reference judgments.

The instances are real outputs of the class assistant, made on 2026-10-26;
the control cases' drafts and traces were written by hand.

## What the first real run found

The LLM tests were first run for real on eight cases (2026-10-26,
`examples/recorded/personal-suites/`). Two of the control cases did not do
what they were meant to, and both are left as they were, as a worked example
of the brief's advice that a test that misses a control is a finding to look
into before you trust its other results:

- **`facts-match-the-source` failed the board suite's reference.** The
  reference (the class intake's) names "Ellis Park", but the meeting notes
  only say "Ellis"; and it says "the committee asks the full board to
  decide", where the notes say the transfer is not the committee's to
  decide. Is the reference wrong, or is the criterion stricter than the
  owner would be? Either way, one of them has to change before the test's
  failures on the real drafts mean anything.
- **`steps-follow` failed the variation `variation-skill-route`.** The
  variation was meant to reach the reference's result by a different, valid
  route. But it drops the search whose result gave the 50,000 review
  threshold, so the brief's "above the 50,000 that Dana reviews" has no
  source in its trace. The test was right: the control was not harmless.

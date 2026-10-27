# Suite report: graph-briefs

Object: process. Suite version 76099c553d55 (search-before-write defc51d7652d, steps-follow 267aad2a7198, sound-process 26a902681f5f). Written 2026-10-26T21:55:02Z by skill-eval-lite 0.1.0.

How Wren prepares a brief about a person or a funder: whether it looks things up in the knowledge graph before it writes, and writes only what it found. Four real runs from the class assistant's demonstrations, two of them made with the knowledge graph removed.

| Case | Role | search-before-write (mechanical) | steps-follow (llm) | sound-process (human) |
| --- | --- | --- | --- | --- |
| dana-brief-1 | instance | pass | not run | not rated |
| dana-brief-2 | instance | pass | fail | not rated |
| priya-brief-1 | instance | pass | not run | not rated |
| priya-brief-2 | instance | pass | not run | not rated |
| fault-no-search | planted fault | fail | not run | not rated |
| fault-out-of-order | planted fault | fail | fail | not rated |
| reference | reference | pass | pass | not rated |
| variation-other-words | harmless variation | pass | not run | not rated |
| variation-skill-route | harmless variation | pass | fail | not rated |

## Failures

- dana-brief-2, steps-follow: fail (The brief's "not found" rows are supported: step 1 shows `kb/kb` is missing, and step 3 shows `Grants/` and `notes/` don't exist. But its "Known standing facts )
- fault-no-search, search-before-write: fail (no lookup before the first write (step 1))
- fault-out-of-order, search-before-write: fail (no lookup before the first write (step 1))
- fault-out-of-order, steps-follow: fail (The only write of the brief is step 1, which created notes/dana-checkin.md before any lookup (steps 2-4) had run, and no later step updated it. The content matc)
- variation-skill-route, steps-follow: fail (The lookups (steps 2 and 3) come before the write (step 4), and most of the brief traces to them: the two open items, 120,000 over two years, the 1 December due)

## Where the tests disagree on the same case

- dana-brief-2: search-before-write pass, steps-follow fail
- variation-skill-route: search-before-write pass, steps-follow fail

## Controls: did each test do what the control expects?

| Test | fault-no-search (planted fault) | fault-out-of-order (planted fault) | reference (reference) | variation-other-words (harmless variation) | variation-skill-route (harmless variation) |
| --- | --- | --- | --- | --- | --- |
| search-before-write | ok (fail, got fail) | ok (fail, got fail) | ok (pass, got pass) | ok (same as reference, got pass) | ok (same as reference, got pass) |
| steps-follow | ? (fail; got nothing) | ok (fail, got fail) | ok (pass, got pass) | ? (same as reference; got nothing) | MISSED (same as reference, got fail) |
| sound-process | ? (fail; got nothing) | ? (fail; got nothing) | ? (pass; got nothing) | ? (same as reference; got nothing) | ? (same as reference; got nothing) |

## Agreement

- steps-follow: no reference judgments yet.
- sound-process: 0 raters so far; agreement needs two.

# Suite report: board-drafts

Object: product. Suite version 2633fbe58565 (no-shorthand ade684519f16, facts-match-the-source aa0ecc4a070a, sendable 25a4e6282bc0). Written 2026-10-26T21:55:02Z by skill-eval-lite 0.1.0.

Drafts that Wren writes for the Riverside board or its finance committee, which Morgan sends under their own name. Six real drafts, made by the class assistant's demonstration runs on 2026-10-26.

| Case | Role | no-shorthand (mechanical) | facts-match-the-source (llm) | sendable (human) |
| --- | --- | --- | --- | --- |
| summary-1 | instance | fail | not run | not rated |
| summary-2 | instance | pass | fail | not rated |
| summary-3 | instance | fail | not run | not rated |
| summary-4 | instance | fail | not run | not rated |
| note-1 | instance | fail | not run | not rated |
| note-2 | instance | pass | not run | not rated |
| fault-shorthand | planted fault | fail | not run | not rated |
| fault-wrong-date | planted fault | pass | fail | not rated |
| reference | reference | pass | fail | not rated |
| variation-reformatted | harmless variation | pass | not run | not rated |
| variation-reworded | harmless variation | pass | fail | not rated |

## Failures

- summary-1, no-shorthand: fail (found: Q1)
- summary-2, facts-match-the-source: fail (One fact in the draft does not match the source.  - **Ellis's timing confirmation, "Tuesday 10 November, with the corrected actuals" (Who does what, item 2).** )
- summary-3, no-shorthand: fail (found: Q1)
- summary-4, no-shorthand: fail (found: Q1)
- note-1, no-shorthand: fail (found: Q1)
- fault-shorthand, no-shorthand: fail (found: Q1, cttee)
- fault-wrong-date, facts-match-the-source: fail (Facts that do not match:  1. **Corrected Q1 actuals deadline:** the draft says Ellis sends them by Tuesday 17 November. The source says by Tue 10 Nov. 2. **Next)
- reference, facts-match-the-source: fail (Facts that do not match:  1. **"Ellis Park"**: the source only says "Ellis" and gives no surname. Tom Becker and Alicia Moreno have surnames in the source, but )
- variation-reworded, facts-match-the-source: fail (Facts that do not match:  - **"Ellis Park"**: the source only says "Ellis" and gives no surname, so "Park" is added. - **"next summer's camp supplies were bough)

## Where the tests disagree on the same case

- summary-2: no-shorthand pass, facts-match-the-source fail
- fault-wrong-date: no-shorthand pass, facts-match-the-source fail
- reference: no-shorthand pass, facts-match-the-source fail
- variation-reworded: no-shorthand pass, facts-match-the-source fail

## Controls: did each test do what the control expects?

| Test | fault-shorthand (planted fault) | fault-wrong-date (planted fault) | reference (reference) | variation-reformatted (harmless variation) | variation-reworded (harmless variation) |
| --- | --- | --- | --- | --- | --- |
| no-shorthand | ok (fail, got fail) | ok (pass, got pass) | ok (pass, got pass) | ok (same as reference, got pass) | ok (same as reference, got pass) |
| facts-match-the-source | ? (pass; got nothing) | ok (fail, got fail) | MISSED (pass, got fail) | ? (same as reference; got nothing) | ok (same as reference, got fail) |
| sendable | - | ? (fail; got nothing) | ? (pass; got nothing) | ? (same as reference; got nothing) | ? (same as reference; got nothing) |

## Agreement

- facts-match-the-source: no reference judgments yet.
- sendable: 0 raters so far; agreement needs two.

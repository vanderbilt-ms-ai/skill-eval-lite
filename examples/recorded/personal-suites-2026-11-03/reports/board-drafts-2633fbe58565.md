# Suite report: board-drafts

Object: product. Suite version 2633fbe58565 (no-shorthand ade684519f16, facts-match-the-source aa0ecc4a070a, sendable 25a4e6282bc0). Written 2026-11-03T23:39:50Z by skill-eval-lite 0.1.2.

Drafts that Wren writes for the Riverside board or its finance committee, which Morgan sends under their own name. Six real drafts, made by the class assistant's demonstration runs on 2026-10-26.

| Case | Role | no-shorthand (mechanical) | facts-match-the-source (llm) | sendable (human) |
| --- | --- | --- | --- | --- |
| summary-1 | instance | fail | pass | not rated |
| summary-2 | instance | pass | fail | not rated |
| summary-3 | instance | fail | fail | not rated |
| summary-4 | instance | fail | pass | not rated |
| note-1 | instance | fail | fail | not rated |
| note-2 | instance | pass | fail | not rated |
| fault-shorthand | planted fault | fail | pass | not rated |
| fault-wrong-date | planted fault | pass | fail | not rated |
| reference | reference | pass | pass | not rated |
| variation-reformatted | harmless variation | pass | pass | not rated |
| variation-reworded | harmless variation | pass | pass | not rated |

## Failures

- summary-1, no-shorthand: fail (found: Q1)
- summary-2, facts-match-the-source: fail (One fact does not match:  - **Ellis's deadline to confirm the supplies overage (Who does what, item 2):** The draft says "Tuesday 10 November, with the correcte)
- summary-3, no-shorthand: fail (found: Q1)
- summary-3, facts-match-the-source: fail (Facts that do not match:  - **"Morgan: send the packet to the board by Thu 12 Nov."** The source says only "packet to board Thu 12 Nov" and names no owner. Only)
- summary-4, no-shorthand: fail (found: Q1)
- note-1, no-shorthand: fail (found: Q1)
- note-1, facts-match-the-source: fail (Facts that do not match:  1. **"first quarter (July to September)"**: Neither the request nor Ellis's email gives the months of Q1. The request says only "Q1" a)
- note-2, facts-match-the-source: fail (**Facts that do not match:**  1. **"July to September"**: The request says only "Q1" and the email gives no fiscal calendar. The draft adds the July-to-Septembe)
- fault-shorthand, no-shorthand: fail (found: Q1, cttee)
- fault-wrong-date, facts-match-the-source: fail (Mismatches found:  1. **Corrected Q1 actuals deadline**: the draft says Ellis sends them by "Tuesday 17 November". The source says by Tue 10 Nov. 2. **Next meet)

## Where the tests disagree on the same case

- summary-1: no-shorthand fail, facts-match-the-source pass
- summary-2: no-shorthand pass, facts-match-the-source fail
- summary-4: no-shorthand fail, facts-match-the-source pass
- note-2: no-shorthand pass, facts-match-the-source fail
- fault-shorthand: no-shorthand fail, facts-match-the-source pass
- fault-wrong-date: no-shorthand pass, facts-match-the-source fail

## Controls: did each test do what the control expects?

| Test | fault-shorthand (planted fault) | fault-wrong-date (planted fault) | reference (reference) | variation-reformatted (harmless variation) | variation-reworded (harmless variation) |
| --- | --- | --- | --- | --- | --- |
| no-shorthand | ok (fail, got fail) | ok (pass, got pass) | ok (pass, got pass) | ok (same as reference, got pass) | ok (same as reference, got pass) |
| facts-match-the-source | ok (same as reference, got pass) | ok (fail, got fail) | ok (pass, got pass) | ok (same as reference, got pass) | ok (same as reference, got pass) |
| sendable | - | ? (fail; got nothing) | ? (pass; got nothing) | ? (same as reference; got nothing) | ? (same as reference; got nothing) |

## Agreement

- facts-match-the-source: no reference judgments yet.
- sendable: 0 raters so far; agreement needs two.

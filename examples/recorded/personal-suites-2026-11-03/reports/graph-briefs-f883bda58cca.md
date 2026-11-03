# Suite report: graph-briefs

Object: process. Suite version f883bda58cca (search-before-write 47167ef80771, steps-follow 267aad2a7198, sound-process 26a902681f5f). Written 2026-11-03T23:39:50Z by skill-eval-lite 0.1.2.

How Wren prepares a brief about a person or a funder: whether it looks things up in the knowledge graph before it writes, and writes only what it found. Four real runs from the class assistant's demonstrations, two of them made with the knowledge graph removed.

| Case | Role | search-before-write (mechanical) | steps-follow (llm) | sound-process (human) |
| --- | --- | --- | --- | --- |
| dana-brief-1 | instance | not run | not run | not rated |
| dana-brief-2 | instance | not run | not run | not rated |
| priya-brief-1 | instance | not run | not run | not rated |
| priya-brief-2 | instance | not run | not run | not rated |
| fault-no-search | planted fault | not run | not run | not rated |
| fault-out-of-order | planted fault | not run | not run | not rated |
| reference | reference | not run | not run | not rated |
| variation-other-words | harmless variation | not run | not run | not rated |
| variation-skill-route | harmless variation | not run | not run | not rated |

## Failures

None.

## Where the tests disagree on the same case

Nowhere.

## Controls: did each test do what the control expects?

| Test | fault-no-search (planted fault) | fault-out-of-order (planted fault) | reference (reference) | variation-other-words (harmless variation) | variation-skill-route (harmless variation) |
| --- | --- | --- | --- | --- | --- |
| search-before-write | ? (fail; got nothing) | ? (fail; got nothing) | ? (pass; got nothing) | ? (same as reference; got nothing) | ? (same as reference; got nothing) |
| steps-follow | ? (fail; got nothing) | ? (fail; got nothing) | ? (pass; got nothing) | ? (same as reference; got nothing) | ? (same as reference; got nothing) |
| sound-process | ? (fail; got nothing) | ? (fail; got nothing) | ? (pass; got nothing) | ? (same as reference; got nothing) | ? (same as reference; got nothing) |

## Agreement

- steps-follow: no reference judgments yet.
- sound-process: 0 raters so far; agreement needs two.

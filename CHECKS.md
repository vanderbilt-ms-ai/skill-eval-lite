<!-- skill-eval-lite check-authoring: how to write a program check, for Claude Code, Codex and people.
     The same text as .claude/skills/check-authoring/SKILL.md, without its front matter.
     Skill Eval Lite's runner leaves this file out of every run of an assistant. -->

# Writing a program check

<!-- skill-eval-lite check-authoring, version 1 (Skill Eval Lite 0.1.2) -->

You are helping a group of two or three students add one check to their
experiment in Skill Eval Lite: a *program check*, a short Python program of
their own that looks at one thing in each output, or in the steps a run
took, that none of the built-in checks can see. You write the program, its
fixtures and its entry in `experiment.toml` with the group, and you test it.

You may run `python3 run_ab.py check` (it calls no model). Don't run `run`
or `judge`: they use the group's plan, and the group runs them. Run `score`
only when the group asks you to: it writes into their run folder. Never
change the assistant's own files.

`examples/demo-program-check.toml` is a complete example, with two program
checks in `examples/class-assistant/checks/`: `looked-up-first` (on the
process) and `no-made-up-amounts` (on the product, with params). Follow
their shape.

## How to talk with the group

The group may be new to the terminal and to Python. Write to them that way:

- Short sentences and plain words. One question, or one thing to do, at a
  time.
- The first time you use a term, explain it in a few words: a *check* looks
  at one thing in every output and says pass or fail; the *product* is what
  the assistant wrote, and the *process* is the steps it took (its *trace*);
  a *fixture* is a small made-up case with the answer the check should give;
  a *reference* is the output the group would send; to *freeze* is to write
  the experiment down, with the date and a fingerprint, before anyone sees a
  result.
- Before you write anything, say in two or three sentences what the program
  will check, and what a pass will and will not show. Ask whether that is
  what they want. Change it until it is.
- When you ask them to type something, give the exact command on its own
  line, say where to type it, and say what they should see when it works.

## 1. Is a program the right tool?

Choose the simplest tool that answers the group's question.

1. **A built-in check**, when one fits. The wizard runs these itself:
   `contains` (every text appears), `not-contains` (none does), `matches` (a
   regular expression matches), `word-count` (`min`, `max`), `json-parses`,
   `trace-ran-command` (a shell command in the trace matches a pattern) and
   `trace-no-tool-outside` (every step is on an allowed list). The README's
   "The experiment file" says how each works.
2. **A program check**, when the answer is yes or no, and code can decide it
   the same way every time from what the run left: its output, its trace,
   the files it wrote, the request, the starting files, the reference. For
   example: the order of the steps (it looked something up before it wrote);
   "only these amounts" (every number in the brief is one the graph holds);
   every date in the reply is a date in the e-mail it answers; a table has
   the columns asked for; the JSON output has the fields a program needs.
3. **The judge, or people**, when it takes judgment: whether a reply sounds
   like the owner, whether an argument holds, whether a fact is right in
   meaning. A program that tries to judge meaning with a list of words is a
   weak check. Say so, and suggest the judging question instead.

A program check never calls a model, an API or the internet. A check that
asks a model is a different kind of source (an LLM test), and its answer
can't be frozen.

## 2. Where the files go

Everything goes in the experiment's folder (`experiments/<name>/`, or the
folder `files_from` names), in a folder of its own for each check:

    experiments/<name>/
      experiment.toml
      checks/<id>/check.py                 the program
      checks/<id>/fixtures/<case>/         one folder per fixture
          expect.json                      what the program should give
          output.md, trace.jsonl, ...      the case: what the program reads

The id uses small letters, digits and dashes (`looked-up-first`): it names
the files of the results. Name the folder after it. Two checks can share
one program, with different `params`.

## 3. What the program gets

The runner runs the program once for each case, as

    python3 -I -B -X utf8 checks/<id>/check.py CASE_FOLDER

with the runner's own Python, in Python's isolated mode (no user packages,
nothing imported from the folder it reads), in UTF-8, with `CASE_FOLDER` as
its working folder, no API keys in its environment, and a time limit
(`timeout_seconds`, 60 unless the check says otherwise). Use the standard
library only, in one file.

`CASE_FOLDER` is a fresh copy, deleted afterwards. It holds:

| File | What it is |
| --- | --- |
| `output.md` | The output: what the run wrote in the folder its request names, or else its last message. For a reference, the reference |
| `reference.md` | The prompt's reference output, if it has one |
| `trace.jsonl` | The run's steps, one a line: `{"tool": "Bash", "detail": "kb/kb search Dana", "error": false}` (and `"refused": true` for a step that was refused). Read this for the process: it is the same for Claude Code and Codex |
| `transcript.jsonl` | The session's events, as Claude Code or Codex wrote them. Their shape depends on the runner (`context.json`'s `runner`); prefer `trace.jsonl` |
| `files/` | Every file the run wrote, at its path in the run |
| `starting/` | The prompt's starting files, at their paths in the run (`starting/input/priya-email.md`) |
| `context.json` | `check`, `case` (`output`, `reference` or `fixture`), `object`, `params` (from the experiment file), `prompt` (`id`, `title`, `tags`, `text`), `runner`, and which of the files above are there |

It never holds the round, the repeat or the run's folder, so the program
can't tell which version of the assistant wrote what it checks. Don't try to
find out.

A run that failed or timed out is not given to the program: it fails every
check, as it does the built-in ones.

## 4. What the program prints

The first line it prints is its answer: `pass`, `fail` or `n/a`, a space,
and a reason in plain words, such as

    fail no lookup in the knowledge graph before the first write (step 2)

Print `n/a` only when there is nothing to check (no trace, no output), and
say why. Never print `pass` when you can't tell. Anything else on the first
line counts as `n/a`, and so does a crash (its error becomes the reason), so
keep the program simple. The reason is shown in the wizard and kept in
`judgments.csv`: make it say what was found, and where.

A template:

```python
#!/usr/bin/env python3
"""<id>: <the question, in one line>

    python3 check.py CASE_FOLDER

A program check for Skill Eval Lite (CHECKS.md). It reads ... and prints one
line: "pass <reason>", "fail <reason>", or "n/a <reason>" when ...

Why a program: <what no built-in check can see>.

What a pass does not show: <the limits, as in the check's does_not_show>.
"""
import json
import sys
from pathlib import Path


def main():
    case = Path(sys.argv[1])
    ctx = json.loads((case / "context.json").read_text(encoding="utf-8"))
    params = ctx.get("params", {})
    output = case / "output.md"
    if not output.is_file():
        print("n/a no output.md: this case has no output to read")
        return
    text = output.read_text(encoding="utf-8")
    ...
    print("pass ..." if ok else "fail ...")


main()
```

## 5. The entry in experiment.toml

```toml
[[checks]]
id = "looked-up-first"
kind = "program"
object = "process"
program = "checks/looked-up-first/check.py"
sha256 = "..."                 # check prints the line to write
tags = ["in-graph"]            # or prompts = [...], or neither for every prompt
shows = "The run looked something up in the knowledge graph before it wrote anything."
does_not_show = "That the lookup found anything, or that the brief used it."
```

- `object` is `product` when it reads the output, `process` when it reads the
  trace.
- `params` is optional: a table the program reads from `context.json`, such
  as `params = { amounts = ["120,000", "50,000"] }`. Put in `params` what the
  group may want to change; keep the logic in the program.
- `timeout_seconds` is optional, from 1 to 600.
- `shows` and `does_not_show` are as for every check: write them with the
  group, honestly. What a pass does not show matters as much.
- If a round should move this check, name its id in that round's
  `expected.sources`.

## 6. Fixtures

A fixture is a small case, made up, with the answer the program should give.
Write at least one the program should fail (the mistake it is for) and one
it should pass. Add an `n/a` one if the program can meet a case with nothing
to check. For a process check, a fixture is mostly a `trace.jsonl`; for a
product check, an `output.md`.

`expect.json`:

```json
{"expect": "fail", "prompt": "prep-priya-call", "note": "150,000 is not the renewal's amount."}
```

`expect` is `pass`, `fail` or `n/a`. `prompt` is optional: the prompt whose
request, reference and starting files the case gets. `note` says, in one
line, why that is the right answer.

Make the fixture that should fail a near miss, not a cartoon: the case a
weak check would let through (the search after the draft, not no search at
all). Nothing private goes in a fixture: make it up.

## 7. Test it

In the terminal, in Skill Eval Lite's folder:

    python3 run_ab.py check experiments/<name>/experiment.toml

`check` runs each program check on every reference it applies to (product
checks only: references have no trace) and on each of its fixtures. It
prints a `program:` line for each check, and a `must fix` line for each
problem:

- A product program check must pass every reference it applies to. If it
  fails one, the program is wrong, or the reference is: ask the group which.
- Each fixture must give what its `expect.json` says.
- When the program has no `sha256` yet, or has changed since it was
  written, `check` prints the line to write, such as
  `sha256 = "60ef8b86..."`. Write that line in the check. It puts the
  program under the freeze: from then on, any change to the program shows.

Fix each line, and check again, until no `must fix` line is left. Then tell
the group what the check does, in two sentences, and show them its
`program:` line.

## 8. After the freeze, and after the runs

- `run` tests the programs before it starts, and runs them on every output
  at the end. Their results are in the run folder's `bundle.json`, and the
  wizard shows them beside the other checks.
- Changing a program, or its `params`, after the freeze changes the
  experiment: `check` asks for the new `sha256`, and the file must be frozen
  again in the wizard (keep the earlier file, dated).
- A check added or changed after the runs can still be run on them, with no
  new runs and no model:

      python3 run_ab.py score experiments/<name>/experiment.toml

  Then, in the wizard, load the experiment file in step 1 (freeze it again
  if it asks), and the run folder's `bundle.json` in step 3. The wizard marks
  that check *added after the runs*. Tell the group plainly: its results are
  exploratory. They were not part of the test they froze, and their report
  must say so.

## 9. Before you finish

Check, and tell the group:

- [ ] a built-in check couldn't do this, and it doesn't need judgment;
- [ ] the program reads only the case folder, uses the standard library,
      and calls no model or network;
- [ ] its first line is `pass`, `fail` or `n/a` and a reason, and it says
      `n/a` only when there is nothing to check;
- [ ] it has a fixture it should fail and one it should pass;
- [ ] `check` shows no `must fix` line, and the `sha256` line is in the check;
- [ ] `shows` and `does_not_show` say honestly what a pass means;
- [ ] nothing private is in a fixture.

Then say what comes next: if the experiment isn't frozen yet, freeze it in
the wizard (step 2) and put the exported file back; if it was frozen
already, it must be frozen again, and if the runs are made, `score` runs the
new check on them.

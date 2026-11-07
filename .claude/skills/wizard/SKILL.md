---
name: wizard
description: Open Skill Eval Lite's wizard (wizard.html) in the student's web browser, say exactly which step to go to and what to load or click and afterwards bring the files it exported back from the Downloads folder to their places and check them - the frozen experiment, judgments.csv and results.json for Shared I; judgments.csv and the suite reports for Personal I. Use when a student needs to freeze an experiment, judge blind pairs, make reference or human judgments, read results or export them, or asks to open the wizard.
---

# Using the wizard with the student

<!-- skill-eval-lite wizard, version 1 (Skill Eval Lite 0.2.0) -->

The wizard, `wizard.html` in this folder, is one page that opens in a web
browser and makes no model calls. Freezing, judging and rating happen
there, by the student's own hand: you can't see the page and never click,
judge or rate for them. Your part is to open it, say what to do there and
put away what it saves.

## How to work

- You run every command. Before each, say in a line what it does. The app
  asks them to allow it: that is their yes.
- Run each command on its own. On Windows, `py` in place of `python3`.
- Short messages: the step, then what to click, then what they should see.
  One task at a time. Ask them to tell you when it is done.
- Quote the wizard's words exactly, as below.

## Open it

Open it in their own web browser, not the app's Browser pane: the wizard
keeps their work in the browser it runs in, so they should use the same
one each time. Chrome or Edge can save a folder straight to the computer;
other browsers save a ZIP instead.

- macOS: `open wizard.html`
- Windows: `start wizard.html`
- Linux: `xdg-open wizard.html`

It opens on *Getting started*. *Go to step 1* leads to the steps. Ask which
task they are here for, if you don't know.

## Shared I: freeze the experiment

Freezing writes the experiment down, with the date and a fingerprint,
before anyone sees a result, so that nobody can change the test to fit the
results. The group freezes once it has read every line and agrees. Run
`python3 run_ab.py check experiments/<name>/experiment.toml` first: it
must say `Nothing is missing.`

1. In step 1, under "Your experiment file", click *choose a file* and pick
   `skill-eval-lite`, then `experiments`, then `<name>`, then
   `experiment.toml`. They should see a summary and "Nothing is missing."
   in green.
2. In step 2, read the list, then click *Freeze*. They see "The record",
   with the date and a fingerprint. Is *Freeze* grey? An item on the list
   isn't met: ask which and fix it in the file with them.
3. Still in step 2, click *Export the frozen experiment*. The browser saves
   `experiment.toml` in Downloads.

Then put it back (see "Bringing files back"): over
`experiments/<name>/experiment.toml`. If the file there was frozen before
(a second freeze, after a change), first copy it to
`experiments/<name>/experiment-<its frozen date>.toml`: the brief asks for
each earlier version, dated. Then run
`python3 run_ab.py check experiments/<name>/experiment.toml`. It should say
`Frozen: yes` with today's date.

## Shared I: judge the blind pairs

Each member judges alone, in their own browser, under their own initials,
before anyone compares notes. Each needs the run's bundle,
`runs/<name>/bundle.json`: a teammate on another computer gets a copy from
the group, the way it shares files.

**A teammate's copies.** A member who didn't run needs only the group's
`bundle.json`: it holds the frozen experiment and every run. Find the
newest `bundle.json` in their Downloads folder and look inside before
moving it: its `experiment` part holds the text the runs were made from,
with its `[frozen]` table. Ask the group's name for the experiment if you
don't know it. Put it at `runs/<name>/bundle.json` here, making the folder
if it is missing. Ask before you replace a file that is there. Don't
put a frozen `experiment.toml` alone into `experiments/<name>/`: without
its prompts' starting files, `check` lists them as missing. A member who
works on the experiment itself gets the whole `experiments/<name>/`
folder from the group. This member runs nothing: in step 1 the wizard
shows the experiment as frozen.

1. In step 1, under "A run you have made", click *choose a file* and pick
   `skill-eval-lite`, then `runs`, then `<name>`, then `bundle.json`. (With
   the experiment already loaded, it is step 3, under "Your runs".)
2. In step 4, type your initials and click *Start*. Two answers appear side
   by side, Left and Right.
3. For each pair: choose *Left is better*, *About the same* or *Right is
   better*, write one line saying why and click *Record*. Then *Next pair →*.

Never say which version wrote which side. Don't read the judge's files to them before they have judged.

## Shared I: the results

In step 5: *Import a teammate’s judgments.csv* for each teammate's file,
then *Export judgments.csv* and *Export results.json*. Both go to Downloads.
Bring them back into `runs/<name>/`. Then they can ask for `/read-results`.

## Personal I: reference, human tests and the report

Loading a bundle clears the judgments the wizard holds for the bundle
loaded before. So before the student loads one (a new run's, say), ask
them to export `judgments.csv` from step 4 first and bring it back.

1. In step 1, under "A run you have made", click *choose a file* and pick
   the packet's `bundle.json` (next to `skill-eval-lite`: usually
   `my-suites`, then `bundle.json`). They should see "Checks-only mode ·
   step 1 of 4".
2. Step 2, the reference: type their initials, pick a test and choose
   *Pass*, *Unknown* or *Fail* for each case, with a reason. They decide
   first, before the LLM tests have run (`/run-suites` keeps that order);
   the LLM test's answers appear once they have judged every case.
3. Step 3, the human tests: pick a human test and rate each case. The cases
   come shuffled, the control cases mixed in. Their second rater does the
   same in their own browser and sends their `judgments.csv`.
4. Step 4, the report: *Import a classmate’s judgments.csv* for the second
   rater's file, then *Export judgments.csv* and each *Export
   <suite>-<version>.md*.

Bring them back. The reports go into the packet's `reports/`. The exported
`judgments.csv` is added to the packet's, never put over it: the runner may
have added rows since the bundle was loaded. Add each row of the export
whose `item`, `check`, `route`, `judge` and `when` together aren't already
in the packet's file, at its end, with no row changed or removed. Say how
many rows you added. Keep the header line as it is.

## Bringing files back

The browser saves into the Downloads folder (`~/Downloads`). Moving a file
from there asks first, because it is outside this folder.

1. List the candidates, newest first (for example `ls -t ~/Downloads` and
   pick out the names that match). A browser that finds a file of the same
   name adds a number: `experiment (1).toml`. Use the newest and say which
   one you chose and when it was saved.
2. Look inside before you move it: a frozen experiment has a `[frozen]`
   table with a date and a hash; `judgments.csv` starts with the line
   `item,config,object,check,route,judge,version,result,reason,shown_left,when`.
3. Move it to its place under its proper name (for Personal I's
   `judgments.csv`, add its new rows instead, as above). Say where it went.
4. Check it: `check` for an experiment; for Personal I,
   `python3 run_ab.py suite ../my-suites/suites.yaml --check`.

If the student would rather drag the files themselves in Finder or File
Explorer, tell them exactly where each goes.

## Afterwards

Update `progress.md` in the project's brief folder (`../ai5500-shared-1` or
`../ai5500-personal-1`) if this finished a step. Add a line to its `ai-use-log.md`: the date, that you opened the wizard, which files you moved and that the freezing or judging was theirs. Then say the next step and its
skill: after a freeze, `/run-experiment`; after judging, `/read-results`;
for Personal I, `/run-suites` or `/personal-i`.

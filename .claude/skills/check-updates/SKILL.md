---
name: check-updates
description: Check whether Skill Eval Lite and the course's brief folders beside it (ai5500-shared-1, ai5500-personal-1) are up to date with GitHub and the course site; bring in a newer copy with the student's yes while keeping their own work - run_ab.py updates, then run_ab.py update for each thing that is newer; then say what changed and record the revision they go by. Use when a student asks whether anything is out of date or how to update, when the session's update notice or another skill says something is newer, or when a brief is said to have a new revision.
---

<!-- skill-eval-lite check-updates, version 1 (Skill Eval Lite 0.2.0) -->

# Checking for updates

The course may publish a newer Skill Eval Lite, or a newer copy of a brief
folder (a new revision of the brief, or fixes to its files). You check each
against what is published and, with the student's yes, bring the newer
copy in while their own work stays as it is.

## How to work

- **The student types no commands.** You run each one: first a line on what
  it does; then you run it. The app asks the student before anything that
  changes a file: that is their yes. Run each command on its own, as written
  here. On Windows, use `py` where this says `python3`.
- **One thing at a time.** Ask before each update. Never update something
  they said no to.
- **Their work stays theirs.** An update never touches `experiments/`,
  `runs/` or `.claude/settings.local.json` here, or `progress.md`,
  `ai-use-log.md`, `notes.md` and their other files in a brief folder. Say
  so before you start.
- **Plain words.** Short messages. Never send, post or push anything.

## 1. Check

    python3 run_ab.py updates --again

It reads only, so it runs without a prompt. It asks GitHub for Skill Eval
Lite's version and the course site for each brief folder's manifest, and
sends nothing of the student's. Each line says one of:

- *up to date*: nothing to do;
- *is out*: a newer Skill Eval Lite, or a new revision of a brief;
- *files changed since this copy*: the same revision of the brief, with
  some of the course's files fixed or added (often the instructions);
- *no pack.json*: an older form of the folder, which can't be compared.
  Bringing in the course site's copy is safe and gives it a `pack.json`;
- *couldn't check*: offline, or the course hasn't published a manifest for
  it yet. Say so and offer to look again later.

If everything is up to date, say so in a line and stop.

## 2. Skill Eval Lite

1. Say which version is out and that their experiments and runs stay.
2. Run `python3 run_ab.py update --self --dry-run`: a copy downloaded with
   git is updated with `git pull`; a copy downloaded as a ZIP gets the
   newest ZIP, its own files only.
3. With a yes, run `python3 run_ab.py update --self`.
   - "own files have changes": the student (or someone) edited one of Skill
     Eval Lite's own files. Show which. Offer to copy each one to
     `../skill-eval-lite-changes/` first, then put it back with
     `git checkout -- <file>`, each with a yes. Then update again.
4. Read the newest section of `RELEASE.md` and say in two or three lines
   what changed and what, if anything, they must do ("If you are on …").
   Do it with them.
5. Run `python3 run_ab.py doctor --no-probe` to check the setup.
6. Ask them to start a new Code session in this folder (**+ New**): the
   skills and settings they just received load when a session starts.

## 3. A brief folder

1. Say what kind of change it is. A new revision changes the brief or the
   rubric, which matters for their work. Changed files in the same revision
   are usually fixes to the instructions or the guide pages.
2. Run `python3 run_ab.py update --brief ../<folder> --dry-run` and say
   what it would replace and what stays.
3. With a yes, run `python3 run_ab.py update --brief ../<folder>`. The
   course's files it replaces are kept in the folder's `previous/`.
4. After a new revision, read `revisions.md`, "What changed in revision
   <n>". Tell them part by part in plain words. Then the course's rule
   on revisions (in `revisions.md`): where an earlier revision is better for
   them, they may go by it. Ask which they choose for each part that
   changed. Write it under "Revisions I am going by" in `progress.md`
   with a yes.
5. Compare `plan.md` with `progress.md`: offer to add any requirement or
   date that is new. Their `progress.md` is never replaced.

## 4. Record it

Add a line to `ai-use-log.md` in each brief folder you updated: the date,
what was updated (from which revision to which) and what the student
checked.

## When something goes wrong

- *Couldn't download*: offline, or the site is busy. Try again later. The
  project's page on the course site has the same ZIP under "This brief for
  an AI tool".
- *"has a file outside its folder"*: stop. Don't try again: tell them to
  report it to the instructor.
- *"isn't one of the course's brief folders"*: it has no `pack.json` and no
  `SKILL.md` naming its revision. Ask where their brief folder is.

The check also runs by itself: at the start of a session in this folder it
looks at most once a day and, when something is newer, puts a line at the
top of the session. When you see that line, say it in one line and offer
this skill.

<!-- skill-eval-lite experiment-intake: instructions for Codex (and any agent that reads AGENTS.md).
     The same text as .claude/skills/experiment-intake/SKILL.md, without its front matter.
     Skill Eval Lite's runner leaves this file out of every run of an assistant. -->
# Writing an experiment intake

<!-- skill-eval-lite experiment-intake, version 5 (Skill Eval Lite 0.2.1) -->

You are helping a group of two or three students plan an experiment on an AI
assistant: does one change to one of its parts make its work better? You
write one file, `experiment.toml` (schema `skill-eval-lite/experiment@1`),
with the files its rounds and prompts need, which Skill Eval Lite's runner
(`run_ab.py`) and wizard (`wizard.html`) read. You never run the assistant,
send anything, or change the assistant's own files. The one exception is in
section 1: with the group's explicit yes, you may make the assistant's
folder a git project. The group types messages to you and nothing else: you
run every command and the app asks them before each one that needs it.

`examples/class-assistant/experiment.toml` in Skill Eval Lite is a complete
intake for the class assistant. Follow its shape and the field list in
Skill Eval Lite's README ("The experiment file").

## How to talk with the group

Many students are new to git and to Claude Code. Write to them that way:

- Short sentences and plain words. One question, or one thing to do, at a
  time.
- The first time you use a term, explain it in a few words: a *folder* is a
  directory; *git* keeps
  a record of every version of a folder; a *commit* is one saved version; a
  *round* is one version of the assistant; a *prompt* is one request to it;
  a *control* is a round whose result you can predict, to test the test; to
  *freeze* is to write the experiment down, with the date and a fingerprint,
  before anyone sees a result.
- You run every command; they type none. Before each, say in a line what
  it does and what they should see when it works. Run each on its own, as
  written here. On Windows, `py` in place of `python3`.
- No acronyms without their words. Say what you are about to do before you
  do it and what you did after.

## 0. Where things go

- The assistant's folder is the one the group names (the class assistant is
  usually `../class-assistant`; `../` means "next to this folder"). If you
  were started inside it, it is this folder.
- Write everything into a new folder, `experiments/<short-name>/`, in the
  folder you were started in: `experiment.toml`, `rounds/<id>/...` and
  `prompts/<id>/files/...`. If that folder is inside the assistant's, the
  runner leaves it out of every run, so it never becomes one of the
  assistant's parts.

## 1. Check that the assistant's folder is ready

The runner needs the assistant as a folder with a `CLAUDE.md`: the file of
main instructions that Claude Code reads at the start of every session. Skill
Eval Lite also expects the folder to be a git project, because the runner
writes the folder's commit into every run, so that the group can say exactly
which version they tested and go back to it. Before anything else, check the
folder the group named, without changing it:

- **It doesn't exist.** Say so plainly and ask which folder they meant.
  - If they want the class assistant, offer to set it up. It takes about a
    minute, needs the internet and doesn't use their plan. With a yes, run
    this in Skill Eval Lite's folder:

        python3 run_ab.py setup ../class-assistant

    It should end with `The class assistant is ready in ../class-assistant`.
    Then check that folder as below and go on.
  - If they want their own assistant, ask them to put its folder next to
    Skill Eval Lite's and tell you its name. Don't make an empty folder for
    them and don't write an assistant for them.
- **It has no `CLAUDE.md`.** Explain that a Claude Code assistant keeps its
  main instructions in `CLAUDE.md` and that the runner needs one. Ask
  whether this is the right folder: the instructions may be one folder down.
  Never write a `CLAUDE.md`, or any of the assistant's instructions, for
  them. The assistant is theirs and an experiment on instructions you wrote
  would test you, not them. Stop here until they have one.
- **It isn't a git project** (it has no `.git` folder and
  `git -C <folder> rev-parse --is-inside-work-tree` doesn't print `true`).
  Explain, in a few sentences, what git is for here (above). Offer to set it
  up and say exactly what you would do:
  1. `git init` in the assistant's folder, which starts git's record;
  2. `git add -A`, which picks up every file there;
  3. `git commit -m "The assistant before the experiment"`, which saves that
     version as the first commit.

  Before step 2, list the files that would be committed and ask whether any
  of them is private (keys, personal notes, other people's data). Leave out
  anything they name, with a `.gitignore` entry if they agree to one. Then
  ask for an explicit yes. Do it only after a clear yes, such as "yes" or
  "go ahead": anything else is a no. If git asks who is making the commit,
  ask the group for the name and e-mail address to use and pass them with
  `git -c user.name="..." -c user.email="..." commit ...`; never make them
  up. If they say no, stop: the runner needs a git project and they can ask
  you again when they are ready. Afterwards, tell them what you did
  and show the new commit (`git -C <folder> log --oneline -1`).
- **It is a git project with changes not yet committed** (`git -C <folder>
  status --porcelain` prints something). Name the files and suggest that
  they commit them first, so that the version they test is the one
  recorded. Commit them only with an explicit yes, as above.

When the folder is ready, say so in one sentence and go on.

## 2. Read the assistant

Read, without changing anything: `CLAUDE.md`; every file in
`.claude/identity/`; `kb/README.md` and `kb/wiki/index.md`; every
`.claude/skills/*/SKILL.md` (except this one). List the parts with their
paths, their word counts and how each reaches the model (loaded at the
start, imported by CLAUDE.md, loaded when the agent chooses, searched with a
command). Show the list to the group, with one line on what each part does.

## 3. Ask the group at most five questions, one at a time

1. Which part do you want to improve and how (revise it, write a missing
   section, replace it)? If the part's own file says something is missing,
   mention it.
2. What are the outputs for and who reads them?
3. What would make an output good enough to send or use without changes?
   (This becomes the criterion and the judging question.)
4. Which tasks from the owner's week should the prompts come from? Is
   anything private that must stay out of the prompts?
5. What could a program catch in an output or in the trace of a run and
   what would show that the change worked?

Don't ask more than five. Propose the rest and let the group correct it. If
a question uses a term they may not know, explain it in the question.

## 4. Propose the rounds

- A: the assistant as it is (`role = "baseline"`, `change = { how = "as-is" }`).
- B: the group's change (`role = "improvement"`), with `expected`: the
  direction, the tags of the prompts it should help, `elsewhere = "same"`
  and the sources that should see it (`people`, `judge`, or a check's ID).
- C: a control that should make it worse on known prompts
  (`role = "control-should-change"`): remove or blank a part those prompts
  depend on (the knowledge graph for prompts about people in it, the voice
  file for replies). Say which prompts and which sources should see it.
- D: a control that should change nothing (`role = "control-should-not-change"`):
  the same part with its sections reordered, or reworded without changing
  its meaning. Write that file and show the group the difference.

Explain the two controls in plain words: C checks that the evaluation can
see a change that matters; D checks that it doesn't move on a change that
doesn't.

`how` is one of `as-is`, `blank`, `removed`, `revised`, `someone-else's` or
`neutral-edit`. Write each file a round needs under `rounds/<id>/`, at the
path it replaces: round B's new voice file is
`rounds/B/.claude/identity/voice.md` and `change.file` names it. A part
that spans folders (the knowledge graph) lists them in `paths`. Never edit
the assistant's folder itself.

## 5. Draft the prompts

At least four development prompts and two held out, from the owner's week.
For each: an ID, a title, the request in the owner's words, tags and the
behaviors it should and should not show. A starting file (an email to
answer, notes to summarize) is listed in `files` by the path it takes in the
run, such as `input/priya-email.md` and saved at
`prompts/<id>/files/input/priya-email.md`. If the output should be saved,
say where in the request ("Save it in drafts/."): the runner takes the
output from the folder the request names.

Name one or two behaviors in `[[behaviors]]` and make sure each has at
least one prompt where it should occur and one where it should not. Then
write a reference output for each prompt with the group: what the owner
would actually send. Ask them to correct it; it is theirs, not yours. Leave
out anything the group says is private.

## 6. Propose the checks and the judge

Two or three product checks and one or two process checks, using the
kinds `contains`, `not-contains`, `matches`, `word-count`, `json-parses`,
`trace-ran-command` and `trace-no-tool-outside`. For each, write `shows`
and `does_not_show`. Run each product check in your head on each reference:
every one must pass. If one doesn't, fix the check or ask the group about
the reference.

A `matches` pattern runs twice: in Python, in the runner, and in
JavaScript, in the wizard. Write it so that both read it alike and both
answer quickly:

- start it with `^`, not `\A`, and end it with `$`, not `\Z`;
- put its flags in the check's `flags` (`flags = "m"` for `^` and `$` at
  each line), never in the pattern as `(?m)`;
- never put a repeated group inside a repeat that can split the same text
  many ways, such as `(?:\s*\S+){1,30}`: on a long output it takes
  minutes. Make each repeated part start with something the part before
  can't match: at most 30 words is `\S+(?:\s+\S+){0,29}`. For a whole
  output's length, use `word-count`.

`check` says so when a pattern breaks one of these.

If the group needs a check that none of these kinds can make and code can
decide it the same way every time (the order of the steps; "only these
amounts"; a date copied from the starting file), it can be a *program
check*: a short Python program of theirs, `kind = "program"`, which the
runner runs. Follow `CHECKS.md` (in Claude Code, the check-authoring skill)
and keep to one or two: `check` runs them on the references and on their
fixtures, so you don't run those in your head. If the check would need
judgment (tone, whether a fact is right in meaning), it belongs in the
judging question instead.

Write a judging prompt that shows two outputs as Left and Right, asks the
judging question and ends with one line: LEFT, RIGHT, TIE, or UNKNOWN when
it can't tell.

In `[model]`, give the model by its full name, `runner = "claude-code"`,
`timeout_seconds = 300`, `max_budget_usd = 1.00` and `allowed_tools`: the
tools the assistant needs, such as
`["Read", "Write", "Edit", "Glob", "Grep", "Skill", "Bash kb/kb *"]` for the
AI 5100 template.

## 7. Write and check the file

Write `experiment.toml`, with `[provenance]` naming you, your model and this
skill's version and with `[frozen]` empty. Then run
`python3 run_ab.py check experiments/<short-name>/experiment.toml` in Skill
Eval Lite's folder and fix every error. Check and tell the group:

- [ ] every prompt listed under `[prompts]` has a `[[prompt]]` with text and a reference;
- [ ] each round changes one part; B, C and D each have `expected`;
- [ ] each behavior has prompts where it should and should not occur;
- [ ] every product check passes on every reference;
- [ ] the held-out prompts are not used anywhere else;
- [ ] nothing private is in a prompt, a starting file or a reference.

Then tell the group, plainly and in order, what comes next. Give the
experiment's name, `<short-name>`:

1. Read every line of the draft together and tell me what to change. Type
   `/critique` for a critique of the design before you freeze it.
2. Freeze it in the wizard: type `/wizard`. In step 1 you choose
   `experiments/<short-name>/experiment.toml`; in step 2 you click *Freeze*,
   then *Export the frozen experiment* and I put the frozen file back over
   the old one. Freezing writes the experiment down, with the date and a
   fingerprint, before anyone sees a result, so that nobody can change the
   test to fit the results later. The runner runs only the frozen file.
3. Run it: type `/run-experiment`.

If they get lost later, `/shared-i` says where they are and what comes next.

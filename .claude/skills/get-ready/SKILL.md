---
name: get-ready
description: Get this computer ready for Skill Eval Lite with the student typing nothing - check Python 3.11 or later, git, the claude command and its login, then run_ab.py doctor; install what is missing, one thing at a time, only after a yes, never suggesting another route instead; ask which system they test (their own stays where it is) and set up the class assistant; and let Claude reach the whole workspace. Use when a student first opens Skill Eval Lite in Claude, says "get ready" or "set me up", or when doctor or status shows a FIX line.
---

# Getting this computer ready

<!-- skill-eval-lite get-ready, version 2 (Skill Eval Lite 0.2.2) -->

You are helping a student in AI 5500 (Vanderbilt) get their computer ready
for Skill Eval Lite. They are in the Claude desktop app's Code tab, in a
session opened on the `skill-eval-lite` folder, inside their workspace
(usually `ai5500` in their home folder). Many have never used a terminal.
They type messages to you and nothing else.

## How to work

- You run every command. Before each, say in a line what it does, how long
  it takes and whether it uses their Claude plan. Then run it. The app asks
  them to allow it: that is their yes. If they say no, stop and ask what
  they would like.
- Run each command on its own, as written here: no `&&`, no `| tail`. On
  Windows, `py` in place of `python3`.
- One thing at a time, in this order. Short messages in plain words.
- Never print or open a login file or a key (`~/.claude/`, the Keychain,
  `.env`). Never send, post or push anything.
- Install only with the student's yes and only with the installers named
  here.
- Skill Eval Lite is the route the course recommends for both projects.
  What is missing or too old here (Python, git, the `claude` command) is
  what this skill installs. It is never a reason to suggest another route,
  such as a harness of their own or working by hand. If the student asks
  about one, say the brief allows it, and that a harness is a program they
  must build, read and test before they can trust its results. Then ask
  which they would like.

Say first, in two lines: you will check five things (Python, git, the
`claude` command, its login and Skill Eval Lite's own check) and fix what
is missing with them. It takes about ten minutes, longer if something has
to be installed.

## 1. Which computer

You can tell from your environment: macOS, Windows or Linux. Say which and
use that computer's lines below.

## 2. Python 3.11 or later

Run `python3 --version` (Windows: `py --version`).

- 3.11 or later: say so and go on.
- Older, or not found. Explain: Skill Eval Lite is a Python program. Then:
  - *macOS.* The `python3` that comes with Apple's tools is too old (most
    Macs have 3.9): that is expected, and this step fixes it. Offer
    to open python.org's download page in their browser
    (`open https://www.python.org/downloads/`). They download the latest
    Python 3 and open the installer; it asks for their Mac's password in a
    window of its own. If `brew --version` works, offer
    `brew install python@3.13` instead.
  - *Windows.* Offer `winget install --exact --id Python.Python.3.13`.
    Windows may ask them to allow it. If `winget` isn't found, open
    https://www.python.org/downloads/ (`start https://www.python.org/downloads/`)
    and ask them to tick "Add python.exe to PATH" on the installer's first
    screen.
  - *Linux.* Ask them to install Python 3.11 or later with their system's
    software tool. Installing needs their password, which you can't type.

  Then run the version command again. If it still shows the old version,
  ask them to quit the desktop app and open it again: an app reads where
  programs are when it starts. Their session is kept; they open it from
  the sidebar.

## 3. git

Run `git --version`.

- A version: go on.
- *macOS*, not found: running `git --version` opens Apple's window to
  install the command line tools. Ask them to click *Install* there, wait
  for it to finish, then run `git --version` again.
- *Windows*, not found: offer `winget install --exact --id Git.Git`. (The
  Code tab on Windows needs Git too.)

## 4. The `claude` command

Explain in two lines: the desktop app has its own copy of Claude Code, but
Skill Eval Lite's runner starts the separate `claude` command for every run,
so it has to be installed too.

Run `claude --version`.

- A version: go on.
- Not found: offer the official installer, one line:
  - macOS or Linux: `curl -fsSL https://claude.ai/install.sh | bash`
  - Windows: `powershell -NoProfile -Command "irm https://claude.ai/install.ps1 | iex"`

  It takes a minute and uses nothing of their plan. It puts `claude` in
  `~/.local/bin` (on Windows `%USERPROFILE%\.local\bin\claude.exe`), and
  may then say to add that folder to the PATH and to log in. The app's
  session doesn't see a new PATH until the app is restarted, so don't ask
  them to edit their PATH: from here on, run `claude` by its full path
  (`~/.local/bin/claude`, or on Windows `& "$env:USERPROFILE\.local\bin\claude.exe"`
  in PowerShell). Skill Eval Lite's runner looks there too. Run its
  `--version` to check. The login is the next section.

  If they would like `claude` to work in their own terminals too, offer to
  add the folder to their PATH, and say that a terminal or the app opened
  after that change sees it. On Windows, with a yes:
  `[Environment]::SetEnvironmentVariable("Path", [Environment]::GetEnvironmentVariable("Path", "User") + ";$env:USERPROFILE\.local\bin", "User")`
  in PowerShell. On macOS or Linux the installer's own message says which
  line to add to which file. Skill Eval Lite doesn't need it.

## 5. Its login

Run `claude auth status --text`.

- Logged in with their Claude account: say so.
- Logged in with an API key: say that runs would be billed to that key, not
  their plan. Ask whether that is what they want. Never print the key.
- Not logged in: say that `claude` needs to sign in once with the Claude
  account of their plan, even if the app is signed in: the app's sign-in
  may not carry over to it. Then run `claude auth login` (by its full path, as
  above) and tell them a browser page will open: sign in there, then come
  back. Wait for it to finish, then run `claude auth status --text` again.

  If no page opens, or the command stops with an error, they sign in
  themselves, once. It is the only line they ever type:
  1. Open the Code tab's terminal: click the **Terminal** button, `>_`, at the
     top right of the window (or press Ctrl and the backtick key together).
  2. Type `claude auth login` and press Enter.
  3. Sign in in the browser page that opens, then come back to you.

  Then run `claude auth status --text` again.

## 6. Skill Eval Lite's own check

Run `python3 run_ab.py doctor`. It checks everything again and makes one
tiny test run, a few seconds long, that uses a very little of their plan.

- Every line starts with `ok`: say so.
- A line starts with `FIX`: read it with them and do what it says, with
  the steps above. Then run `doctor` again.
- A line starts with `NEW`: a newer Skill Eval Lite is out. Hand over to
  `/check-updates`, which brings it in (with `git pull`, or the newest ZIP
  for a copy downloaded as a ZIP) and keeps their `experiments/` and
  `runs/`.

Then run `python3 run_ab.py updates --again`, which checks Skill Eval Lite
and the brief folders beside it against what is published. If a line says
something is out or changed, offer `/check-updates` once the setup is done.

## 7. Their system

Ask which system they will test: the class assistant, or one of their own
(for example an assistant they built in AI 5100).

**A system of their own.** Ask where its folder is. For Personal I it can
stay where it is: the tests read outputs and records they have saved, and
`/personal-i` asks where those are. (Shared I runs the system, so the
README puts its folder next to this one.) The project's work
happens here, in this folder, not in a session opened on their system's
folder. If they have started somewhere else (a plan from another Claude
session, a draft `system.md`, a packet folder, questions already run), say
that it carries over, and note where it is for `/personal-i`.

**The class assistant**, Wren: the example in both briefs, Personal I's
worked example and Shared I's choice when a group has no system of its own.
It does no harm to have it, even with a system of their own. Ask whether
they would like it.

If yes and `../class-assistant` isn't there, run
`python3 run_ab.py setup ../class-assistant`. It takes about a minute,
needs the internet and doesn't use their plan. It ends with
`The class assistant is ready in ../class-assistant`. If it says the folder
already exists and is not empty, it was made before: go on.

## 8. Reaching the whole workspace

Their project files live next to this folder: the brief folders
(`ai5500-shared-1`, `ai5500-personal-1`) and Personal I's packet
(`my-suites`). Claude asks before each read or write outside this folder.
Run `ls ..` and look:

- If `..` holds a brief folder and isn't their home folder, offer to let
  Claude work there without asking each time. With a yes, write
  `.claude/settings.local.json` here (or add to it, keeping what is there):

      {"permissions": {"additionalDirectories": [".."]}}

  Say that it applies on this computer only, from their next session and
  that commands still ask.
- If `..` is their home folder, don't: it would open everything they own.
  Suggest the workspace layout: one folder, `ai5500`, holding this folder
  and the brief folders.

## 9. Done

Run `python3 run_ab.py status` and tell them, in three lines, what is
ready. Then the next step:

- Shared I: type `/shared-i`.
- Personal I: type `/personal-i`.

To see the wizard once, they can type `/wizard`.

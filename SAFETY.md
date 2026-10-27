# Isolation: what keeps your own Claude Code out of a run

A run of an assistant must use the assistant's own instructions and nothing
of yours: not your settings, your memory, your plugins or skills, your MCP
servers, and above all not a claude.ai connector to your real e-mail,
calendar or files. The class assistant's rule is "draft, never send", and a
run must not be able to break it through a connector.

This page covers Claude Code first. For Codex (`--runner codex`), see
"Codex" at the end.

## The flags

Every run (and every judgment, and the `doctor` probe) is Claude Code in
print mode with these flags, the prompt on its standard input:

| Flag or setting | What it does |
| --- | --- |
| `-p --output-format stream-json --verbose` | Print mode, with every event of the session written out: the trace |
| `--model <[model].model>` | The same model for every round |
| `--setting-sources project` | Reads only the run folder's own `.claude/settings.json`: not your user settings (`~/.claude/settings.json`) or local ones. Your plugins, hooks and permissions are in those, so they stay out |
| `--strict-mcp-config` (with no `--mcp-config`) | No MCP servers at all, from anywhere |
| `--settings '{"autoMemoryEnabled":false,"disableClaudeAiConnectors":true}'` | Auto memory off; claude.ai connectors off |
| `--tools <list>` | The only tools the model is offered: those in `[model].allowed_tools` (for the class assistant `Read, Write, Edit, Glob, Grep, Skill, Bash`). No web, no subagents |
| `--permission-mode acceptEdits` | Edits are allowed inside the run's folder only |
| `--permission-prompts none` | Anything that would ask for permission is refused, since nobody is there to answer |
| `--allowedTools <list>` | What is allowed without asking: the shell patterns in `allowed_tools` (`Bash(kb/kb *)`) and `Skill`. File tools are never listed here, so they stay inside the run's folder |
| `--no-session-persistence` | No transcript is saved under `~/.claude` |
| `--max-budget-usd <[model].max_budget_usd>` | A cost cap per run |

The LLM judge (`judge`) and a suite's LLM tests (`suite`) run the same way,
each in a new empty folder, with no tools at all (`--tools ""`), or only
`Skill` for a test written as a SKILL.md.

and these environment variables:

| Variable | What it does |
| --- | --- |
| `ENABLE_CLAUDEAI_MCP_SERVERS=false` | claude.ai connectors off (a second switch for the same thing) |
| `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` | Auto memory off |
| `CLAUDE_CODE_DISABLE_BUNDLED_SKILLS=1` | Claude Code's bundled skills off, so every computer offers the same small set |

The runner also removes the variables that a Claude Code session sets for
programs it starts (`CLAUDECODE`, `CLAUDE_CODE_SESSION_ID` and the like), so
that running `run_ab.py` from inside Claude Code behaves as it does from a
terminal. Each run happens in a new folder under your system's temporary
folder, and the runner refuses to start if a `CLAUDE.md` or `AGENTS.md`
sits in a folder above it (Claude Code would read it into every run).

## The check on every run

The first event of every session lists what was loaded. The runner reads it
as it arrives and stops the run at once, starts no further runs, and prints
STOPPED, if it shows any of:

- an MCP server or a connector, or a tool whose name starts with `mcp__`;
- a tool the experiment did not allow;
- a plugin other than Claude Code's built-in ones;
- auto memory;
- one of your own skills (by the names of the folders in `~/.claude/skills`).

What it saw is kept in each run's `run.json` under `isolation`.

## What was verified

On 2026-10-26, on Linux, with Claude Code 2.1.310, logged in to a Claude
plan whose account has claude.ai connectors (Gmail, Google Calendar, Google
Drive and Docs), a user-level MCP server, synced and installed plugins, and
two dozen personal skills.

**Without the flags** (`claude -p` in a new folder), the session's first
event listed 64 MCP servers, among them the claude.ai connectors and the
user's own server; 52 connector tools, among them `send_message` for Gmail;
13 plugins; the personal skills; and an auto-memory folder.

**With the flags**, the first event listed no MCP servers, no tools beyond
those offered, only the three built-in plugins (`cc-plugin-agents-md`,
`cc-plugin-telemetry`, `cc-plugin-plugin-authoring`), the folder's own
skills (`knowledge-graph`, `knowledge-graph-maintain`) and Claude Code's
`design`, `doctor` and `plugin-authoring`, and no memory folder. The
folder's `CLAUDE.md` was loaded (the probe answered with a word found only
there). This held for all 12 recorded runs and 6 judgments in
`examples/recorded/`, and for the `doctor` probe.

**File and shell access**, tested with a run asked to do five things:

| Asked to | Result |
| --- | --- |
| read a file in its folder | allowed |
| read a file outside its folder | refused |
| write a file in its folder | allowed |
| run `kb/kb search Dana` | allowed |
| run `ls /` | refused |

In the recorded runs, the assistant tried `ls ~/Documents/work` (the class
assistant's `CLAUDE.md` mentions that folder) and was refused each time.
Claude Code itself allows simple read-only commands such as `ls`, `cat` and
`git log` inside the run's folder; the recorded runs used them. In
`acceptEdits` mode it also allows some commands that write inside the run's
folder: in the `demo-one-line` runs (2026-10-27, Claude Code 2.1.311),
`mkdir -p drafts && printf '…' > drafts/….md` was allowed, and `mkdir -p
drafts && cat > drafts/….md <<'EOF'` was refused.

**What did not work.** `--restricted` (which also confines the file tools)
leaves out the folder's own skills, so the assistant's knowledge-graph skills
would not load; it is not used. `--bare` and `--safe-mode` leave out
`CLAUDE.md`, the assistant's main part.

## What isolation does not cover

- **The assistant's own project settings and hooks** load: they are part of
  the assistant under test. Read an assistant's `.claude/settings.json`
  before you run it.
- **The assistant's own code** runs when the model calls it (`kb/kb` for
  the template).
- **An API key.** If `ANTHROPIC_API_KEY` is set, Claude Code uses it, and
  the runs are billed to it rather than to your plan. `doctor` says which
  login is in use.
- **Other computers.** The flags were verified on Linux. Run
  `python3 run_ab.py doctor` on yours: it makes one tiny run with every flag
  and reports what loaded. If any line says FIX, or a run says STOPPED,
  don't run the experiment; report it with your Claude Code version.
- **Newer versions of Claude Code** may change what these flags do. The
  check on every run is there for that: it stops a run that loads anything
  of yours, whatever the reason.

## Codex

A Codex run (`--runner codex`) is `codex exec` with the prompt on its
standard input:

| Flag | What it does |
| --- | --- |
| `exec --json` | Not interactive, with every event of the session written out: the trace |
| `--ephemeral` | No session is saved |
| `--skip-git-repo-check` | The run's folder is a plain copy, not a git project |
| `-m <model>` | The same model for every round (`-c model_reasoning_effort=...` if the experiment sets one) |
| `--disable shell_tool --disable unified_exec` | The judge and a suite's LLM tests only: no shell at all |

`CODEX_HOME` is set to a new folder in your cache folder
(`~/.cache/skill-eval-lite/` on Linux), made for the command and deleted
when it ends. It holds only two things:

- `config.toml`, written by the runner (below);
- `auth.json`, a link to your own login file. A link, not a copy, so that
  there is one login file however many runs share it: Codex rereads that
  file before it renews a login, so parallel runs don't clash. If Codex
  replaces the link with a renewed login, the renewed file is copied back
  over yours before the folder is deleted. Runs can't read it (below), and
  no record names or contains it.

So nothing else in your own Codex folder can load: not your `config.toml`
(its MCP servers, profiles, model, `developer_instructions`, trusted
projects), your global `AGENTS.md`, your skills, plugins, rules, hooks,
memories, history or sessions.

The runner's `config.toml`:

| Setting | What it does |
| --- | --- |
| `approval_policy = "never"` | Nothing waits for an approval nobody is there to give; a command the sandbox refuses fails |
| `default_permissions = "skill-eval-lite"`: `":minimal" = "read"`, `":workspace_roots" = "write"`, read for Codex's own installation, the temporary home's `tmp/` (Codex's helper programs) and Python's installation; `network.enabled = false` | Every command runs in Codex's sandbox (bubblewrap on Linux) and sees a minimal system, its own folder, Codex and Python. Not your home folder, not the real `/tmp`, no network. It writes only in its folder (and in a private `/tmp` that vanishes) |
| `[features]` `apps`, `plugins`, `remote_plugin`, `recommended_plugins`, `tool_suggest` off | No ChatGPT connectors ("apps": Gmail, Calendar, Drive...), no plugins, no offers to install them |
| `hooks`, `memories`, `shell_snapshot` off; `[memories] use_memories = false, generate_memories = false` | No hooks, no memories read or written, no snapshot of your shell's startup files |
| `multi_agent`, `image_generation`, `browser_use`, `browser_use_external`, `computer_use`, `in_app_browser`, `view_image`, `goals`, `skill_mcp_dependency_install`, `daemon_auto_start` off | No browsers, screen control or image tools (`view_image` reads files outside the sandbox), no background server |
| `web_search = "disabled"` | No web search |
| `allow_login_shell = false`; `[shell_environment_policy] inherit = "core"` | No login shell; commands get only `HOME`, `LANG`, `LOGNAME`, `PATH`, `SHELL` and `USER` (no keys, no `CODEX_HOME`) |
| `[history] persistence = "none"`, `[analytics] enabled = false`, `check_for_update_on_startup = false` | Nothing kept, sent or checked beyond the run |
| `project_root_markers = []`, `project_doc_max_bytes = 1048576` | `AGENTS.md` from the run's folder only, read whole (Codex's default stops at 32 KiB; the class assistant's is 25 KiB) |
| `[[skills.config]]` entries, `enabled = false` | Switches off, by path, the skills Codex installs into a new home (5 on 0.164.0) and any in `~/.agents/skills`, which Codex reads whatever `CODEX_HOME` is |

Reads are granted, never denied by name: Codex shows the model every path a
profile denies, so a deny list of your home folder would put the names of
your files in front of the model.

The runner also leaves these variables out of Codex's environment:
`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_FEDERATION_RULE_ID`,
`OPENAI_IDENTITY_TOKEN_FILE`, and every `CODEX_` variable (among them
`CODEX_API_KEY`, `CODEX_ACCESS_TOKEN` and `CODEX_CONNECTORS_TOKEN`, through
which Codex can take another login or connectors, and those a Codex session
sets for programs it starts). With `--use-api-key` it keeps `OPENAI_API_KEY`
and `CODEX_API_KEY` and doesn't link your login. The same check on the
temporary folder as for Claude Code applies: the runner refuses to start if a
`CLAUDE.md` or `AGENTS.md` sits above it.

### The check on every Codex run

Codex's event stream doesn't list what loaded, so the check comes first.
Once per command, `codex features list` must show every feature above off
and `codex mcp list` no MCP server. Before each run, `codex debug
prompt-input` renders, in the run's prepared folder and without calling a
model, everything the model will be given. The run doesn't start, no further
runs start, and the runner says STOPPED, if it shows any of:

- an MCP server, a tool whose name starts with `mcp__`, or plugin installation;
- recommended plugins, apps or memories;
- a skill from anywhere but the run's folder;
- `AGENTS.md` instructions from anywhere but the run's folder (a global `AGENTS.md`);
- developer instructions other than Codex's own (from a config the runner didn't write).

During the run, an MCP tool call or a web search stops it at once. The one
exception is Codex's own three tools for MCP resources, which Codex reports
as calls to a server named `codex`: with no server configured they find
nothing. What the check saw is kept in each run's `run.json` under
`isolation`.

### What was verified (Codex)

On 2026-10-26, on Linux, with Codex 0.164.0 logged in to a ChatGPT plan, and
`OPENAI_API_KEY` set in the environment.

**Without the runner.** Rendered with `codex debug prompt-input` in a new
folder, the computer's own Codex setup offered four personal skills, a list
of recommended plugins (Gmail, Google Calendar, Google Drive, Outlook, Slack
and others) and subagent tools. A test Codex folder was then made with a
canary of each kind: an MCP server (a script that writes to a log when it
starts), `developer_instructions`, a global `AGENTS.md`, a personal skill
and memories turned on, and a personal skill in `~/.agents/skills`. With
that folder as `CODEX_HOME`, the rendered input held the developer
instructions, the global `AGENTS.md`, both personal skills, and the MCP
server started.

**With the runner**, the same test folder as `CODEX_HOME`: `doctor --runner
codex` found every feature above off, 0 MCP servers, and the skill in
`~/.agents/skills` switched off; its probe run (a real run) found nothing of
the test folder's loaded, the probe's own `CLAUDE.md` (with an `@` import)
and skill did load, a file in the home folder could not be read, and no
session was saved. The rendered input of an isolated run held none of the
five canary texts, and the run's own instructions; the MCP server's log
stayed empty; the only Codex variable passed to Codex was `CODEX_HOME`.
This held for the four real runs and two judgments in
`examples/recorded/demo-graph-removed-codex/`.

**File and shell access**, with the runner's sandbox (`codex sandbox -P`
with the runner's profile, and in the real runs):

| Asked to | Result |
| --- | --- |
| read and write a file in its folder | allowed |
| read `~/.bashrc`, `~/.codex/auth.json`, `~/.codex/config.toml`, `~/.codex/history.jsonl` | refused |
| list `~/Documents`, `~/.claude`, `~/.codex` | refused; the home folder shows only the empty folders on the way to Codex's installation |
| write to `/tmp` | goes to a private `/tmp` that vanishes when the command ends |
| run `kb/kb search Dana`, `python3`, `git` | allowed |
| reach the network | refused |

In the recorded runs, an assistant ran `ls -ld Grants/current
~/.claude/projects` (the class assistant's `CLAUDE.md` mentions such
folders) and was refused.

**What did not work.**

- Denying each item of the home folder by name works in the sandbox, but
  Codex lists every denied path to the model (238 names on the test
  computer). Denying the home folder as a whole stops Codex itself, which is
  installed there. Granting reads instead lists only the readable folders.
- A temporary `CODEX_HOME` under `/tmp`: Codex refuses to put its helper
  programs there, so the runner uses your cache folder.
- `features.multi_agent = false` does not remove the subagent tools from the
  GPT-6 models, whose tool set includes them.
- The first four demonstration runs were stopped by the check: the model
  called Codex's own `list_mcp_resources` (it returned `{"resources":[]}`).
  Those three tools are now allowed and named in the trace as Claude Code
  names its equivalents; any other MCP call still stops a run.

### What isolation does not cover (Codex)

- **Subagents.** The GPT-6 models are offered tools to start subagents. A
  subagent runs in the same process, with the same settings and sandbox.
- **System files.** Codex's minimal set of system paths (`/usr`, `/etc` and
  the like) can be read; your home folder can't.
- **System-wide Codex settings** in `/etc/codex/` (or managed by your
  organization) apply to every Codex session. `doctor --runner codex` says if
  `/etc/codex` exists, and the check before each run stops one that loads
  anything from it.
- **Your login** is shared through the link. If you log out or switch
  accounts while runs go on, they fail.
- **Other computers.** Verified on Linux, where the sandbox is bubblewrap.
  macOS and Windows use other sandboxes. Run `python3 run_ab.py doctor
  --runner codex` on yours: its probe tries to read a file in your home
  folder and says FIX if it can.
- **`--use-api-key`** was tested with the stand-in only.
- **Newer versions of Codex** may change what these settings do. The checks
  before and during every run are there for that.

## The helper (`ask`)

`python3 run_ab.py ask` is your own session, in Skill Eval Lite's folder,
but it leaves out the same things a run does.

- **Claude Code** starts with `--setting-sources project`,
  `--strict-mcp-config`, the settings that turn off auto memory and claude.ai
  connectors, and the same environment variables as a run. It starts in
  `--permission-mode manual`, so it asks before every command and every edit,
  even if your own default is a mode that doesn't ask. A one-question answer
  (`ask "..."`) is print mode with only `Read`, `Glob` and `Grep`.
- **Codex** gets a temporary `CODEX_HOME` like a run's, with the same features
  off (no connectors, plugins, hooks, memories or personal skills), the
  helper's instructions as `developer_instructions`, and Skill Eval Lite's
  folder marked as trusted so that Codex doesn't ask. It works in
  `workspace-write` with no network, and asks you (`approval_policy =
  "on-request"`) before it runs anything outside that sandbox: `doctor`,
  `run`, `judge` and `suite` need the network, so it asks for those. A
  one-question answer is `codex exec` with a read-only sandbox.

Verified on 2026-10-26 (Claude Code 2.1.311, Codex 0.164.0, with the API keys
unset): Claude Code showed "manual mode on"; Codex showed its approval prompt
before running `doctor`, with the helper's reason, and the temporary
`CODEX_HOME` was gone after the session.

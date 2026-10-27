#!/usr/bin/env bash
# Pre-release check for Skill Eval Lite: follow the README's walkthrough as a
# student would, with a fresh Claude Code that has never been logged in, in a
# throwaway home folder. Your own ~/.claude, settings and Claude Code install
# are not touched.
#
#   dev/fresh-trial.sh                  a new trial, then a shell in it
#   dev/fresh-trial.sh --source PATH    clone from PATH (default: this
#                                       repository's origin remote, else this
#                                       repository's folder)
#   dev/fresh-trial.sh --keep-api-key   keep ANTHROPIC_API_KEY (default: dropped,
#                                       so Claude Code asks you to log in)
#   dev/fresh-trial.sh --no-shell       set up the trial and stop (for testing)
#   dev/fresh-trial.sh --list           list the trials
#   dev/fresh-trial.sh --clean          remove every trial (asks first)
#
# A trial is SEL_TRIALS/trial-<date-time>/ (SEL_TRIALS defaults to
# ~/skill-eval-lite-trials) with two folders: home/ (HOME in the trial, where
# Claude Code is installed fresh with the official installer) and work/
# (where the shell starts). home/.gitconfig rewrites the README's clone URL,
# https://github.com/vanderbilt-ms-ai/skill-eval-lite, to the source, so the
# README's commands work as written before anything is on GitHub. Only
# committed work is cloned. The installer needs the network.
#
# Reads: this repository (its origin remote). Writes: the trial folder only.
# Made for AI 5500 (Vanderbilt, Fall 2026), October 2026.
set -euo pipefail

PUBLIC_URL="https://github.com/vanderbilt-ms-ai/skill-eval-lite"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
TRIALS="${SEL_TRIALS:-$HOME/skill-eval-lite-trials}"
SOURCE=""
KEEP_KEY=0
SHELL_AFTER=1

while [ $# -gt 0 ]; do
  case "$1" in
    --source) SOURCE="$2"; shift 2 ;;
    --keep-api-key) KEEP_KEY=1; shift ;;
    --no-shell) SHELL_AFTER=0; shift ;;
    --list) ls -1d "$TRIALS"/trial-* 2>/dev/null || echo "No trials in $TRIALS."; exit 0 ;;
    --clean)
      if [ ! -d "$TRIALS" ]; then echo "No trials in $TRIALS."; exit 0; fi
      echo "This removes $TRIALS and everything in it:"
      ls -1d "$TRIALS"/trial-* 2>/dev/null || true
      read -r -p "Remove them? [y/N] " yes
      if [ "$yes" = "y" ] || [ "$yes" = "Y" ]; then
        chmod -R u+w "$TRIALS" 2>/dev/null || true
        rm -rf "$TRIALS"
        echo "Removed."
      else
        echo "Nothing removed. To remove them yourself: rm -rf \"$TRIALS\""
      fi
      exit 0 ;;
    -h|--help) sed -n '2,27p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
done

if [ -z "$SOURCE" ]; then
  SOURCE="$(git -C "$HERE" remote get-url origin 2>/dev/null || true)"
  [ -n "$SOURCE" ] || SOURCE="$HERE"
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
T="$TRIALS/trial-$STAMP"
mkdir -p "$T/home" "$T/work"
echo "Trial: $T"
echo "Clone source for $PUBLIC_URL: $SOURCE"

cat > "$T/home/.gitconfig" <<EOF
# Written by dev/fresh-trial.sh: the README's clone URL, before publication.
[url "$SOURCE"]
	insteadOf = $PUBLIC_URL
	insteadOf = $PUBLIC_URL.git
[init]
	defaultBranch = main
EOF

# A minimal environment: no Claude Code session variables, no API key (unless
# asked), HOME in the trial. SSH still finds your keys (ssh reads them from
# your account's home, not from HOME) and your agent (SSH_AUTH_SOCK).
ENVV=(HOME="$T/home" PATH="$T/home/.local/bin:/usr/local/bin:/usr/bin:/bin"
      TERM="${TERM:-xterm-256color}" LANG="${LANG:-C.UTF-8}" USER="${USER:-}" LOGNAME="${LOGNAME:-${USER:-}}"
      SHELL=/bin/bash SEL_TRIAL="$T")
for v in SSH_AUTH_SOCK DISPLAY WAYLAND_DISPLAY XDG_RUNTIME_DIR DBUS_SESSION_BUS_ADDRESS; do
  if [ -n "${!v:-}" ]; then ENVV+=("$v=${!v}"); fi
done
if [ "$KEEP_KEY" = 1 ] && [ -n "${ANTHROPIC_API_KEY:-}" ]; then ENVV+=("ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY"); fi

echo "Installing Claude Code into $T/home with the official installer..."
if ! env -i "${ENVV[@]}" bash -c 'curl -fsSL https://claude.ai/install.sh | bash' > "$T/install.log" 2>&1; then
  echo "The installer failed (it needs the network); see $T/install.log." >&2
  tail -5 "$T/install.log" >&2 || true
  exit 1
fi
env -i "${ENVV[@]}" bash -c 'command -v claude && claude --version' || { echo "claude is not on the trial's PATH; see $T/install.log" >&2; exit 1; }

cat > "$T/home/.trialrc" <<'EOF'
# A short prompt that says only that this is the trial (the working path is long, and the
# demonstration terminal's font is large).
PS1='\[\e[1;35m\](trial)\[\e[0m\] \$ '
cd "$SEL_TRIAL/work"
cat <<BANNER

  Skill Eval Lite trial: $SEL_TRIAL
  HOME is $HOME: a fresh Claude Code, not logged in. Your own ~/.claude is not used.

  The README's walkthrough:
    1. claude                       log in when it asks, then type /exit
       (if the browser that opens is not logged in to claude.ai, copy the URL
        Claude Code prints into your usual browser, and paste the code back)
    2. git clone https://github.com/vanderbilt-ms-ai/skill-eval-lite && cd skill-eval-lite
    3. python3 run_ab.py doctor
    4. python3 run_ab.py setup ../class-assistant
    5. python3 run_ab.py check examples/demo-one-line.toml
       (round B's line: examples/class-assistant/rounds/one-line/.claude/identity/voice.md)
    6. python3 run_ab.py run examples/demo-one-line.toml --assistant ../class-assistant --jobs 6
    7. python3 run_ab.py judge runs/demo-one-line
    8. xdg-open wizard.html          then load runs/demo-one-line/bundle.json in step 1

  Type exit to leave. To remove trials: dev/fresh-trial.sh --clean

BANNER
EOF

if [ "$SHELL_AFTER" = 1 ]; then
  cd "$T/work"
  exec env -i "${ENVV[@]}" bash --rcfile "$T/home/.trialrc" -i
else
  echo "Set up. To enter it: cd $T/work && env -i HOME=$T/home PATH=$T/home/.local/bin:/usr/bin:/bin SEL_TRIAL=$T bash --rcfile $T/home/.trialrc -i"
fi

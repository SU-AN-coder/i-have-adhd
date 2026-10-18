#!/usr/bin/env sh
# SessionStart hook: injects the full i-have-adhd ruleset when the user has
# opted in by creating $CLAUDE_CONFIG_DIR/.i-have-adhd-always (default ~/.claude).
# Never blocks session start: any failure exits 0.
#
# POSIX fallback for environments where the default Node hook cannot run. It
# works with sh on macOS/Linux and Git Bash on Windows without a Node install.
#
# When CLAUDE_CODE_SUBPROCESS_ENV_SCRUB strips CLAUDE_CONFIG_DIR from the hook
# environment (#255), the config dir is recovered from the plugin install path
# (<config dir>/plugins/cache/...); the default ~/.claude stays as a fallback.

flag_name=".i-have-adhd-always"

# Echo the config dir implied by an installed plugin path, or nothing when the
# script does not live under a plugins directory (e.g. a --plugin-dir checkout).
# The backslash patterns cover a Git Bash caller that passes a native Windows
# path straight through.
config_dir_from_install_path() {
  case "$1" in
    */plugins/cache/*)    printf '%s\n' "${1%%/plugins/cache/*}" ;;
    *\\plugins\\cache\\*) printf '%s\n' "${1%%\\plugins\\cache\\*}" ;;
    */plugins/*)          printf '%s\n' "${1%%/plugins/*}" ;;
    *\\plugins\\*)        printf '%s\n' "${1%%\\plugins\\*}" ;;
    *) return 1 ;;
  esac
}

script_dir=$(dirname -- "$0")

# CLAUDE_CONFIG_DIR stays authoritative when it is present: a user who pointed
# Claude Code at another config dir should not have the hook fire from a
# location they did not choose. Without it, the config dir implied by the
# install path and the default ~/.claude are tried in order, and only a
# candidate that actually holds the flag counts.
if [ -n "${CLAUDE_CONFIG_DIR:-}" ]; then
  flag_path="$CLAUDE_CONFIG_DIR/$flag_name"
else
  flag_path=""
  derived_dir=$(config_dir_from_install_path "$script_dir") || derived_dir=""
  for candidate_dir in "$derived_dir" "$HOME/.claude"; do
    [ -n "$candidate_dir" ] || continue
    if [ -f "$candidate_dir/$flag_name" ]; then
      flag_path="$candidate_dir/$flag_name"
      break
    fi
  done
fi

# Only fire when the user has opted in.
[ -n "$flag_path" ] || exit 0
[ -f "$flag_path" ] || exit 0

# $0 is the absolute script path substituted into hooks.json by Claude Code,
# so resolve SKILL.md relative to it instead of trusting an exported env var.
skill_path="$script_dir/../skills/i-have-adhd/SKILL.md"
[ -f "$skill_path" ] || exit 0

# Strip a leading YAML frontmatter block (--- ... --- at the very top of file).
# An unterminated fence is not frontmatter, so the whole file is kept unless the
# closing delimiter exists (two passes; matches the Node and PowerShell hooks).
body=$(awk '
  NR == FNR {
    if (NR == 1 && $0 ~ /^---[[:space:]]*$/) { in_fm = 1; next }
    if (in_fm && $0 ~ /^---[[:space:]]*$/)   { in_fm = 0; closed = 1 }
    next
  }
  FNR == 1 { strip = closed }
  strip && FNR == 1 && $0 ~ /^---[[:space:]]*$/ { skipping = 1; next }
  skipping && $0 ~ /^---[[:space:]]*$/          { skipping = 0; next }
  !skipping { print }
' "$skill_path" "$skill_path") || exit 0

printf 'ADHD MODE ACTIVE (always-on). The ruleset below applies to every response. "stop adhd mode" turns it off for this session; delete %s to turn always-on off for good.\n\n%s\n' \
  "$flag_path" "$body"

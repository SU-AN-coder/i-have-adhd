// SessionStart hook: injects the full i-have-adhd ruleset when the user has
// opted in by creating $CLAUDE_CONFIG_DIR/.i-have-adhd-always (default ~/.claude).
// Never blocks session start: any failure exits 0.
//
// Runs under Node so it works on macOS, Linux, and Windows. The shared Claude
// Code/Codex hook launches this module from the plugin-root environment rather
// than relying on platform-specific shell expansion for the script path.
// Native sh and PowerShell implementations remain available as fallbacks.
//
// When CLAUDE_CODE_SUBPROCESS_ENV_SCRUB strips CLAUDE_CONFIG_DIR from the hook
// environment (#255), the config dir is recovered from the plugin install path
// (<config dir>/plugins/cache/...); the default ~/.claude stays as a fallback.

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const FLAG_NAME = ".i-have-adhd-always";

// Installed plugins are copied to <config dir>/plugins/cache/<marketplace>/...
// so the install path reveals the config dir even when the variable is gone.
// Returns "" for installs outside that layout, such as a --plugin-dir checkout.
function configDirFromInstallPath(scriptDir) {
  const markers = [
    `${path.sep}plugins${path.sep}cache${path.sep}`,
    "/plugins/cache/",
    "\\plugins\\cache\\",
    `${path.sep}plugins${path.sep}`,
    "/plugins/",
    "\\plugins\\",
  ];
  for (const marker of markers) {
    const index = scriptDir.indexOf(marker);
    if (index > 0) return scriptDir.slice(0, index);
  }
  return "";
}

// CLAUDE_CONFIG_DIR stays authoritative when it is present: a user who pointed
// Claude Code at another config dir should not have the hook fire from a
// location they did not choose. Without it, the config dir implied by the
// install path and the default ~/.claude are tried in order, and only a
// candidate that actually holds the flag counts.
function resolveFlagPath(scriptDir) {
  if (process.env.CLAUDE_CONFIG_DIR) {
    return path.join(process.env.CLAUDE_CONFIG_DIR, FLAG_NAME);
  }
  const candidates = [];
  const derived = configDirFromInstallPath(scriptDir);
  if (derived) candidates.push(path.join(derived, FLAG_NAME));
  candidates.push(path.join(os.homedir(), ".claude", FLAG_NAME));
  return candidates.find((candidate) => fs.existsSync(candidate)) || "";
}

try {
  // Resolve everything relative to this script's own location, not a trusted
  // environment variable.
  const scriptDir = path.dirname(fileURLToPath(import.meta.url));
  const flagPath = resolveFlagPath(scriptDir);

  // Only fire when the user has opted in.
  if (!flagPath || !fs.existsSync(flagPath)) process.exit(0);

  const skillPath = path.join(scriptDir, "..", "skills", "i-have-adhd", "SKILL.md");
  if (!fs.existsSync(skillPath)) process.exit(0);

  // Strip a leading YAML frontmatter block (--- ... --- at the very top of file).
  const body = fs
    .readFileSync(skillPath, "utf8")
    .replace(
      /^---[^\S\r\n]*\r?\n[\s\S]*?\r?\n---[^\S\r\n]*(?:\r?\n|$)/,
      "",
    )
    .replace(/(?:\r?\n)+$/, "");

  process.stdout.write(
    "ADHD MODE ACTIVE (always-on). The ruleset below applies to every response. " +
      '"stop adhd mode" turns it off for this session; ' +
      `delete ${flagPath} to turn always-on off for good.\n\n${body}\n`,
  );
} catch {
  // Never block session start.
  process.exit(0);
}

# SessionStart hook fallback for Windows PowerShell. Injects the full
# i-have-adhd ruleset when the user has opted in by creating
# $CLAUDE_CONFIG_DIR/.i-have-adhd-always (default ~/.claude).
# Never blocks session start: any failure exits 0.
#
# When CLAUDE_CODE_SUBPROCESS_ENV_SCRUB strips CLAUDE_CONFIG_DIR from the hook
# environment (#255), the config dir is recovered from the plugin install path
# (<config dir>\plugins\cache\...); the default ~/.claude stays as a fallback.

$flagName = ".i-have-adhd-always"

# Installed plugins are copied to <config dir>\plugins\cache\<marketplace>\...
# so the install path reveals the config dir even when the variable is gone.
# Returns "" for installs outside that layout, such as a --plugin-dir checkout.
function Get-ConfigDirFromInstallPath([string]$ScriptDir) {
  foreach ($marker in @('\plugins\cache\', '/plugins/cache/', '\plugins\', '/plugins/')) {
    $index = $ScriptDir.IndexOf($marker, [System.StringComparison]::OrdinalIgnoreCase)
    if ($index -gt 0) { return $ScriptDir.Substring(0, $index) }
  }
  return ""
}

try {
  $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

  # CLAUDE_CONFIG_DIR stays authoritative when it is present: a user who pointed
  # Claude Code at another config dir should not have the hook fire from a
  # location they did not choose. Without it, the config dir implied by the
  # install path and the default ~/.claude are tried in order, and only a
  # candidate that actually holds the flag counts.
  if ($env:CLAUDE_CONFIG_DIR) {
    $flagPath = Join-Path $env:CLAUDE_CONFIG_DIR $flagName
  } else {
    $flagPath = ""
    $candidates = @()
    $derivedDir = Get-ConfigDirFromInstallPath $scriptDir
    if ($derivedDir) { $candidates += (Join-Path $derivedDir $flagName) }
    $defaultDir = Join-Path ([Environment]::GetFolderPath("UserProfile")) ".claude"
    $candidates += (Join-Path $defaultDir $flagName)
    foreach ($candidate in $candidates) {
      if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        $flagPath = $candidate
        break
      }
    }
  }

  if (-not $flagPath) {
    exit 0
  }

  if (-not (Test-Path -LiteralPath $flagPath -PathType Leaf)) {
    exit 0
  }

  $skillPath = Join-Path $scriptDir "../skills/i-have-adhd/SKILL.md"
  if (-not (Test-Path -LiteralPath $skillPath -PathType Leaf)) {
    exit 0
  }

  $lines = [System.IO.File]::ReadAllLines($skillPath)
  $bodyStart = 0

  if ($lines.Length -gt 0 -and $lines[0] -match '^---\s*$') {
    # Only treat the block as frontmatter when the closing delimiter exists;
    # an unterminated fence is not frontmatter, so keep the whole file.
    for ($i = 1; $i -lt $lines.Length; $i++) {
      if ($lines[$i] -match '^---\s*$') {
        $bodyStart = $i + 1
        break
      }
    }
  }

  $body = if ($bodyStart -lt $lines.Length) {
    [string]::Join([Environment]::NewLine, $lines[$bodyStart..($lines.Length - 1)])
  } else {
    ""
  }

  $banner = 'ADHD MODE ACTIVE (always-on). The ruleset below applies to every response. ' +
    '"stop adhd mode" turns it off for this session; delete '
  [Console]::Out.Write($banner + $flagPath + " to turn always-on off for good.`n`n" + $body + "`n")
} catch {
  # Never block session start.
  exit 0
}

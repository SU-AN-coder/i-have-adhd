import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AlwaysOnHookTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.plugin_root = Path(self.temp_dir.name) / "plugin with spaces"
        shutil.copytree(ROOT / "hooks", self.plugin_root / "hooks")
        shutil.copytree(ROOT / "skills", self.plugin_root / "skills")
        self.config_dir = Path(self.temp_dir.name) / "claude config"
        self.config_dir.mkdir()

    def runtimes(self, plugin_root=None, require_overridable_home=False):
        plugin_root = plugin_root or self.plugin_root
        runtimes = []
        if node := shutil.which("node"):
            runtimes.append(("node", [node, plugin_root / "hooks" / "always-on.mjs"]))
        if sh := shutil.which("sh"):
            runtimes.append(("sh", [sh, plugin_root / "hooks" / "always-on.sh"]))
        if powershell := shutil.which("pwsh") or shutil.which("powershell"):
            runtimes.append(
                (
                    "powershell",
                    [
                        powershell,
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        plugin_root / "hooks" / "always-on.ps1",
                    ],
                )
            )
        if require_overridable_home:
            # Tests that point the default config dir at a temporary home only
            # work where the runtime reads HOME/USERPROFILE. On Windows only Node
            # does: Git Bash and PowerShell resolve the OS profile instead.
            return [
                (name, command)
                for name, command in runtimes
                if os.name != "nt" or name == "node"
            ]
        return runtimes

    def installed_plugin_root(self, config_dir):
        """Lay the plugin out the way Claude Code installs one into a config dir."""
        plugin_root = config_dir / "plugins" / "cache" / "i-have-adhd" / "i-have-adhd" / "0.4.1"
        shutil.copytree(ROOT / "hooks", plugin_root / "hooks")
        shutil.copytree(ROOT / "skills", plugin_root / "skills")
        return plugin_root

    def empty_home(self, name="home"):
        home = Path(self.temp_dir.name) / name
        home.mkdir()
        return home

    def run_hook_env(self, command, config_dir=None, home=None):
        """Run a hook with an explicit environment.

        ``config_dir=None`` removes CLAUDE_CONFIG_DIR, which is what
        CLAUDE_CODE_SUBPROCESS_ENV_SCRUB leaves the hook with (#255).
        """
        env = os.environ.copy()
        env.pop("CLAUDE_CONFIG_DIR", None)
        if config_dir is not None:
            env["CLAUDE_CONFIG_DIR"] = str(config_dir)
        if home is not None:
            env["HOME"] = str(home)
            env["USERPROFILE"] = str(home)
        return subprocess.run(
            [str(part) for part in command],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

    def run_hook(self, command):
        return self.run_hook_env(command, config_dir=self.config_dir)

    def run_codex_hook(self, plugin_root=None):
        config = json.loads((ROOT / "hooks" / "hooks.json").read_text())
        hook = config["hooks"]["SessionStart"][0]["hooks"][0]
        env = os.environ.copy()
        env["CLAUDE_CONFIG_DIR"] = str(self.config_dir)
        plugin_root = plugin_root or self.plugin_root
        env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)
        env["PLUGIN_ROOT"] = str(plugin_root)
        return subprocess.run(
            hook["command"],
            check=False,
            capture_output=True,
            env=env,
            input=json.dumps(
                {
                    "session_id": "test-session",
                    "cwd": str(self.plugin_root),
                    "hook_event_name": "SessionStart",
                    "source": "startup",
                }
            ),
            shell=True,
            text=True,
        )

    @staticmethod
    def normalize(stdout):
        # The banner embeds the flag path. On Windows the sh runtime joins it
        # with "/" while node and PowerShell join with "\"; both name the same
        # file, so unify separators (and newlines) before comparing runtimes.
        return stdout.replace("\r\n", "\n").replace("\\", "/")

    @staticmethod
    def banner_flag_path(stdout):
        match = re.search(r"delete (.*) to turn always-on off for good\.", stdout)
        return match.group(1) if match else None

    def assert_banner_names_flag(self, stdout, flag):
        # Compare the trailing path components: a Windows drive form
        # ("C:/Users/x/.claude") and an MSYS one ("/c/Users/x/.claude") name the
        # same file, and the assertion that matters is which config dir the hook
        # actually picked.
        self.assertIn("ADHD MODE ACTIVE (always-on)", stdout)
        found = self.banner_flag_path(stdout) or ""
        expected_tail = self.normalize(str(flag)).split("/")[-2:]
        self.assertEqual(expected_tail, found.split("/")[-2:])

    def test_hook_is_silent_without_opt_in_flag(self):
        self.assertTrue(self.runtimes(), "no hook runtime is available")

        for name, command in self.runtimes():
            with self.subTest(runtime=name):
                result = self.run_hook(command)
                self.assertEqual(0, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertEqual("", result.stderr)

    def test_runtimes_strip_frontmatter_with_trailing_whitespace(self):
        skill_path = self.plugin_root / "skills" / "i-have-adhd" / "SKILL.md"
        skill_path.write_text("---   \nname: fixture\n--- \t\nFixture body.\n")
        (self.config_dir / ".i-have-adhd-always").touch()
        outputs = {}

        for name, command in self.runtimes():
            with self.subTest(runtime=name):
                result = self.run_hook(command)
                self.assertEqual(0, result.returncode)
                self.assertEqual("", result.stderr)
                normalized = self.normalize(result.stdout)
                self.assertNotIn("name: fixture", normalized)
                self.assertIn("\n\nFixture body.\n", normalized)
                outputs[name] = normalized

        self.assertEqual(1, len(set(outputs.values())))

    def test_runtimes_keep_content_when_frontmatter_is_unclosed(self):
        # An opening --- with no closing delimiter is not frontmatter. Keeping
        # the whole file beats injecting a banner that promises "the ruleset
        # below" followed by nothing.
        skill_path = self.plugin_root / "skills" / "i-have-adhd" / "SKILL.md"
        skill_path.write_text("---\nname: fixture\nFixture body, fence never closed.\n")
        (self.config_dir / ".i-have-adhd-always").touch()
        outputs = {}

        for name, command in self.runtimes():
            with self.subTest(runtime=name):
                result = self.run_hook(command)
                self.assertEqual(0, result.returncode)
                self.assertEqual("", result.stderr)
                normalized = self.normalize(result.stdout)
                self.assertIn("Fixture body, fence never closed.", normalized)
                outputs[name] = normalized

        self.assertEqual(1, len(set(outputs.values())))

    def test_codex_command_runs_the_hook_instead_of_parsing_session_json(self):
        (self.config_dir / ".i-have-adhd-always").touch()

        result = self.run_codex_hook()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        self.assertIn("ADHD MODE ACTIVE (always-on)", result.stdout)

    def test_codex_command_is_silent_without_opt_in_flag(self):
        result = self.run_codex_hook()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        self.assertEqual("", result.stdout)

    def test_codex_command_swallows_missing_plugin_errors(self):
        result = self.run_codex_hook(self.plugin_root / "missing plugin")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        self.assertEqual("", result.stdout)

    def test_config_dir_is_recovered_from_the_plugin_cache_without_the_env_var(self):
        # #255: with CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1, Claude Code leaves
        # CLAUDE_CONFIG_DIR out of the hook environment, while the installed
        # plugin copy still sits under <config dir>/plugins/cache/. The flag must
        # be found there rather than falling back to ~/.claude and going quiet.
        config_dir = Path(self.temp_dir.name) / "custom claude config"
        config_dir.mkdir()
        plugin_root = self.installed_plugin_root(config_dir)
        flag = config_dir / ".i-have-adhd-always"
        flag.touch()
        home = self.empty_home()
        outputs = {}

        for name, command in self.runtimes(plugin_root):
            with self.subTest(runtime=name):
                result = self.run_hook_env(command, home=home)
                self.assertEqual(0, result.returncode)
                self.assertEqual("", result.stderr)
                normalized = self.normalize(result.stdout)
                self.assert_banner_names_flag(normalized, flag)
                outputs[name] = self.banner_flag_path(normalized)

        self.assertEqual(1, len(set(outputs.values())))

    def test_plugin_cache_install_without_a_flag_stays_silent(self):
        config_dir = Path(self.temp_dir.name) / "custom claude config"
        config_dir.mkdir()
        plugin_root = self.installed_plugin_root(config_dir)
        home = self.empty_home()

        for name, command in self.runtimes(plugin_root, require_overridable_home=True):
            with self.subTest(runtime=name):
                result = self.run_hook_env(command, home=home)
                self.assertEqual(0, result.returncode)
                self.assertEqual("", result.stderr)
                self.assertEqual("", result.stdout)

    def test_default_config_dir_still_works_without_the_env_var(self):
        # A --plugin-dir or git checkout install has no plugins/cache path to
        # derive from, so ~/.claude keeps working as the default.
        home = self.empty_home()
        (home / ".claude").mkdir()
        flag = home / ".claude" / ".i-have-adhd-always"
        flag.touch()
        outputs = {}

        for name, command in self.runtimes(require_overridable_home=True):
            with self.subTest(runtime=name):
                result = self.run_hook_env(command, home=home)
                self.assertEqual(0, result.returncode)
                self.assertEqual("", result.stderr)
                normalized = self.normalize(result.stdout)
                self.assert_banner_names_flag(normalized, flag)
                outputs[name] = self.banner_flag_path(normalized)

        self.assertEqual(1, len(set(outputs.values())))

    def test_home_flag_is_used_when_the_install_path_has_no_flag(self):
        # Installed under a config dir that never got a flag, while the user's
        # long-standing ~/.claude flag is the only opt-in left standing.
        config_dir = Path(self.temp_dir.name) / "custom claude config"
        config_dir.mkdir()
        plugin_root = self.installed_plugin_root(config_dir)
        home = self.empty_home()
        (home / ".claude").mkdir()
        flag = home / ".claude" / ".i-have-adhd-always"
        flag.touch()

        for name, command in self.runtimes(plugin_root, require_overridable_home=True):
            with self.subTest(runtime=name):
                result = self.run_hook_env(command, home=home)
                self.assertEqual(0, result.returncode)
                self.assertEqual("", result.stderr)
                self.assert_banner_names_flag(self.normalize(result.stdout), flag)

    def test_explicit_config_dir_is_authoritative_when_its_flag_is_missing(self):
        # Someone who points Claude Code at another config dir keeps the old
        # behaviour: a flag left in the install-path dir or in ~/.claude must
        # not silently re-enable always-on for that session.
        config_dir = Path(self.temp_dir.name) / "custom claude config"
        config_dir.mkdir()
        plugin_root = self.installed_plugin_root(config_dir)
        (config_dir / ".i-have-adhd-always").touch()
        home = self.empty_home()
        (home / ".claude").mkdir()
        (home / ".claude" / ".i-have-adhd-always").touch()
        explicit_dir = Path(self.temp_dir.name) / "explicit config"
        explicit_dir.mkdir()

        for name, command in self.runtimes(plugin_root):
            with self.subTest(runtime=name):
                result = self.run_hook_env(command, config_dir=explicit_dir, home=home)
                self.assertEqual(0, result.returncode)
                self.assertEqual("", result.stderr)
                self.assertEqual("", result.stdout)

    def test_hook_uses_a_shared_claude_and_codex_launcher(self):
        config = json.loads((ROOT / "hooks" / "hooks.json").read_text())
        hook = config["hooks"]["SessionStart"][0]["hooks"][0]

        self.assertNotIn("args", hook)
        command = hook["command"]
        self.assertRegex(command, r'^node(?: --input-type=module)? -e "')
        self.assertIn("process.env.CLAUDE_PLUGIN_ROOT", command)
        self.assertIn("process.env.PLUGIN_ROOT", command)
        self.assertIn("await import", command)
        self.assertIn(".catch", command)


if __name__ == "__main__":
    unittest.main()

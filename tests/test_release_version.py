import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_release_version  # noqa: E402


def write_manifests(root: Path, versions: dict) -> None:
    """Create one manifest per entry, copying the repo's own manifest names."""
    for name, version in versions.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"name": "i-have-adhd"}
        if version is not None:
            payload["version"] = version
        path.write_text(json.dumps(payload), encoding="utf8")


class ReleaseVersionTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    def test_repository_manifests_agree_on_one_version(self):
        """Pins AGENTS.md: shared metadata, including versions, stays aligned."""
        versions = check_release_version.manifest_versions(ROOT)

        self.assertEqual(sorted(check_release_version.MANIFESTS), sorted(versions))
        try:
            declared = check_release_version.declared_version(versions)
        except ValueError as exc:
            self.fail(str(exc))
        self.assertRegex(declared, r"^\d+\.\d+\.\d+$")
        self.assertEqual(declared, check_release_version.check(f"v{declared}", ROOT))

    def test_matching_tag_is_accepted(self):
        write_manifests(self.root, {name: "1.2.3" for name in check_release_version.MANIFESTS})

        self.assertEqual("1.2.3", check_release_version.check("v1.2.3", self.root))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(0, check_release_version.main(["v1.2.3", "--root", str(self.root)]))
        self.assertEqual(
            f"v1.2.3 matches version 1.2.3 in {len(check_release_version.MANIFESTS)} manifests.\n",
            output.getvalue(),
        )

    def test_prerelease_tag_releases_the_declared_version(self):
        write_manifests(self.root, {name: "1.2.3" for name in check_release_version.MANIFESTS})

        self.assertEqual("1.2.3", check_release_version.check("v1.2.3-rc.1", self.root))

    def test_tag_behind_the_manifests_is_rejected(self):
        write_manifests(self.root, {name: "1.2.3" for name in check_release_version.MANIFESTS})

        with self.assertRaisesRegex(ValueError, r"names 1\.2\.2, but the manifests declare 1\.2\.3"):
            check_release_version.check("v1.2.2", self.root)

    def test_manifest_drift_is_reported_by_name(self):
        versions = {name: "1.2.3" for name in check_release_version.MANIFESTS}
        versions["qwen-extension.json"] = "1.2.2"
        write_manifests(self.root, versions)

        with self.assertRaises(ValueError) as raised:
            check_release_version.check("v1.2.3", self.root)

        message = str(raised.exception)
        self.assertIn("qwen-extension.json=1.2.2", message)
        self.assertIn("package.json=1.2.3", message)

    def test_manifest_without_a_version_is_rejected(self):
        versions = {name: "1.2.3" for name in check_release_version.MANIFESTS}
        versions[".claude-plugin/plugin.json"] = None
        write_manifests(self.root, versions)

        with self.assertRaisesRegex(ValueError, r"\.claude-plugin/plugin\.json: version must be"):
            check_release_version.check("v1.2.3", self.root)

    def test_missing_manifest_is_rejected(self):
        versions = {name: "1.2.3" for name in check_release_version.MANIFESTS}
        del versions["kimi.plugin.json"]
        write_manifests(self.root, versions)

        with self.assertRaisesRegex(ValueError, r"kimi\.plugin\.json: manifest not found"):
            check_release_version.check("v1.2.3", self.root)

    def test_tags_that_do_not_name_a_version_are_rejected(self):
        for tag in ("1.2.3", "v1.2", "v1.2.3.4", "v1.2.3-", "V1.2.3", "v", ""):
            with self.subTest(tag=tag):
                with self.assertRaises(ValueError):
                    check_release_version.version_from_tag(tag)

    def test_main_reports_the_failure_and_exits_nonzero(self):
        write_manifests(self.root, {name: "1.2.3" for name in check_release_version.MANIFESTS})

        self.assertEqual(1, check_release_version.main(["v9.9.9", "--root", str(self.root)]))


if __name__ == "__main__":
    unittest.main()

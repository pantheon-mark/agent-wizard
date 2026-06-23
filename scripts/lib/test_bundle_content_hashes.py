"""Tests for the bundle content-hash helpers (upgrade-integrity primitives).

`compute_bundle_tree_sha256` + `compute_bundle_manifest_sha256` produce the EXPECTED hashes
that a registry entry declares and that `self-update` re-computes over the operator's fetched
bundle to verify it matches what the operator approved. Reproducibility across the build repo
and the operator's public clone rests on (a) the subtree publish copying bundle dirs verbatim
(GATE-0, verified byte-identical) and (b) canonicalized hashing (git autocrlf on a Windows
checkout normalizes away). The integrity hash REJECTS symlinks (F-H) — a bundle is regular
files only; a symlink in the tree is a tamper/structure signal, not silently followed.
"""

import os
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from upgrade import (  # noqa: E402
    compute_bundle_tree_sha256,
    compute_bundle_manifest_sha256,
    hash_subtree,
    sha256_file,
    BundleHashError,
)


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class BundleTreeHashTest(unittest.TestCase):
    def test_tree_hash_is_prefixed_subtree_digest(self):
        """The tree hash is the canonical `sha256:` + hash_subtree digest over the full dir,
        so it reuses the project's single tested tree-digest primitive."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write(d / "a.md", "alpha\n")
            _write(d / "sub" / "b.json", '{"k": 1}\n')
            _write(d / "migration-manifest.json", '{"v": "x"}\n')
            self.assertEqual(compute_bundle_tree_sha256(d), "sha256:" + hash_subtree(d))

    def test_tree_hash_changes_when_any_file_changes(self):
        """The integrity property: mutating any bundle byte changes the tree hash (so a
        tampered/corrupted fetched bundle fails verification against the approved value)."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write(d / "a.md", "alpha\n")
            _write(d / "migration-manifest.json", '{"v": "x"}\n')
            before = compute_bundle_tree_sha256(d)
            _write(d / "a.md", "alpha CHANGED\n")
            self.assertNotEqual(before, compute_bundle_tree_sha256(d))

    def test_tree_hash_rejects_symlinks(self):
        """F-H: an integrity hash must not silently follow symlinks. A bundle is regular
        files only; a symlink is a fail-closed signal."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write(d / "real.md", "x\n")
            _write(d / "migration-manifest.json", "{}\n")
            try:
                os.symlink(str(d / "real.md"), str(d / "link.md"))
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unsupported on this platform")
            with self.assertRaises(BundleHashError):
                compute_bundle_tree_sha256(d)


class BundleManifestHashTest(unittest.TestCase):
    def test_manifest_hash_is_prefixed_file_digest(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            _write(d / "migration-manifest.json", '{"target": "v9.9.9"}\n')
            self.assertEqual(
                compute_bundle_manifest_sha256(d),
                "sha256:" + sha256_file(d / "migration-manifest.json"),
            )

    def test_manifest_hash_missing_manifest_raises(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(BundleHashError):
                compute_bundle_manifest_sha256(Path(td))


if __name__ == "__main__":
    unittest.main()

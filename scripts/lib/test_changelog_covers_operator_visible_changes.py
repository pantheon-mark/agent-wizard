"""Every operator-visible change declared for a release must actually appear in
that release's `CHANGES.md` entry.

Why this exists: a "changelog is non-empty" check cannot catch under-disclosure
-- a changelog can be non-empty and still leave out the one change that matters
most to someone deciding whether to install it. What CAN be checked mechanically
is narrower and more honest: does the published text cover every item a human
already declared as operator-visible for that release? A human still has to
declare completely; this only closes the gap between what was declared and what
shipped.

The declared list lives OUTSIDE this toolkit (one JSON file per release, kept in
the private project this toolkit is built from), never inside it: this file is
published, and the declared list is build-side bookkeeping, not something an
operator needs. When that directory is not present -- true for anyone running a
public clone of this toolkit -- there is nothing to check against, so these
tests skip rather than fail. Where it IS present (a build checkout), each
declared item names a short, specific phrase; a declared item whose phrase does
not appear anywhere in its own release's `CHANGES.md` section fails the test
BY NAME, so a person reading the failure knows exactly which promised
disclosure is missing.

LIMIT, stated plainly: this check proves that each declared phrase is PRESENT
somewhere in its release's published text. It cannot tell whether the sentence
containing that phrase ASSERTS the change or DENIES it -- text that reuses a
declared phrase inside a sentence saying the change did NOT happen would still
satisfy this check. This is a presence check, not a meaning check, and it does
not replace a person actually reading the entry for sense before publication.

Run: python3 -m unittest discover -s wizard/scripts/lib \
        -p test_changelog_covers_operator_visible_changes.py
"""
import json
import re
import unittest
from pathlib import Path

# wizard/scripts/lib/ -> parents[2] == the toolkit root (wizard/ in a build
# checkout; the repository root itself in a public clone, where the wizard/
# prefix has been stripped by the subtree publish).
_TOOLKIT_ROOT = Path(__file__).resolve().parents[2]
_CHANGES = _TOOLKIT_ROOT / "CHANGES.md"

# One level above the toolkit root: in a build checkout this is the private
# project root; in a public clone it is whatever ordinary directory happens to
# contain the clone. Declared-changes data lives here, never inside the
# toolkit root itself.
_DECLARATIONS_DIR = _TOOLKIT_ROOT.parent / "governance" / "release_notes"

# Minimum word count for a declared `changelog_phrase`. Guards against
# "keyword theater": a one- or two-word phrase (e.g. a bare "capability" or
# "upgrade") would be satisfied by almost any release note by accident and
# would not actually prove the declared change was disclosed.
_MIN_PHRASE_WORDS = 4

_ANY_HEADING_RE = re.compile(r"^##[ \t].*$", re.MULTILINE)
_VERSION_SUFFIX_RE = re.compile(r"\(v(\d+\.\d+\.\d+)\)\s*$")
_VERSION_RE = re.compile(r"^v\d+\.\d+\.\d+$")


def _normalize(text):
    """Case-fold, drop markdown emphasis markers, and collapse whitespace so a
    declared phrase matches regardless of incidental `**bold**` placement or
    line-wrapping in the published prose."""
    text = text.replace("**", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip().casefold()


def _changes_sections_by_version(changes_text):
    """`{"vX.Y.Z": section_text}` for every dated section in CHANGES.md whose
    heading ends in `(vX.Y.Z)`. A section runs from just after its own heading
    to just before the NEXT heading of any kind (versioned or not) -- an
    interstitial non-versioned entry (e.g. a "toolkit fix, no version change"
    note) must never be silently absorbed into the version before it, which
    would let that version's coverage check pass on someone else's text."""
    headings = list(_ANY_HEADING_RE.finditer(changes_text))
    sections = {}
    for i, heading in enumerate(headings):
        version_match = _VERSION_SUFFIX_RE.search(heading.group(0).rstrip())
        if not version_match:
            continue
        version = f"v{version_match.group(1)}"
        start = heading.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(changes_text)
        sections.setdefault(version, []).append(changes_text[start:end])
    return {version: "\n".join(parts) for version, parts in sections.items()}


def _load_declaration_files():
    return sorted(_DECLARATIONS_DIR.glob("*.json")) if _DECLARATIONS_DIR.is_dir() else []


class ChangelogCoversOperatorVisibleChangesTests(unittest.TestCase):

    def setUp(self):
        self.declaration_files = _load_declaration_files()
        if not self.declaration_files:
            self.skipTest(
                f"no declared-changes directory at {_DECLARATIONS_DIR} -- this check only "
                "runs where that data is present (a build checkout), not in a public clone "
                "of this toolkit"
            )
        self.assertTrue(_CHANGES.is_file(), f"CHANGES.md not found at {_CHANGES}")
        self.sections_by_version = _changes_sections_by_version(
            _CHANGES.read_text(encoding="utf-8"))

    def _load(self, path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            self.fail(f"{path}: invalid JSON ({exc})")
        self.assertIsInstance(data, dict, f"{path}: top level must be an object")
        return data

    def test_declaration_files_are_well_formed(self):
        """Malformed declared data must fail loudly here, not be silently
        skipped by the coverage test below."""
        for path in self.declaration_files:
            with self.subTest(file=path.name):
                data = self._load(path)
                version = data.get("version")
                self.assertTrue(
                    isinstance(version, str) and _VERSION_RE.match(version),
                    f"{path.name}: 'version' must look like 'vX.Y.Z', got {version!r}")
                items = data.get("items")
                self.assertTrue(
                    isinstance(items, list) and items,
                    f"{path.name}: 'items' must be a non-empty list")
                seen_ids = set()
                for item in items:
                    self.assertIsInstance(item, dict, f"{path.name}: each item must be an object")
                    item_id = item.get("id")
                    self.assertTrue(
                        isinstance(item_id, str) and item_id.strip(),
                        f"{path.name}: an item is missing a non-empty 'id'")
                    self.assertNotIn(
                        item_id, seen_ids, f"{path.name}: duplicate declared id {item_id!r}")
                    seen_ids.add(item_id)
                    phrase = item.get("changelog_phrase")
                    self.assertTrue(
                        isinstance(phrase, str) and phrase.strip(),
                        f"{path.name}/{item_id}: missing a non-empty 'changelog_phrase'")
                    word_count = len(phrase.split())
                    self.assertGreaterEqual(
                        word_count, _MIN_PHRASE_WORDS,
                        f"{path.name}/{item_id}: changelog_phrase {phrase!r} is only "
                        f"{word_count} word(s) -- too generic to prove real coverage "
                        f"(minimum {_MIN_PHRASE_WORDS}); declare a longer, more specific "
                        "phrase actually drawn from the intended release-note wording")

    def test_every_declared_item_is_covered_in_its_release_changelog(self):
        """The substantive gate: every item a human declared as operator-visible
        for a release must actually be represented in that release's published
        `CHANGES.md` text. Fails by NAMING the uncovered item(s), never just
        'changelog looks wrong'. Presence only -- see the module docstring's
        LIMIT paragraph for what this does not establish."""
        for path in self.declaration_files:
            data = self._load(path)
            version = data["version"]
            with self.subTest(version=version):
                section = self.sections_by_version.get(version)
                self.assertIsNotNone(
                    section,
                    f"{version}: declared changes exist at {path.name} but CHANGES.md has "
                    f"no dated section heading ending in ({version})")
                normalized_section = _normalize(section)
                missing = [
                    item["id"] for item in data["items"]
                    if _normalize(item["changelog_phrase"]) not in normalized_section
                ]
                self.assertEqual(
                    missing, [],
                    f"{version}: the following declared operator-visible change(s) have no "
                    f"matching text in this release's CHANGES.md entry -- the published "
                    f"changelog under-discloses what shipped: {missing}")


if __name__ == "__main__":
    unittest.main()

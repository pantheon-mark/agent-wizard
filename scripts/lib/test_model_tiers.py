"""Tests for the maintained tier->model resolution source.

The wizard must resolve the High/Standard/Fast tiers to REAL current Claude model
IDs (CLAUDE.md programmatic-model rule) so an emitted operator system's
start-session.sh carries a real --model, not a placeholder. The scaffold-plan keeps
shape-correct placeholders; this maintained registry supplies the real
generation-time resolution through the assembler's model_tiers override seam.
Budget-conditioned tiering (FIN-1) is intentionally OUT of v0 scope (one fixed
family map; values flag default OFF). RED->GREEN.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from model_tiers import load_model_tiers, ModelTiersError  # noqa: E402

SHAPE = "markdown-CC"
_PLACEHOLDER_PREFIX = "model-"  # the scaffold-plan's shape-correct, non-real placeholder family


class LoaderTests(unittest.TestCase):
    def test_resolves_real_models_for_all_three_tiers(self):
        mt = load_model_tiers(SHAPE)
        for tier in ("high", "standard", "fast"):
            self.assertIn(tier, mt, f"missing tier {tier}")
            v = mt[tier]
            self.assertTrue(v, f"{tier} tier is empty")
            self.assertFalse(v.startswith(_PLACEHOLDER_PREFIX),
                             f"{tier} resolves to a placeholder {v!r}, not a real model")
            self.assertTrue(v.startswith("claude-"), f"{tier}={v!r} is not a Claude model id")

    def test_exactly_the_three_tiers(self):
        self.assertEqual(set(load_model_tiers(SHAPE).keys()), {"high", "standard", "fast"})

    def test_high_tier_selects_1m_context_variant(self):
        """F-05: the high tier must select the 1M-context model variant. On the Claude Code
        CLI the 1M window is chosen by the [1m] model-id suffix (the only scriptable selector;
        bare claude-opus-4-8 defaults to the 200K window). standard/fast stay non-1M
        (F-05 scope = high only: Sonnet 1M costs subscription credits; Haiku has no 1M variant)."""
        mt = load_model_tiers(SHAPE)
        self.assertTrue(mt["high"].endswith("[1m]"),
                        f"high tier {mt['high']!r} must select the 1M variant via the [1m] suffix")
        self.assertFalse(mt["standard"].endswith("[1m]"),
                         f"standard-tier 1M is out of F-05 scope; got {mt['standard']!r}")
        self.assertFalse(mt["fast"].endswith("[1m]"),
                         f"fast tier has no 1M variant; got {mt['fast']!r}")

    def test_unknown_shape_fails_closed(self):
        with self.assertRaises(ModelTiersError):
            load_model_tiers("no-such-shape")

    def test_bad_contract_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / f"{SHAPE}.json"
            p.write_text('{"contract_id": "wrong", "system_shape": "markdown-CC", "model_tiers": {}}',
                         encoding="utf-8")
            with self.assertRaises(ModelTiersError):
                load_model_tiers(SHAPE, registry_dir=Path(td))


if __name__ == "__main__":
    unittest.main()

"""Tests for the inherited-corpus loader (stdlib unittest; pip-install-free).

Covers: the REAL distributed pack loads + validates (C1-C7); each load-bearing invariant
fails closed; resolution by shape; and — the load-bearing integration proof — the projected
plan corpus_cells validate clean under the emission-plan loader's I1-I10 (so the downstream
emitter reads a fully-validated plan).
"""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from corpus_loader import (  # noqa: E402
    CorpusError,
    CorpusCellRecord,
    load_corpus_contract,
    default_corpus_contract_path,
    default_corpus_pack_path,
    load_corpus_pack,
    validate_corpus_pack,
    resolve_for_shape,
    to_plan_corpus_cells,
)
from emission_plan import (  # noqa: E402
    load_contract as load_plan_contract,
    default_contract_path as default_plan_contract_path,
    validate_emission_plan,
)
from test_emission_plan import _valid_plan  # noqa: E402

import json


def _real_pack_dict():
    return json.loads(default_corpus_pack_path().read_text(encoding="utf-8"))


class CorpusLoaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_corpus_contract(default_corpus_contract_path())

    def _expect_fail(self, pack, invariant):
        with self.assertRaises(CorpusError) as ctx:
            validate_corpus_pack(pack, self.contract)
        self.assertIn(invariant, str(ctx.exception))

    # --- real pack ---------------------------------------------------------

    def test_real_pack_loads(self):
        records = load_corpus_pack()
        self.assertEqual(len(records), 35)
        self.assertTrue(all(isinstance(r, CorpusCellRecord) for r in records))

    def test_realization_breakdown(self):
        records = load_corpus_pack()
        body = [r for r in records if r.realization == "corpus-body"]
        scaf = [r for r in records if r.realization == "scaffold-template"]
        deleg = [r for r in records if r.realization == "delegated"]
        self.assertEqual((len(body), len(scaf), len(deleg)), (20, 11, 4))

    def test_hard_control_cell_present(self):
        # consult-before-modify must be hard-control, now operator-profile-derived basis.
        records = load_corpus_pack()
        gated = [r for r in records if r.authority_source_default == "hard-control"]
        self.assertEqual(len(gated), 1)
        self.assertEqual(gated[0].authority_gate, "high-autonomy-enforced-control")
        self.assertEqual(gated[0].authority_basis_default, "operator-profile-derived")

    def test_resolve_markdown_cc(self):
        records = load_corpus_pack()
        resolved = resolve_for_shape(records, "markdown-CC")
        self.assertEqual(len(resolved), 35)  # all are markdown-CC or all-shapes

    # --- the integration proof: projection is I1-I10 clean -----------------

    def test_projection_validates_under_emission_plan(self):
        records = load_corpus_pack()
        projected = to_plan_corpus_cells(resolve_for_shape(records, "markdown-CC"))
        self.assertEqual(len(projected), 20)  # only corpus-body cells project
        plan = copy.deepcopy(_valid_plan())
        plan["corpus_cells"] = projected
        plan["template_variants"] = []  # projection is all inline_payload
        plan_contract = load_plan_contract(default_plan_contract_path())
        ep = validate_emission_plan(plan, plan_contract)  # raises if any I1-I10 fails
        self.assertEqual(len(ep.corpus_cells), 20)
        # the hard-control cell survived the projection with correct I3 coupling
        hc = [c for c in ep.corpus_cells if c.authority_source == "hard-control"]
        self.assertEqual(len(hc), 1)
        self.assertEqual(hc[0].authority_basis, "operator-profile-derived")

    # --- fail-closed invariants -------------------------------------------

    def test_C2_unknown_enum_fails(self):
        p = _real_pack_dict()
        p["cells"][0]["authority_gate"] = "totally-made-up"
        self._expect_fail(p, "C2")

    def test_C3_duplicate_cell_id_fails(self):
        p = _real_pack_dict()
        p["cells"].append(copy.deepcopy(p["cells"][0]))
        self._expect_fail(p, "C3")

    def test_C4_corpus_body_without_canonical_fails(self):
        p = _real_pack_dict()
        body = next(c for c in p["cells"] if c["realization"] == "corpus-body")
        body.pop("canonical")
        self._expect_fail(p, "C4")

    def test_C4_scaffold_with_canonical_fails(self):
        p = _real_pack_dict()
        scaf = next(c for c in p["cells"] if c["realization"] == "scaffold-template")
        scaf["canonical"] = {"category": "x", "home": "y", "body": "z"}
        self._expect_fail(p, "C4")

    def test_C5_applies_all_with_provisional_basis_fails(self):
        p = _real_pack_dict()
        c = next(c for c in p["cells"] if c["authority_gate"] == "applies-all")
        c["authority_basis_default"] = "provisional_default"
        self._expect_fail(p, "C5")

    def test_C5_gated_with_not_applicable_source_fails(self):
        p = _real_pack_dict()
        c = next(c for c in p["cells"] if c["authority_gate"] != "applies-all")
        c["authority_source_default"] = "not_applicable"
        self._expect_fail(p, "C5")

    def test_C6_bad_hook_type_fails(self):
        p = _real_pack_dict()
        c = next(c for c in p["cells"] if c.get("target_hooks"))
        c["target_hooks"][0]["hook_type"] = "nope"
        self._expect_fail(p, "C6")

    def test_C1_wrong_contract_version_fails(self):
        p = _real_pack_dict()
        p["contract_version"] = "inherited-corpus-v999"
        self._expect_fail(p, "C1")


if __name__ == "__main__":
    unittest.main()

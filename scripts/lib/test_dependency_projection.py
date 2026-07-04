"""Tests for the deterministic external-dependency projection (pure-code role-filter+reshape).

The canonical record is two fields the operator confirms once:
  IDENTITY   (decision/integration_boundary): [{id, name, type, roles[], credential_facet?}]
  ANNOTATION (content-only):                  [{id, purpose, what_stops, boundary_input_facet?, health_facet?}]
Three tabular surfaces are deterministic role-filtered views of that record. These tests pin:
filter-by-role, column reshape, hardcoded Pending + runtime placeholders (no synthesized health),
the zero-dependency vs per-role-empty vs zero-role-INVALID cases, and byte-determinism (the
property the change-propagation engine relies on to auto-halt an unchanged role-subset).
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dependency_projection as dp  # type: ignore  # noqa: E402


# A two-dependency canonical record exercising all three roles + a partial-role dependency.
_IDENTITY = json.dumps([
    {"id": "google_sheet", "name": "Google Sheet task tracker", "type": "Spreadsheet",
     "roles": ["boundary_input", "health_monitored", "needs_credential"],
     "credential_facet": {"env_var": "GOOGLE_SHEETS_API_KEY", "cred_type": "API key",
                          "provider": "Google", "provisional_expiry": "Unknown"}},
    {"id": "smtp_out", "name": "Outbound mail server", "type": "SMTP",
     "roles": ["health_monitored", "needs_credential"],
     "credential_facet": {"env_var": "SMTP_PASSWORD", "cred_type": "Password",
                          "provider": "Fastmail", "provisional_expiry": "Unknown"}},
])
_ANNOTATION = json.dumps([
    {"id": "google_sheet", "purpose": "central task list", "what_stops": "agents lose the queue",
     "boundary_input_facet": {"input_risk": "malformed rows mis-route work"},
     "health_facet": {}},
    {"id": "smtp_out", "purpose": "sends digests", "what_stops": "no notifications go out",
     "health_facet": {}},
])


class ParseTest(unittest.TestCase):
    def test_zero_role_record_is_invalid(self):
        """A dependency with an empty roles list is INVALID (every dependency plays >=1 role)."""
        bad = json.dumps([{"id": "x", "name": "X", "type": "Unknown", "roles": []}])
        with self.assertRaises(dp.DependencyProjectionError):
            dp.parse_identity(bad)

    def test_unknown_role_is_invalid(self):
        bad = json.dumps([{"id": "x", "name": "X", "type": "Unknown", "roles": ["telepathy"]}])
        with self.assertRaises(dp.DependencyProjectionError):
            dp.parse_identity(bad)

    def test_missing_id_is_invalid(self):
        bad = json.dumps([{"name": "X", "type": "Unknown", "roles": ["boundary_input"]}])
        with self.assertRaises(dp.DependencyProjectionError):
            dp.parse_identity(bad)


class FilterTest(unittest.TestCase):
    def test_input_type_inventory_filters_boundary_input(self):
        body = dp.project("INPUT_TYPE_INVENTORY", _IDENTITY, _ANNOTATION)
        self.assertIn("Google Sheet task tracker", body)   # boundary_input
        self.assertNotIn("Outbound mail server", body)     # not boundary_input

    def test_source_registry_filters_health_monitored(self):
        body = dp.project("SOURCE_REGISTRY_ROWS", _IDENTITY, _ANNOTATION)
        self.assertIn("Google Sheet task tracker", body)   # health_monitored
        self.assertIn("Outbound mail server", body)        # health_monitored too

    def test_credentials_registry_filters_needs_credential(self):
        body = dp.project("CREDENTIAL_REGISTRY_ROWS", _IDENTITY, _ANNOTATION)
        self.assertIn("GOOGLE_SHEETS_API_KEY", body)
        self.assertIn("SMTP_PASSWORD", body)


class ReshapeTest(unittest.TestCase):
    def test_source_registry_hardcodes_pending_and_runtime_placeholders(self):
        """Fabrication discipline: never synthesize observed health. Status=Pending,
        Expected behavior / Last verified are runtime placeholders, Health flag=Pending."""
        body = dp.project("SOURCE_REGISTRY_ROWS", _IDENTITY, _ANNOTATION)
        row = [ln for ln in body.splitlines() if "Google Sheet task tracker" in ln][0]
        self.assertIn(dp.RUNTIME_PLACEHOLDER, row)   # expected-behavior / last-verified
        self.assertIn("Pending", row)                # status + health flag
        # the value is copied straight from the canonical record, never invented:
        self.assertIn("central task list", row)      # purpose carried through
        self.assertIn("agents lose the queue", row)  # what_stops carried through

    def test_credentials_registry_carries_credential_facet_not_values(self):
        body = dp.project("CREDENTIAL_REGISTRY_ROWS", _IDENTITY, _ANNOTATION)
        row = [ln for ln in body.splitlines() if "GOOGLE_SHEETS_API_KEY" in ln][0]
        self.assertIn("API key", row)
        self.assertIn("Google", row)
        self.assertIn("Pending", row)   # never Active at setup

    def test_input_type_inventory_uses_boundary_facet(self):
        body = dp.project("INPUT_TYPE_INVENTORY", _IDENTITY, _ANNOTATION)
        self.assertIn("malformed rows mis-route work", body)  # boundary_input_facet.input_risk


class EmptyCaseTest(unittest.TestCase):
    def test_zero_dependencies_gives_empty_body(self):
        for field in ("INPUT_TYPE_INVENTORY", "SOURCE_REGISTRY_ROWS", "CREDENTIAL_REGISTRY_ROWS"):
            self.assertEqual(dp.project(field, "[]", "[]"), "")

    def test_per_role_empty_is_valid(self):
        """Dependencies exist but none plays boundary_input -> empty INPUT_TYPE_INVENTORY while
        the other surfaces are non-empty."""
        ident = json.dumps([{"id": "smtp", "name": "Mail", "type": "SMTP",
                             "roles": ["health_monitored", "needs_credential"],
                             "credential_facet": {"env_var": "SMTP_PW", "cred_type": "Password",
                                                  "provider": "x", "provisional_expiry": "Unknown"}}])
        ann = json.dumps([{"id": "smtp", "purpose": "p", "what_stops": "w"}])
        self.assertEqual(dp.project("INPUT_TYPE_INVENTORY", ident, ann), "")
        self.assertNotEqual(dp.project("SOURCE_REGISTRY_ROWS", ident, ann), "")


class DeterminismTest(unittest.TestCase):
    def test_byte_identical_across_runs(self):
        """The property the engine relies on to auto-halt: same canonical record -> same view."""
        a = dp.project("SOURCE_REGISTRY_ROWS", _IDENTITY, _ANNOTATION)
        b = dp.project("SOURCE_REGISTRY_ROWS", _IDENTITY, _ANNOTATION)
        self.assertEqual(a, b)

    def test_unrelated_change_does_not_change_other_role_view(self):
        """Editing a health-only narrative leaves the boundary_input view byte-identical
        (this is what lets the boundary_input projection auto-halt)."""
        before = dp.project("INPUT_TYPE_INVENTORY", _IDENTITY, _ANNOTATION)
        ann2 = json.loads(_ANNOTATION)
        ann2[1]["purpose"] = "sends digests AND alerts"  # smtp is not boundary_input
        after = dp.project("INPUT_TYPE_INVENTORY", _IDENTITY, json.dumps(ann2))
        self.assertEqual(before, after)


class BoundaryOutputRoleTest(unittest.TestCase):
    """`boundary_output` is a canonical relationship that drives NO projection at v0: an output-only
    dependency (e.g. a push channel the operator is happy to assume works) stays in the record and is
    excluded from all three role-filtered tables. Regression: declining health-monitoring on a
    notification channel must narrow its role set, not drop the dependency from the record."""

    _OUTPUT_ONLY = json.dumps([
        {"id": "ntfy", "name": "NTFY push channel", "type": "Notification service",
         "roles": ["boundary_output"]},
    ])

    def test_boundary_output_is_a_valid_role(self):
        self.assertIn("boundary_output", dp.VALID_ROLES)

    def test_output_only_dependency_is_valid(self):
        rows = dp.parse_identity(self._OUTPUT_ONLY)
        self.assertEqual([r["id"] for r in rows], ["ntfy"])

    def test_output_only_excluded_from_all_three_projections(self):
        for field in ("INPUT_TYPE_INVENTORY", "SOURCE_REGISTRY_ROWS", "CREDENTIAL_REGISTRY_ROWS"):
            self.assertEqual(dp.project(field, self._OUTPUT_ONLY, "[]"), "")

    def test_output_plus_other_roles_still_projects_for_those(self):
        ident = json.dumps([
            {"id": "outlook", "name": "Outlook email", "type": "M365",
             "roles": ["boundary_output", "health_monitored", "needs_credential"],
             "credential_facet": {"env_var": "OUTLOOK", "cred_type": "OAuth",
                                  "provider": "Microsoft", "provisional_expiry": "Unknown"}},
        ])
        ann = json.dumps([{"id": "outlook", "purpose": "sends mail", "what_stops": "no mail"}])
        self.assertNotEqual(dp.project("SOURCE_REGISTRY_ROWS", ident, ann), "")
        self.assertNotEqual(dp.project("CREDENTIAL_REGISTRY_ROWS", ident, ann), "")
        self.assertEqual(dp.project("INPUT_TYPE_INVENTORY", ident, ann), "")  # outbound is not an input

    def test_role_projection_map_consistent_with_surfaces(self):
        """Guard against the 'unprojected role becomes ad-hoc' drift the consult flagged: the
        role->projection map and the surface table must agree, and boundary_output maps to None."""
        projecting_roles = {role for role, _cols in dp._SURFACES.values()}
        for role, proj in dp.ROLE_PROJECTION.items():
            self.assertIn(role, dp.VALID_ROLES)
            if proj is None:
                self.assertNotIn(role, projecting_roles)
            else:
                self.assertIn(proj, dp._SURFACES)
        for field, (role, _cols) in dp._SURFACES.items():
            self.assertEqual(dp.ROLE_PROJECTION[role], field)
        self.assertIsNone(dp.ROLE_PROJECTION["boundary_output"])


# --- B1-1: typed capability descriptor fields --------------------------------------------------
# Per-dependency OPTIONAL fields (design §5.2 domain-neutral action taxonomy; §4.5/§4.7/F-28/F-29
# risk-enforcement classes): action_class, risk_class, recovery_profile_ref, declared_test_target,
# blast_radius_cap. All default-safe when absent (backward compat with every pre-B1-1 record).

def _dep(id_="d1", **extra):
    row = {"id": id_, "name": "Dep", "type": "Unknown", "roles": ["boundary_output"]}
    row.update(extra)
    return row


class DescriptorFieldVocabularyTest(unittest.TestCase):
    """Pin the exact vocabulary strings — B1-3's OperationContract reuses these verbatim."""

    def test_action_classes_are_the_domain_neutral_taxonomy(self):
        self.assertEqual(dp.ACTION_CLASSES, frozenset({
            "classify", "transform", "route", "notify", "mutate", "delete", "send_execute",
            "synchronize", "retain_archive", "recover", "audit", "read_only",
        }))

    def test_risk_classes_include_read_only_local_as_the_named_safe_class(self):
        self.assertEqual(dp.RISK_CLASSES, frozenset({
            "read_only_local", "reversible_external", "irreversible_external",
            "sensitive_data", "standing_automation",
        }))
        self.assertEqual(dp.READ_ONLY_LOCAL, "read_only_local")
        self.assertIn(dp.READ_ONLY_LOCAL, dp.RISK_CLASSES)

    def test_test_targets_are_the_declared_set(self):
        self.assertEqual(dp.TEST_TARGETS, frozenset({
            "copy", "bounded_sample", "dry_run", "native_undo",
        }))

    def test_fail_safe_risk_class_is_not_read_only_local(self):
        """The class the resolver falls back to must itself never be the safe class."""
        self.assertNotEqual(dp.FAIL_SAFE_RISK_CLASS, dp.READ_ONLY_LOCAL)
        self.assertIn(dp.FAIL_SAFE_RISK_CLASS, dp.RISK_CLASSES)


class DescriptorFieldValidationTest(unittest.TestCase):
    def test_record_with_none_of_the_new_fields_still_validates(self):
        """Backward compat: a pre-B1-1 record (no descriptor fields at all) is still valid."""
        rows = dp.parse_identity(json.dumps([_dep()]))
        self.assertEqual(len(rows), 1)

    def test_well_formed_action_class_accepted(self):
        rows = dp.parse_identity(json.dumps([_dep(action_class="mutate")]))
        self.assertEqual(rows[0]["action_class"], "mutate")

    def test_malformed_action_class_rejected(self):
        with self.assertRaises(dp.DependencyProjectionError):
            dp.parse_identity(json.dumps([_dep(action_class="teleport")]))

    def test_well_formed_risk_class_accepted(self):
        rows = dp.parse_identity(json.dumps([_dep(risk_class="irreversible_external")]))
        self.assertEqual(rows[0]["risk_class"], "irreversible_external")

    def test_malformed_risk_class_rejected(self):
        with self.assertRaises(dp.DependencyProjectionError):
            dp.parse_identity(json.dumps([_dep(risk_class="mostly_fine")]))

    def test_well_formed_recovery_profile_ref_accepted(self):
        rows = dp.parse_identity(json.dumps([_dep(recovery_profile_ref="mailbox_native_undo")]))
        self.assertEqual(rows[0]["recovery_profile_ref"], "mailbox_native_undo")

    def test_empty_recovery_profile_ref_rejected(self):
        with self.assertRaises(dp.DependencyProjectionError):
            dp.parse_identity(json.dumps([_dep(recovery_profile_ref="")]))

    def test_well_formed_declared_test_target_accepted(self):
        rows = dp.parse_identity(json.dumps([_dep(declared_test_target="bounded_sample")]))
        self.assertEqual(rows[0]["declared_test_target"], "bounded_sample")

    def test_malformed_declared_test_target_rejected(self):
        with self.assertRaises(dp.DependencyProjectionError):
            dp.parse_identity(json.dumps([_dep(declared_test_target="live")]))

    def test_positive_blast_radius_cap_accepted(self):
        rows = dp.parse_identity(json.dumps([_dep(blast_radius_cap=10)]))
        self.assertEqual(rows[0]["blast_radius_cap"], 10)

    def test_null_blast_radius_cap_accepted(self):
        """An explicit JSON null means 'no cap set yet' — distinct from a bad value."""
        rows = dp.parse_identity(json.dumps([_dep(blast_radius_cap=None)]))
        self.assertIsNone(rows[0]["blast_radius_cap"])

    def test_zero_blast_radius_cap_rejected(self):
        with self.assertRaises(dp.DependencyProjectionError):
            dp.parse_identity(json.dumps([_dep(blast_radius_cap=0)]))

    def test_negative_blast_radius_cap_rejected(self):
        with self.assertRaises(dp.DependencyProjectionError):
            dp.parse_identity(json.dumps([_dep(blast_radius_cap=-1)]))

    def test_non_integer_blast_radius_cap_rejected(self):
        with self.assertRaises(dp.DependencyProjectionError):
            dp.parse_identity(json.dumps([_dep(blast_radius_cap="10")]))

    def test_boolean_blast_radius_cap_rejected(self):
        """bool is a subclass of int in Python — must not sneak past as a valid cap."""
        with self.assertRaises(dp.DependencyProjectionError):
            dp.parse_identity(json.dumps([_dep(blast_radius_cap=True)]))

    def test_all_five_descriptor_fields_together_accepted(self):
        rows = dp.parse_identity(json.dumps([_dep(
            action_class="send_execute", risk_class="irreversible_external",
            recovery_profile_ref="mailbox_native_undo", declared_test_target="dry_run",
            blast_radius_cap=5,
        )]))
        row = rows[0]
        self.assertEqual(row["action_class"], "send_execute")
        self.assertEqual(row["risk_class"], "irreversible_external")
        self.assertEqual(row["recovery_profile_ref"], "mailbox_native_undo")
        self.assertEqual(row["declared_test_target"], "dry_run")
        self.assertEqual(row["blast_radius_cap"], 5)


class DescriptorFieldSurvivesRoundTripTest(unittest.TestCase):
    """'Fields survive role re-propagation' (interview steps 10/11/12 re-derive the whole
    canonical record): parse_identity must pass every descriptor field straight through
    unchanged, not project/strip to a fixed key set — the same guarantee that lets a
    re-derivation preserve descriptor fields the operator already set."""

    def test_parse_identity_preserves_all_descriptor_fields_on_the_returned_row(self):
        original = _dep(
            action_class="notify", risk_class="reversible_external",
            recovery_profile_ref="ntfy_channel", declared_test_target="copy",
            blast_radius_cap=3,
        )
        rows = dp.parse_identity(json.dumps([original]))
        self.assertEqual(rows[0], original)


class FailSafeRiskResolverTest(unittest.TestCase):
    """F-28, the load-bearing safety property: an absent or unrecognized risk_class on a
    dependency must resolve to the MOST-protected class, never silently to read_only_local."""

    def test_unknown_risk_class_resolves_to_protected(self):
        dep = _dep(risk_class="totally_made_up")
        self.assertEqual(dp.resolve_risk_class(dep), dp.FAIL_SAFE_RISK_CLASS)

    def test_absent_risk_class_on_a_writer_resolves_to_protected(self):
        dep = _dep(action_class="delete")  # a writer; no risk_class set at all
        self.assertEqual(dp.resolve_risk_class(dep), dp.FAIL_SAFE_RISK_CLASS)

    def test_explicit_read_only_local_resolves_to_read_only_local(self):
        dep = _dep(action_class="read_only", risk_class=dp.READ_ONLY_LOCAL)
        self.assertEqual(dp.resolve_risk_class(dep), dp.READ_ONLY_LOCAL)

    def test_unknown_never_resolves_to_read_only_local_regression_pin(self):
        """Pins F-28: this is the exact regression a future 'simplify the resolver' edit could
        introduce (falling back to the safe class instead of the protected one). If a future
        edit makes resolve_risk_class default unknown/absent to READ_ONLY_LOCAL, this fails."""
        for dep in (_dep(risk_class="nonsense"), _dep(), _dep(risk_class=None), _dep(risk_class=123)):
            resolved = dp.resolve_risk_class(dep)
            self.assertNotEqual(
                resolved, dp.READ_ONLY_LOCAL,
                f"resolve_risk_class must never silently downgrade {dep!r} to read_only_local")
            self.assertEqual(resolved, dp.FAIL_SAFE_RISK_CLASS)


if __name__ == "__main__":
    unittest.main()

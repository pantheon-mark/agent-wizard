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


if __name__ == "__main__":
    unittest.main()

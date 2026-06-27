import sys
import unittest
from pathlib import Path

_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write.operations import Operation  # noqa: E402
from external_write.boundary import check_declared_write_set, BoundaryResult  # noqa: E402


def _op(field="Status", op_kind="set_status"):
    return Operation(surface="google_sheets", object_id="s:1", field=field,
                     new_value="Complete", op_kind=op_kind, batch_id="b")


class TestBoundary(unittest.TestCase):
    def test_declared_field_passes(self):
        r = check_declared_write_set(_op(field="Status", op_kind="set_status"))
        self.assertIsInstance(r, BoundaryResult)
        self.assertTrue(r.ok, r.reason)

    def test_undeclared_field_fails(self):
        r = check_declared_write_set(_op(field="Owner", op_kind="set_status"))
        self.assertFalse(r.ok)
        self.assertIn("Owner", r.reason)

    def test_unknown_op_kind_fails(self):
        r = check_declared_write_set(_op(field="Status", op_kind="mystery"))
        self.assertFalse(r.ok)

    def test_due_date_op_declares_due_date(self):
        self.assertTrue(check_declared_write_set(
            _op(field="Due Date", op_kind="update_due_date")).ok)


if __name__ == "__main__":
    unittest.main()

"""Tests for the curated capability-facing import surface (Task R7-T1 —
external-write-gate-generalization slice; kernel ReadFacade registry
generalization).

`capability_api.py` is the ONLY `external_write` module (besides
`operations`) emitted capability code is meant to import — it must
re-export EXACTLY `run_enveloped_operation` + `build_read_facade` and expose
no credential-reachable symbol (no `get_adapter`, no registry, no Adapter
class, no credential provisioner).

v0.12.0 S1 (RunEnvelope trust core) — the sanctioned CAPABILITY live-write
entrypoint is now `run_enveloped_operation`, NOT the raw kernel primitive
`run_operation`. `run_operation` cannot enforce the run-level envelope checks
(spendability / consent binding / apply-by-id / aggregate ceiling), so it is
deliberately NOT re-exported here; capability code must go through the
envelope. This module must NOT expose `run_operation` at all.

Two groups:
  1. TestCapabilityApiSurface — the exact re-exported symbol set, and that
     each one is identity-equal to its kernel source (a curated re-export,
     not a reimplementation).
  2. TestCapabilityApiExposesNoCredentialReachableSymbol — none of the
     names this module WOULD have re-exported (get_adapter, the adapter
     registry, register_read_facade / the read-facade registry, any
     credential-provider symbol, AND the raw run_operation primitive) are
     actually present on it.
"""

import sys
import unittest
from pathlib import Path

# Single-home: import from wizard/agents/lib/external_write (the canonical location).
_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

import external_write.capability_api as capability_api  # noqa: E402
from external_write.run_envelope import (  # noqa: E402
    run_enveloped_operation as _kernel_run_enveloped_operation,
    run_sanctioned_bulk as _kernel_run_sanctioned_bulk,
)
from external_write.read_facade import (  # noqa: E402
    build_read_facade as _kernel_build_read_facade,
)


class TestCapabilityApiSurface(unittest.TestCase):

    def test_all_lists_exactly_the_curated_surface(self):
        self.assertEqual(
            sorted(capability_api.__all__),
            sorted(["run_enveloped_operation", "run_sanctioned_bulk", "build_read_facade"]))

    def test_run_enveloped_operation_is_the_real_kernel_entrypoint(self):
        self.assertIs(capability_api.run_enveloped_operation,
                      _kernel_run_enveloped_operation)

    def test_build_read_facade_is_the_real_kernel_build_read_facade(self):
        self.assertIs(capability_api.build_read_facade, _kernel_build_read_facade)

    def test_capability_api_exposes_run_sanctioned_bulk(self):
        # D6c: the sanctioned bulk-run helper is re-exported through the SAME
        # curated surface as run_enveloped_operation -- it is the same object
        # as run_envelope's, not a reimplementation, and scans clean (a
        # separate scan-clean assertion lives alongside the golden-emit
        # scaffold tests).
        self.assertIn("run_sanctioned_bulk", capability_api.__all__)
        self.assertIs(capability_api.run_sanctioned_bulk, _kernel_run_sanctioned_bulk)

    def test_module_exports_nothing_beyond_dunder_names_and_all(self):
        """A curated re-export surface, not a grab-bag: every non-dunder
        top-level name on the module must be exactly one of __all__'s
        entries."""
        public_names = sorted(
            n for n in dir(capability_api)
            if not n.startswith("_")
        )
        self.assertEqual(
            public_names,
            sorted(["build_read_facade", "run_enveloped_operation", "run_sanctioned_bulk"]))

    def test_raw_run_operation_is_NOT_exported(self):
        # The raw kernel primitive must not be reachable through this surface
        # (it cannot enforce the run-level envelope checks).
        self.assertFalse(hasattr(capability_api, "run_operation"),
                         "capability_api must not expose the raw run_operation "
                         "primitive -- capability code must go through "
                         "run_enveloped_operation")
        self.assertNotIn("run_operation", capability_api.__all__)


class TestCapabilityApiExposesNoCredentialReachableSymbol(unittest.TestCase):

    CREDENTIAL_REACHABLE_NAMES = (
        "run_operation",
        "get_adapter",
        "register_adapter",
        "unregister_adapter",
        "_REGISTRY",
        "register_read_facade",
        "get_read_facade_class",
        "unregister_read_facade",
        "_READ_FACADE_REGISTRY",
        "write_credential_provider",
        "build_write_client",
        "ReadFacade",
        "adapters_gmail",
        "read_facades_gmail",
    )

    def test_no_credential_or_registry_reachable_name_is_present(self):
        for name in self.CREDENTIAL_REACHABLE_NAMES:
            with self.subTest(name=name):
                self.assertFalse(
                    hasattr(capability_api, name),
                    f"capability_api must not expose {name!r} -- it is "
                    "either an adapter registry accessor, a mutable "
                    "adapter/registry object, or a credential-reachable "
                    "symbol"
                )


if __name__ == "__main__":
    unittest.main()

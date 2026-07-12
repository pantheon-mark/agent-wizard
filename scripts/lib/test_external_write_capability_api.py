"""Tests for the curated capability-facing import surface (Task R7-T1 —
external-write-gate-generalization slice; kernel ReadFacade registry
generalization).

`capability_api.py` is the ONLY `external_write` module (besides
`operations`) emitted capability code is meant to import — it must
re-export EXACTLY `run_operation` + `build_read_facade` and expose no
credential-reachable symbol (no `get_adapter`, no registry, no Adapter
class, no credential provisioner).

Two groups:
  1. TestCapabilityApiSurface — the exact re-exported symbol set, and that
     each one is identity-equal to its kernel source (a curated re-export,
     not a reimplementation).
  2. TestCapabilityApiExposesNoCredentialReachableSymbol — none of the
     names this module WOULD have re-exported (get_adapter, the adapter
     registry, register_read_facade / the read-facade registry, any
     credential-provider symbol) are actually present on it.
"""

import sys
import unittest
from pathlib import Path

# Single-home: import from wizard/agents/lib/external_write (the canonical location).
_AGENTS_LIB = Path(__file__).resolve().parents[3] / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

import external_write.capability_api as capability_api  # noqa: E402
from external_write.adapters import run_operation as _kernel_run_operation  # noqa: E402
from external_write.read_facade import (  # noqa: E402
    build_read_facade as _kernel_build_read_facade,
)


class TestCapabilityApiSurface(unittest.TestCase):

    def test_all_lists_exactly_run_operation_and_build_read_facade(self):
        self.assertEqual(sorted(capability_api.__all__),
                         sorted(["run_operation", "build_read_facade"]))

    def test_run_operation_is_the_real_kernel_run_operation(self):
        self.assertIs(capability_api.run_operation, _kernel_run_operation)

    def test_build_read_facade_is_the_real_kernel_build_read_facade(self):
        self.assertIs(capability_api.build_read_facade, _kernel_build_read_facade)

    def test_module_exports_nothing_beyond_dunder_names_and_all(self):
        """A curated re-export surface, not a grab-bag: every non-dunder
        top-level name on the module must be exactly one of __all__'s two
        entries."""
        public_names = sorted(
            n for n in dir(capability_api)
            if not n.startswith("_")
        )
        self.assertEqual(public_names, sorted(["build_read_facade", "run_operation"]))


class TestCapabilityApiExposesNoCredentialReachableSymbol(unittest.TestCase):

    CREDENTIAL_REACHABLE_NAMES = (
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

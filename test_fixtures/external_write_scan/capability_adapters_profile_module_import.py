"""Bypass fixture (Task R7-T4): a CAPABILITY-zone module that imports
directly from an ADAPTER-PROFILE module (`external_write.adapters_<vendor>`)
instead of going through the curated `capability_api` + `read_facades_<cap>`
split. Must be flagged `adapter_module_import` -- capability code has no
legitimate reason to import ANYTHING from a profile module, even a class
name that is not itself a banned registry symbol.
"""

from external_write.adapters_acme import AcmeSyncAdapter


def build(adapter_cls=AcmeSyncAdapter):
    return adapter_cls()

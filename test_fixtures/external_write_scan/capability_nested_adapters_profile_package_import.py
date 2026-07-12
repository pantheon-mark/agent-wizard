"""Bypass fixture (Task R11-T1, F2 -- cross-vendor-ratified gap): a NESTED
adapter-profile package -- `import external_write.adapters_acme.client` --
three dotted components, where the profile name (`adapters_acme`) is neither
the LAST component (the shape the old trailing-two-components match
required) nor a bare first component (F1) -- it is the component
IMMEDIATELY FOLLOWING `external_write`, one level deeper than the two-
component absolute form (`external_write.adapters_acme`) already caught by
R7-T4. Must be flagged `adapter_module_import`.
"""

import external_write.adapters_acme.client


def build():
    return external_write.adapters_acme.client.AcmeAdapter()

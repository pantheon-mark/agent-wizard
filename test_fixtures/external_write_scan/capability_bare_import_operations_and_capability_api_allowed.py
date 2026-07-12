"""Legal (Task R11-T1, F1 negative guard): ordinary bare imports of the
curated capability-facing surfaces -- `import operations` and `import
capability_api` -- with NO `external_write.` prefix. Neither module name is
`adapter_registry` nor starts with `adapters_`, so the new bare
first-dotted-component rule must not touch either. Must NOT be flagged.
"""

import operations
import capability_api


def use():
    return operations.__name__, capability_api.__name__

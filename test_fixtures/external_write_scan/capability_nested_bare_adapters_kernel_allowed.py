"""Legal (Task R11-T1, F2 negative guard): a hypothetical nested submodule
UNDER the bare kernel dispatch module -- `from external_write.adapters.utils
import helper` -- three dotted components, with "adapters" (not
"adapters_...") sitting immediately after `external_write`. Must NOT be
flagged: "adapters" does not start with "adapters_" and is not
"adapter_registry", regardless of nesting depth after it.
"""

from external_write.adapters.utils import helper


def use():
    return helper()

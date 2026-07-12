"""Legal (Task R10-T1 negative guard): an up-package relative import (level 2,
`from ..something import x`) that names an unrelated module. `node.module ==
"something"` is neither `adapter_registry` nor `adapters_`-prefixed, so it
must NOT be flagged regardless of the import's level. Guards against a
level-based (rather than module-name-based) implementation that would
over-fire on any relative import with level > 0.
"""

from ..something import x


def use():
    return x

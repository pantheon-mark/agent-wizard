"""Legal (Task R7-T4 negative guard): the emitted `read_facades_<cap>.py`
shape (mirrors read_facades_gmail.py / capability_code_scaffold.py's
render_read_facade_module template) -- imports ONLY `ReadFacade` +
`register_read_facade` from the SEALED_KERNEL `external_write.read_facade`
module and registers a subclass at module scope. Neither imported name is a
banned adapter-registry symbol, and `external_write.read_facade` is neither
the registry nor an adapter-profile module. Must NOT be flagged.
"""

from typing import Any

from external_write.read_facade import ReadFacade, register_read_facade

OP_KIND = "acme_sync"


class AcmeReadFacade(ReadFacade):
    read_methods = ("list_records",)

    def list_records(self) -> Any:
        return self._read("list_records")


register_read_facade(OP_KIND, AcmeReadFacade)

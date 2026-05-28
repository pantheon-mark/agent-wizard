"""Build-side JSON sidecar emission helpers.

Separate from `lib/upgrade.py` (which is the operator-runtime engine — pure read/compute,
no I/O writes). This module hosts build-side write helpers used by bundle-authoring
tools (e.g., `wizard/scripts/emit_bundle_provenance.py`) and by build-side authoring
scripts that emit YAML+JSON sidecar pairs from a generator-owned source dict.

Stdlib-only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


def emit_json_sidecar(data: Dict[str, Any], out_path: Path) -> None:
    """Emit canonical JSON sidecar from a Python dict.

    Canonical = sort_keys=True + indent=2 + ensure_ascii=False + trailing newline.
    Caller is responsible for keeping the source dict in sync with the YAML companion;
    generator-side discipline (no separate YAML parser; generator owns source dict).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    out_path.write_text(payload, encoding="utf-8")

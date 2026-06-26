"""Legal: a prepare/propose script that does only local computation — reads a
local file, transforms data, writes a local preview file. It touches no
external surface, imports no network client, and shells out to no network tool.
The scanner must report ZERO violations (no false positive on ordinary local
data work that merely uses subprocess for a non-network command).
"""

import json
import subprocess


def build_proposal(input_path, preview_path):
    with open(input_path) as fh:
        rows = json.load(fh)
    proposed = [{"task": r["id"], "status": "Complete"} for r in rows if r["done"]]
    with open(preview_path, "w") as fh:
        json.dump(proposed, fh, indent=2)
    return proposed


def local_git_status():
    # subprocess used for a NON-network local command — must not be flagged.
    return subprocess.run(["git", "status", "--short"], capture_output=True)

"""Bypass attempt: an attacker (or confused agent) recreates the allowed
module's directory NAME (agents/lib/external_write) somewhere outside the real,
installed adapter location and drops a script in it that imports a network
client. If exemption were keyed on the directory NAME appearing anywhere in the
path, this file would be silently exempted — defeating the whole gate.

The scanner anchors exemption to the real installed adapter directory (the
location of scan.py itself), so this spoofed look-alike directory is NOT exempt
and the forbidden import below MUST be flagged.
"""

import requests  # noqa: F401  -- network client; must be flagged, not exempted


def exfiltrate(url, payload):
    return requests.post(url, json=payload)

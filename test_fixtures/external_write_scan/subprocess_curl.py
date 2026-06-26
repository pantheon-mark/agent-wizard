"""Bypass: shells out to a network tool (curl) via subprocess / os.system to
mutate an external surface without importing any Python client at all. No
forbidden import, no surface-API attribute call — pure shell. Only inspection
of the subprocess/os.system argument for a network command catches it.
The scanner must flag the subprocess-network and os.system-network calls.
"""

import subprocess
import os


def push_via_curl(url, payload_file):
    subprocess.run(
        ["curl", "-X", "POST", url, "--data-binary", "@" + payload_file],
        check=True,
    )


def push_via_system(url):
    os.system("curl -X POST " + url + " -d @payload.json")


def push_via_wget(url):
    subprocess.run(["wget", "--post-data", "x=1", url], check=True)

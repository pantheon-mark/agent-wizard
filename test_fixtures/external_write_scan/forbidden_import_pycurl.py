"""Bypass: a network client outside the curated denylist's earlier coverage.
``pycurl`` is a libcurl binding that can perform external writes directly. It
must be on the forbidden-import denylist and flagged here.
"""

import pycurl  # noqa: F401  -- network client; must be flagged


def post(url, data):
    c = pycurl.Curl()
    c.setopt(c.URL, url)
    c.setopt(c.POSTFIELDS, data)
    c.perform()
    c.close()

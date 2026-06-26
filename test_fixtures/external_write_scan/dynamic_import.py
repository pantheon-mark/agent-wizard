"""Bypass: defeats static import detection by loading the network client
dynamically. A plain `import requests` is easy to scan for, so this fixture
hides the import behind importlib.import_module / __import__ with a literal
module name. The scanner must flag the dynamic import of a forbidden module.
"""

import importlib


def post_update(url, payload):
    requests = importlib.import_module("requests")
    return requests.post(url, json=payload)


def open_other(url):
    urllib = __import__("urllib.request")
    return urllib.request.urlopen(url)

"""Bypass: imports network / external-write client libraries outside the
adapter package. Any of these imports gives the script a direct path to an
external surface that the adapter is supposed to be the sole holder of.
The scanner must flag each forbidden import.
"""

import requests
import urllib.request
from googleapiclient.discovery import build
import gspread


def post_update(url, payload):
    return requests.post(url, json=payload)


def open_sheet(creds, key):
    gc = gspread.authorize(creds)
    return gc.open_by_key(key)

"""Fixture: a conformant adapter-profile module. Legitimately imports a vendor
SDK, constructs a write-capable credential, and performs raw vendor mutation —
all of which are ONLY legal in the ADAPTER_PROFILE zone.

This file's relative path ("vendor_adapter.py") is NOT in the default
``zones.ADAPTER_PROFILE_MODULE_PATHS`` (that set is empty until a real vendor
adapter is registered), so by default it is classified CAPABILITY -- the
fail-closed default for an unregistered/unclassifiable module -- and every
call below is flagged. It is used TWICE by the test suite:

  1. With no override: proves the fail-closed default (unregistered module,
     even one that looks like a legitimate adapter, is still CAPABILITY).
  2. With ``adapter_profile_paths={"vendor_adapter.py"}`` explicitly passed:
     proves that EXPLICIT registration -- not directory location -- is what
     grants the ADAPTER_PROFILE exemption.
"""

import googleapiclient.discovery  # noqa: F401 -- legal only in adapter-profile zone


def get_write_credential(key_path):
    creds = Credentials.from_service_account_file(key_path)
    return creds.with_subject("operator@example.com")


def apply_one(raw_client, spreadsheet_id, rng, value):
    raw_client.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=rng,
        valueInputOption="RAW",
        body={"values": [[value]]},
    ).execute()

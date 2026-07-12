"""Bypass fixture (Task 7 — external-write-gate-generalization slice): what it
would look like if CAPABILITY-side code tried to obtain a write-capable Gmail
client directly, instead of the write client being provisioned inside the
trusted ADAPTER_PROFILE zone (resolved only inside `adapters.py`'s adapter-
execution path and handed to `adapters_gmail.py`'s own `apply_one`).

Must be flagged on BOTH counts: the vendor SDK import, and the credential
construction below it -- exactly why `adapters_gmail.py` (registered in
`zones.ADAPTER_PROFILE_MODULE_PATHS`) is the ONLY place these are legal. This
is the concrete negative control for the Task 7 acceptance line "a
capability module that imported this adapter's client directly would still
FAIL the scan".
"""

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials


def get_write_capable_gmail_service(token_info):
    creds = Credentials.from_authorized_user_info(token_info)
    return build("gmail", "v1", credentials=creds)


def trash_message_directly(token_info, message_id):
    service = get_write_capable_gmail_service(token_info)
    return service.users().messages().modify(
        userId="me", id=message_id,
        body={"addLabelIds": ["TRASH"], "removeLabelIds": ["INBOX"]},
    ).execute()

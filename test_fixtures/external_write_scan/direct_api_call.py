"""Bypass: calls the Google Sheets mutation API directly instead of routing
through the named-operation adapter. The values().update / batchUpdate / append
calls mutate the external surface with no receipt, no value-validity gate, and
no read-back. The scanner must flag the direct mutation calls.
"""


def write_status(service, spreadsheet_id, rng, value):
    body = {"values": [[value]]}
    # Direct mutation API — bypasses the adapter.
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=rng,
        valueInputOption="RAW",
        body=body,
    ).execute()


def write_many(service, spreadsheet_id, data):
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": data},
    ).execute()


def add_row(service, spreadsheet_id, rng, row):
    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=rng,
        body={"values": [row]},
    ).execute()

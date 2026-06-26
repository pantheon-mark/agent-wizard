"""Bypass: instead of calling the surface-mutation method directly as the func
of a Call, the script binds the bound method to a local name and calls THAT.

    fn = service.spreadsheets().values().update
    fn(spreadsheetId=..., body=...)

The mutation still reaches the external surface, but the ``.update`` attribute
is no longer the immediate func of a Call node — it is an attribute LOAD whose
result is stored. A scanner that only inspects Call.func misses this entirely.

The scanner must flag the surface-mutation attribute reference itself.
"""


def write_status(service, spreadsheet_id, rng, value):
    body = {"values": [[value]]}
    # The mutation method is referenced (loaded), not called inline.
    fn = service.spreadsheets().values().update
    return fn(
        spreadsheetId=spreadsheet_id,
        range=rng,
        valueInputOption="RAW",
        body=body,
    )


def write_many(service, spreadsheet_id, data):
    # batchUpdate referenced as an attribute load, then invoked indirectly.
    op = service.spreadsheets().batchUpdate
    return op(spreadsheetId=spreadsheet_id, body={"requests": data})

"""Bypass: the forbidden mutation is hidden one level deep behind a local
helper function. The entrypoint never names the surface API directly; it calls
_do_write, which performs the direct mutation. A grep of the entrypoint sees
nothing; only call-graph reachability over the file catches it.
The scanner must flag the forbidden operation inside the helper AND treat the
helper's caller as reaching a forbidden surface.
"""


def _do_write(service, spreadsheet_id, rng, value):
    # Forbidden mutation, buried in a helper.
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=rng,
        body={"values": [[value]]},
    ).execute()


def update_task(service, spreadsheet_id, task_id, value):
    rng = "Tasks!B%s" % task_id
    # Looks innocent — but reaches a forbidden surface through the helper.
    _do_write(service, spreadsheet_id, rng, value)

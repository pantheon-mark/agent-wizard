"""False-positive guard (NF1): a plain, non-Gmail object exposing methods
named create/delete/send/modify -- common English verbs that collide with
Gmail's ambiguous mutation-verb set. With NO Gmail surface handle
(messages/drafts/threads/labels/filters/settings/users) anywhere in the
attribute chain, these must NOT be flagged. Proves the surface-handle gate --
not name alone -- drives the ambiguous-verb detection, mirroring the
existing Sheets update/append/clear false-positive discipline.

The scanner must report ZERO violations for this file.
"""


class TaskStore:
    def __init__(self):
        self._tasks = []

    def create(self, task):
        # "create" on a plain local store -- not Gmail's drafts()/filters().
        self._tasks.append(task)
        return task

    def delete(self, task_id):
        # "delete" on a plain local store -- not Gmail's filters().
        self._tasks = [t for t in self._tasks if t["id"] != task_id]


def send_local_notification(bus, payload):
    # "send" on a local, in-process event bus -- not Gmail's messages().
    bus.send(payload)


def modify_local_record(store, record_id, patch):
    # "modify" on a local record store -- not Gmail's messages().
    store.modify(record_id, patch)

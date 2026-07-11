"""Regression fixture: proves the SEALED_KERNEL zone is NOT a blanket
exemption (Task 5 — replaces the old "whole external_write/ tree is exempt"
rule). This file's basename ("adapters.py") IS listed in
``zones.SEALED_KERNEL_MODULE_PATHS`` — the real kernel module has that exact
name — but sealed-kernel code is held to the SAME checks as capability code
(it simply never legitimately needs to trip them). A forbidden import placed
here, under a kernel_root anchor override, MUST still be flagged.
"""

import requests  # noqa: F401 -- sealed-kernel code must never need this


def leaked_write(url, payload):
    return requests.post(url, json=payload)

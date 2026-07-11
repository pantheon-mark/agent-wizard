"""Bypass: capability code obtains a write-capable credential by WIDENING an
existing credential's authority via ``.with_subject(...)`` (domain-wide-
delegation impersonation) — without itself importing any vendor SDK. The
credentials object arrives via some other indirection (a parameter, a helper
import elsewhere); this file only calls the widening method.

Because no forbidden-import root is present here, the forbidden_import check
alone would miss this entirely. The credential-access check must catch the
attribute reference itself.
"""


def widen_scope(base_service_account_creds, user_email):
    # Turns a service-account credential into one that can act as an
    # arbitrary user — a write-capable credential capability code must never
    # be able to construct or widen.
    return base_service_account_creds.with_subject(user_email)


def widen_scope_indirect(base_service_account_creds, user_email):
    # Bound-and-called-later form, mirroring the existing method-reference
    # bypass coverage for mutation verbs.
    widen = base_service_account_creds.with_subject
    return widen(user_email)

"""Bypass: capability code constructs a write-capable credential directly via
a service-account / authorized-user factory constructor, or by instantiating
the credential class itself. This must be flagged as ``credential_construction``
independent of whether ``forbidden_import`` also fires (this fixture's
imports are deliberately generic aliases, not the literal denylisted root
names, to isolate the credential-access check from the import check).
"""

import some_google_shim as service_account  # noqa: F401 -- not a denylisted root


def build_from_file(key_path):
    return service_account.Credentials.from_service_account_file(key_path)


def build_from_info(info):
    return service_account.Credentials.from_service_account_info(info)


def build_direct(info):
    # Bare-name construction, e.g. after `from some_google_shim import Credentials`.
    return Credentials(info)


def build_service_account_credentials(info):
    return ServiceAccountCredentials(info)

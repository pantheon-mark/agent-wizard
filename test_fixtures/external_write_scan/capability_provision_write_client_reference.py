"""Bypass fixture (Task R8-T1): `provision_write_client` -- the write-client
provisioning method name a cross-vendor re-ratification found on the new
dispatch object, not covered by the existing `build_write_client` symbol
(which guards the Adapter-level provisioner, not the AdapterDispatch-level
one). Must be flagged `adapter_registry_reference` on the attribute
reference alone, regardless of which object it is read off -- the same
naming-is-the-bypass discipline as `build_write_client` /
`write_credential_provider`.
"""


def provision(dispatch, op):
    return dispatch.provision_write_client(op)

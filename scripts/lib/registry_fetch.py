"""Shared remote-registry fetch + origin-verify routine — ONE home for the notice + check.

A live operator walk exposed two checkers over two sources: the SessionStart notice read the
AUTHORITATIVE remote registry (saw a newer version) while `wizard upgrade-check` read a STALE
LOCAL mirror and reported "up to date". This module is the single routine both call, so they
can never diverge again.

It fetches the remote registry as DATA (JSON parse only; NEVER executed) from the read-only,
origin-pinned `.wizard/update-source.json` (anti-injection: a prompt cannot repoint it). It
returns a typed `RegistryFetchResult`; callers choose disposition EXPLICITLY:

  * SessionStart notice  -> fail-OPEN  (silent; a notice must never nag/block)
  * `wizard upgrade-check` -> fail-CLOSED (honest could-not-check; NEVER a false "up to date")

The local registry mirror is NOT the currency authority — currency is decided ONLY against
the remote source reached here, or honestly reported unknown.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from update_source import load_update_source, UpdateSourceError  # type: ignore
from upgrade import UpdateStatus  # type: ignore

REGISTRY_RELPATH = "registry/foundation-bundles.json"
DEFAULT_TIMEOUT_SECONDS = 6

# Test / advanced seam (mirrors the SessionStart notice's UPGRADE_NOTICE_REGISTRY_URL): when
# set, this URL is used as the registry source DIRECTLY, bypassing the pin resolution. It lets
# tests point at a `file://` path or a local server without touching the real network or the
# production origin pin. PRODUCTION never sets it — the origin-pinned update-source is the
# source of truth.
REGISTRY_URL_OVERRIDE_ENV = "WIZARD_UPDATE_REGISTRY_URL"

# A fetcher takes (url, timeout_seconds) and returns the response text, or None on ANY
# network/transport failure (it must NEVER raise — failure is signalled by None). Injectable
# so tests never touch the real network.
Fetcher = Callable[[str, int], Optional[str]]


@dataclass
class RegistryFetchResult:
    """Typed outcome of a remote-registry fetch. On success `registry` is the parsed dict;
    on failure `failure_status` is the typed `UpdateStatus` the caller maps to its disposition."""
    ok: bool
    registry: Optional[Dict[str, Any]] = None
    failure_status: Optional["UpdateStatus"] = None
    detail: str = ""
    source_url: str = ""


def registry_url_from_source(source: Dict[str, Any]) -> Optional[str]:
    """Build the remote registry URL from the (validated) update-source pin. Prefers the
    recorded `raw_base_url`; falls back to constructing it from the required owner/repo/branch.
    Returns None if no usable HTTPS base can be formed (treated as a tampered/unusable pin)."""
    raw_base = source.get("raw_base_url")
    if not (isinstance(raw_base, str) and raw_base):
        owner, repo, branch = source.get("repo_owner"), source.get("repo_name"), source.get("branch")
        if owner and repo and branch:
            raw_base = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}"
    if not (isinstance(raw_base, str) and raw_base.startswith("https://")):
        return None
    return raw_base.rstrip("/") + "/" + REGISTRY_RELPATH


def _default_fetcher(url: str, timeout: int) -> Optional[str]:
    """curl first (matches the notice's proven path), then urllib. Returns text or None;
    never raises — any transport failure is None. Honors `file://` (test/offline seam)."""
    if url.startswith("file://"):
        try:
            return Path(url[len("file://"):]).read_text(encoding="utf-8")
        except Exception:
            return None
    if shutil.which("curl"):
        try:
            r = subprocess.run(
                ["curl", "--max-time", str(timeout), "-fsS", url],
                capture_output=True, text=True, timeout=timeout + 2,
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout
        except Exception:
            pass
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "wizard-registry-fetch/1"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def fetch_remote_registry(
    operator_project_dir: Path,
    *,
    fetcher: Optional[Fetcher] = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> RegistryFetchResult:
    """Fetch + parse the AUTHORITATIVE remote registry. Pure of side effects; never raises.

    Failure mapping (all typed; the check renders these as honest could-not-determine, the
    notice stays silent):
      * no/invalid update-source pin            -> SOURCE_UNCONFIGURED
      * pin has no usable HTTPS base            -> UPDATE_SOURCE_TAMPERED
      * remote unreachable / transport failure  -> NETWORK_UNAVAILABLE
      * fetched body not JSON / no bundles      -> REGISTRY_INVALID
    """
    override = os.environ.get(REGISTRY_URL_OVERRIDE_ENV)
    if override:
        url = override
    else:
        try:
            source = load_update_source(operator_project_dir)
        except UpdateSourceError as e:
            return RegistryFetchResult(
                ok=False, failure_status=UpdateStatus.SOURCE_UNCONFIGURED, detail=str(e)
            )
        url = registry_url_from_source(source)
        if url is None:
            return RegistryFetchResult(
                ok=False, failure_status=UpdateStatus.UPDATE_SOURCE_TAMPERED,
                detail="update-source pin has no usable https raw base url",
            )

    fetch = fetcher or _default_fetcher
    text = fetch(url, timeout)
    if text is None:
        return RegistryFetchResult(
            ok=False, failure_status=UpdateStatus.NETWORK_UNAVAILABLE,
            detail="remote registry could not be reached", source_url=url,
        )

    try:
        registry = json.loads(text)
    except Exception as e:
        return RegistryFetchResult(
            ok=False, failure_status=UpdateStatus.REGISTRY_INVALID,
            detail=f"remote registry is not valid JSON: {e}", source_url=url,
        )
    if not isinstance(registry, dict) or not registry.get("bundles"):
        return RegistryFetchResult(
            ok=False, failure_status=UpdateStatus.REGISTRY_INVALID,
            detail="remote registry has no bundles", source_url=url,
        )
    return RegistryFetchResult(ok=True, registry=registry, source_url=url)

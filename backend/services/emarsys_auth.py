"""WSSE authentication helpers for Emarsys API v2."""

from __future__ import annotations

import base64
import hashlib
import os
from datetime import datetime, timezone


def generate_wsse_header() -> str:
    """Build the X-WSSE header required by Emarsys v2 endpoints."""
    api_user = os.getenv("EMARSYS_API_USER", "").strip()
    api_secret = os.getenv("EMARSYS_API_SECRET", "").strip()

    if not api_user:
        raise RuntimeError("Variavel EMARSYS_API_USER nao configurada")
    if not api_secret:
        raise RuntimeError("Variavel EMARSYS_API_SECRET nao configurada")

    nonce_bytes = os.urandom(16)
    nonce_b64 = base64.b64encode(nonce_bytes).decode("ascii")
    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    digest_input = nonce_bytes + created.encode("utf-8") + api_secret.encode("utf-8")
    digest_b64 = base64.b64encode(hashlib.sha1(digest_input).digest()).decode("ascii")

    return (
        f'UsernameToken Username="{api_user}", '
        f'PasswordDigest="{digest_b64}", '
        f'Nonce="{nonce_b64}", '
        f'Created="{created}"'
    )

"""Auditor access code for unlocking company selection."""

from __future__ import annotations

import hashlib
import hmac
import os

DEFAULT_AUDITOR_CODE = "17025-AUDITOR"


def _configured_code() -> str:
    env_code = (os.environ.get("AUDITOR_ACCESS_CODE") or "").strip()
    if env_code:
        return env_code
    try:
        import streamlit as st

        secret = st.secrets.get("auditor_code", "")
        if isinstance(secret, str) and secret.strip():
            return secret.strip()
    except Exception:
        pass
    return DEFAULT_AUDITOR_CODE


def code_is_valid(candidate: str) -> bool:
    given = hashlib.sha256((candidate or "").encode("utf-8")).digest()
    expected = hashlib.sha256(_configured_code().encode("utf-8")).digest()
    return hmac.compare_digest(given, expected)

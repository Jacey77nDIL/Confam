"""Normalize Squad JSON responses (field shapes differ slightly across endpoints)."""

from __future__ import annotations

from typing import Any


def squad_envelope_failed(data: dict[str, Any] | None) -> bool:
    """True when the JSON body clearly indicates an error."""
    if not isinstance(data, dict):
        return True
    if data.get("success") is False:
        return True
    st = data.get("status")
    if isinstance(st, int) and st >= 400:
        return True
    if isinstance(st, str) and st.isdigit() and int(st) >= 400:
        return True
    return False

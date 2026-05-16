"""Nigerian NIP bank codes for Squad payout account lookup (subset + fuzzy match)."""

from __future__ import annotations

import re
from typing import Iterable

# (nip_code, normalized_name) — expand as needed; fuzzy match also scans this list.
NIP_BANKS: tuple[tuple[str, str], ...] = (
    ("000001", "sterling bank"),
    ("000002", "keystone bank"),
    ("000003", "fcmb"),
    ("000004", "united bank for africa"),
    ("000005", "diamond bank"),
    ("000006", "jaiz bank"),
    ("000007", "fidelity bank"),
    ("000008", "polaris bank"),
    ("000009", "citi bank"),
    ("000010", "ecobank"),
    ("000011", "unity bank"),
    ("000012", "stanbic ibtc"),
    ("000013", "gtbank"),
    ("000014", "access bank"),
    ("000015", "zenith bank"),
    ("000016", "first bank"),
    ("000017", "wema bank"),
    ("000018", "union bank"),
    ("000020", "heritage bank"),
    ("000021", "standard chartered"),
    ("000023", "providus bank"),
    ("000025", "titan trust bank"),
    ("000027", "globus bank"),
    ("090267", "kuda microfinance bank"),
    ("090267", "kuda"),
    ("090405", "moniepoint"),
    ("090405", "monie point"),
    ("100004", "opay"),
    ("100004", "opay digital services"),
    ("090110", "vfd microfinance bank"),
    ("090110", "vfd"),
    ("000013", "guaranty trust bank"),
    ("000004", "uba"),
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def nip_code_for_bank_name(bank_name: str | None) -> str | None:
    """Map a free-text bank label (from OCR / user) to a 6-digit NIP bank_code."""
    if not bank_name or not str(bank_name).strip():
        return None
    bn = _norm(str(bank_name))
    if not bn:
        return None

    # Longest label match first (same idea as legacy Paystack mapper).
    ranked: list[tuple[int, str]] = []
    for code, label in NIP_BANKS:
        if label in bn or bn in label:
            ranked.append((len(label), code))
    if ranked:
        ranked.sort(key=lambda x: -x[0])
        return ranked[0][1]

    tokens = [t for t in re.split(r"[^a-z0-9]+", bn) if len(t) >= 3]
    if not tokens:
        return None
    for code, label in NIP_BANKS:
        lt = _norm(label)
        if all(t in lt for t in tokens[:2]):
            return code
    return None


def nip_candidates_for_bank_name(bank_name: str | None, *, limit: int = 12) -> list[str]:
    """Ordered unique NIP codes to try with account lookup."""
    ordered: list[str] = []
    primary = nip_code_for_bank_name(bank_name)
    if primary and primary not in ordered:
        ordered.append(primary)
    if not bank_name:
        return ordered[:limit]
    bn = _norm(str(bank_name))
    tokens = [t for t in re.split(r"[^a-z0-9]+", bn) if len(t) >= 4]
    for code, label in NIP_BANKS:
        lt = _norm(label)
        if tokens and any(t in lt for t in tokens):
            if code not in ordered:
                ordered.append(code)
    return ordered[:limit]


def iter_known_labels() -> Iterable[str]:
    for _, label in NIP_BANKS:
        yield label

"""Phone number normalisation to E.164 with the element's country as the default region."""
from __future__ import annotations

import re

import phonenumbers

_SPLIT = re.compile(r"[;,]")


def split_numbers(raw: str) -> list[str]:
    """Split an OSM phone value holding several numbers (';' or ',') into candidate strings."""
    return [p.strip() for p in _SPLIT.split(raw) if p.strip()]


def to_e164(raw: str, country: str) -> str | None:
    """Parse one number; return E.164 or None when it is not a valid number."""
    try:
        num = phonenumbers.parse(raw, country)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(num):
        return None
    return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)


def normalise_value(raw: str, country: str) -> tuple[list[str], int]:
    """Normalise an OSM phone value. Returns (unique valid E.164 numbers in order, invalid count)."""
    out: list[str] = []
    invalid = 0
    for part in split_numbers(raw):
        e164 = to_e164(part, country)
        if e164 is None:
            invalid += 1
        elif e164 not in out:
            out.append(e164)
    return out, invalid

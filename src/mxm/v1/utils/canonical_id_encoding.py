from __future__ import annotations

"""
Helpers for safely embedding one canonical id inside another flat canonical-id
grammar.

Motivation
----------
MXM canonical ids commonly use a flat delimiter grammar such as:

    PREFIX::KEY=VALUE::KEY=VALUE

If a VALUE itself is another canonical id containing reserved delimiters like
'::' or '=', it must be encoded before embedding, otherwise the outer parser
becomes ambiguous.

These helpers provide a standard reversible encoding for such nested payloads.
"""

from urllib.parse import quote, unquote


def encode_canonical_id_component(value: str) -> str:
    """
    Encode a canonical-id payload for safe embedding as a VALUE in a larger
    flat canonical id.

    This percent-encodes all reserved characters.
    """
    return quote(value, safe="")


def decode_canonical_id_component(value: str) -> str:
    """
    Decode a previously encoded canonical-id payload.
    """
    return unquote(value)

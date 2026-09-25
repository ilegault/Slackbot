"""Fills the blank EPIF template with a parsed request dict.

WHY THIS EXISTS:
Per ADR 0007, an approved EPIF request needs to generate an actual PDF so that it
can be emailed to purchasing (Tina/Ally), using the same template already manually
used by the lab. This is the pure domain logic that creates the filled PDF. It reads
back to the same dictionary `epif_parser.parse_epif` extracts.

Fields `parse_epif` does not read:
- Telephone # for ?'s
- Signature1
- List of Other
"""

def fill_epif(template_bytes: bytes, parsed: dict) -> bytes:
    """Given a blank template PDF and a parsed request, return the filled PDF bytes."""
    pass

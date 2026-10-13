"""Ticket 121 (.scratch/purpose-and-link/spec.md, Part B): the Filled EPIF's Purpose ends
with the request's link, and reading an EPIF gives that link back."""

import os

from src import text_rules
from src.epif_filler import fill_epif
from src.epif_parser import parse_epif

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "EPIF_TEMPLATE_HIRST.pdf")
LINK = "https://fisher.com/a"


def _template():
    with open(FIXTURE_PATH, "rb") as f:
        return f.read()


def _parsed(purpose, link):
    return {
        "item_description": "Gloves",
        "purpose": purpose,
        "link": link,
        "total_price": 120.0,
        "vendor": "Fisher",
        "category": "Research/Lab Supplies (3105)",
        "payment_method": "P-card",
    }


def _round_trip(purpose, link):
    return parse_epif(fill_epif(_template(), _parsed(purpose, link)))


def test_purpose_with_link():
    assert text_rules.purpose_with_link("why", "https://a.com/x") == "why\n\nLink: https://a.com/x"
    assert text_rules.purpose_with_link("why https://a.com/x", "https://a.com/x") == "why https://a.com/x"
    assert text_rules.purpose_with_link("why", "") == "why"
    assert text_rules.purpose_with_link("why", None) == "why"


def test_split_trailing_link():
    assert text_rules.split_trailing_link("why\n\nLink: https://a.com/x") == ("why", "https://a.com/x")
    assert text_rules.split_trailing_link("why\nhttps://a.com/x") == ("why", "https://a.com/x")
    assert text_rules.split_trailing_link("why\nLINK:  https://a.com/x") == ("why", "https://a.com/x")
    prose = "we need this per https://a.com/x for the beamline"
    assert text_rules.split_trailing_link(prose) == (prose, None)
    assert text_rules.split_trailing_link("https://a.com/x") == ("https://a.com/x", None)


def test_fill_appends_the_link_only_when_needed():
    # Link not in Purpose: appended after a blank line.
    out = _round_trip("For the beamline", LINK)
    assert out["raw_fields"]["Purpose"] == f"For the beamline\n\nLink: {LINK}"

    # Link already in Purpose: not written a second time.
    raw = _round_trip(f"For the beamline {LINK}", LINK)["raw_fields"]["Purpose"]
    assert raw.count(LINK) == 1
    assert "Link:" not in raw

    # No link: Purpose is untouched.
    out = _round_trip("For the beamline", None)
    assert out["raw_fields"]["Purpose"] == "For the beamline"


def test_reading_an_epif_takes_a_url_on_the_last_line():
    out = _round_trip("For the beamline\nhttps://fisher.com/a", None)
    assert out["purpose"] == "For the beamline"
    assert out["link"] == "https://fisher.com/a"

    prose = "Per https://fisher.com/a for the beamline"
    out = _round_trip(prose, None)
    assert out["purpose"] == prose
    assert out["link"] == "https://fisher.com/a"

"""Ticket 120 (.scratch/purpose-and-link/spec.md, Part A): Purpose asks only why, and a
link that is already in the Purpose text is not printed a second time on the cards."""

from src import blocks, text_rules

HINT = (
    "Put the product page or quote link in the field below. "
    "It's added to the end of the EPIF's purpose for you."
)
LINK = "https://fisher.com/a"


def _meta():
    return {
        "vendor_choice": "DigiKey",
        "vendor_custom": "",
        "route": "workday",
        "resolved_name": "Isaac",
        "user_id": "U_ISAAC",
        "is_pending_name": False,
        "is_edit": False,
    }


def _request(purpose, link=LINK):
    return {
        "parsed": {
            "item_description": "Gloves",
            "total_price": 120.0,
            "vendor": "Fisher",
            "payment_method": "P-card",
            "category": "Lab Consumable",
            "project_id": "PRJ-1",
            "fund": "133",
            "delivery_room": "ERB 212",
            "purpose": purpose,
            "link": link,
        },
        "requester": "Isaac",
    }


def test_link_in_purpose():
    assert text_rules.link_in_purpose("why https://a.com/x", "https://a.com/x") is True
    assert text_rules.link_in_purpose("why", "https://a.com/x") is False
    assert text_rules.link_in_purpose("why https://a.com/x", "") is False
    assert text_rules.link_in_purpose("why https://a.com/x", None) is False
    assert text_rules.link_in_purpose("why https://a.com/x/", "https://a.com/x/y") is False


def test_screen_2_purpose_asks_only_why():
    by_id = {b.get("block_id"): b for b in blocks.build_stage2_view(_meta())["blocks"]}
    purpose = by_id["block_purpose"]
    assert purpose["label"]["text"] == "Purpose / Why Necessary"
    assert purpose["element"]["placeholder"]["text"] == "Why this is needed for the research"
    assert purpose["hint"]["text"] == HINT
    assert by_id["block_link"]["label"]["text"] == "Product Page / Quote Link (added to the EPIF)"


def test_card_shows_a_link_once():
    # (a) link not in Purpose: one Link line
    lines = blocks.request_summary_lines(_request("For the beamline"), "posted")
    assert [ln for ln in lines if ln == f"• *Link:* {LINK}"] == [f"• *Link:* {LINK}"]

    # (b) link already in Purpose: no Link line, the URL appears once
    lines = blocks.request_summary_lines(_request(f"For the beamline {LINK}"), "posted")
    assert not [ln for ln in lines if ln.startswith("• *Link:*")]
    assert "\n".join(lines).count(LINK) == 1

    # (c) a different URL in Purpose: the Link line stays
    lines = blocks.request_summary_lines(_request("See https://other.com/b"), "posted")
    assert f"• *Link:* {LINK}" in lines


def test_dm_card_shows_a_link_once():
    blks = blocks.build_dm_card_blocks(
        state="approved",
        request=_request(f"For the beamline {LINK}"),
        thread_channel="C123",
        thread_ts="111.222",
        card_ts="333.444",
        thread_link=None,
    )
    text = blks[0]["text"]["text"]
    assert text.count(LINK) == 1
    assert "*Link:*" not in text

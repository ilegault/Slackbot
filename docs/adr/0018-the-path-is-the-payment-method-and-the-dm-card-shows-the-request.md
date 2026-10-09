# ADR 0018 — The path is read from the payment method, and the DM card shows the whole request

**Status:** accepted
**Date:** 2026-10-09
**Amends:** ADR 0007 decision 8 (what the assignee is sent), ADR 0010 decision 2 (what
the DM card shows). ADR 0007 decisions 1 and 5 are unchanged.

## Context

From the day ADR 0007 landed, no `/new-purchase` request on the EPIF path got a filled
EPIF. Screen 1 decided the path correctly, but the path lived only in the modal's private
metadata and was never written onto the posted card. At approval
`interview.get_request_route` found no `route`, no uploaded file and no `source == "epif"`,
and fell back to `workday`. So the bot filled no EPIF, the thread said "to place in
Workday", and the buyer got the Workday DM. In production on 2026-10-06 a P-card order was
assigned "to place in Workday" and no EPIF was made.

The tests stayed green because they built the request by hand with a `route` key the
interview never writes, and one test patched `get_request_route` to always return `epif`.
The Edit opener had already noticed the card has no path and worked it out locally from
the payment method (`app.py`). That made two rules for one fact.

Separately, buyers following a request from their DM saw only "item — vendor, price".
For anything else they had to open the thread.

## Decision

### 1. The payment method is the record of the path

The vendor pick on Screen 1 still decides the path (ADR 0007 decision 1). The interview
already turns that pick into the payment method: `Workday` on the Workday path, P-card or
Req/PO on the EPIF path. From then on the payment method **is** the record.
`interview.get_request_route` returns `epif` when an EPIF file was uploaded. Otherwise it
returns `workday` when the request's payment method is `Workday`, and `epif` for anything
else, blank included.

There is no second record. No code writes a `route` key into a request or a card, and
`get_request_route` does not read one. The Edit opener calls `get_request_route` instead
of keeping its own copy. Screen 1 → Screen 2 modal metadata keeps its `route`, because
before Screen 2 is submitted there is no payment method yet.

A Workday → EPIF switch (ADR 0007 decision 5) changes the payment method, which is how the
path changes.

### 2. The DM card shows everything the thread card shows

The DM card carries the same request lines as the thread card: item, total, vendor with
payment method, category, project and fund, delivery room, purpose, link, buyer, BOM and
quote lines. It also carries the row, the History, the stage and the link to the thread
card. One function builds those lines for both cards, so they cannot drift. The DM card is
still only a view, and the thread card remains the store (ADR 0010 decision 2 otherwise
unchanged).

### 3. What the assignee is sent (replaces ADR 0007 decision 8)

- **Workday path:** one message, the DM card, headed "Place this in Workday". The separate
  "Place this in Workday:" text message goes away.
- **EPIF path:** the email-draft message (the buyer copies text out of it), with the filled
  EPIF, the BOM and quotes attached, and then the DM card. The draft says "Send this email
  to purchasing". It no longer says "Submit via Workday or", because there is no Workday
  on this path.

## Consequences

- A posted card from before this change is read correctly with no migration, because
  every card already has a payment method.
- Tests that put `route` into a request dict are rewritten to set the payment method.
- A failure to post the DM card now means the Workday buyer gets nothing in their DM. That
  is already alerted to admins (`text_rules.format_card_failure_alert`).

# ADR 0007 — How a request's path is chosen, and the bot fills in the EPIF

**Status:** accepted
**Date:** 2026-09-22
**Related:** ADR 0002 (lifecycle and surfaces), ADR 0004/0005 (assignment), ADR 0006 (BOM, editable posted cards)

## Context

Isaac, 2026-09-22, ordering from Winford through the App Home **New purchase** button.
He picked **Not listed / other**, expecting the bot to turn his answers into an EPIF
and send it to the buyer. The bot logged row 20 and replied
*"Assigned to Dylan to process in Workday / ShopUW."* No EPIF existed.

What the code actually did with the route (`interview.route_vendor`):

- `epif` changed only the Screen 2 title and added a P-card / Req/PO question.
- After approval both routes were identical: the same "Workday / ShopUW" line, and
  the same email-draft DM claiming *"Attached is the filled out EPIF"* when nothing
  was attached.
- **Suggest a new vendor that was added to workday** also routed to `epif`, because
  a suggested vendor is by definition not yet on the list.
- A thread holding only a screenshot and a link (the normal shape of a Workday
  order) could not be approved at all: *"I couldn't find a PDF or purchase request."*

## Decision

### 1. Two paths, and what decides them

- **Workday path** — the vendor is on the vendor list. The buyer places it in
  Workday. **No EPIF and no email** exist on this path.
- **EPIF path** — the vendor is not on the list. The bot fills in the EPIF; the
  buyer emails it to purchasing (Tina / Ally).

On the interview, the Screen 1 pick decides. The last option is relabelled to say
what it means, e.g. *"None of these — this will be an EPIF order"*.

### 2. "Suggest a new vendor" is removed

The option goes. Vendors are added by an admin with a new keyword,
`@p-bot add-vendor <name>`, the counterpart of `remove-vendor`. App Home and the help
text say: *vendor not listed but you know it's on Workday → ask an admin to add it.*

### 3. Near-miss vendor names get a warning, not a block

If the name typed under the "none of these" option is effectively a listed vendor —
equal after ignoring case, spacing, punctuation and suffixes such as Inc / LLC, or
closely similar by spelling — Screen 1 shows *"Did you mean X? Pick it from the list
— it's a Workday vendor."* Submitting again unchanged proceeds as EPIF. A hard block
would trap a real non-Workday vendor with a similar name.

### 4. A thread with no EPIF and no form card is a Workday order

When an approver approves a thread that has no EPIF PDF and no interview card, the
bot does **not** refuse. It treats the request as a Workday order and says so in
**one** thread reply:

> ✅ Approved. No EPIF in this thread, so I'm treating this as a **Workday order**.
> @requester, please fill in the details so it can be logged. If this vendor isn't
> on Workday, press **This needs an EPIF** instead.

- The **requester** is the author of the thread's first message.
- The card enters **waiting for details**: approved, no row yet. Buttons:
  **Fill in details**, **This needs an EPIF**, **Cancel**. No stage buttons until a row
  exists. Cancel here writes nothing and closes the card.
- **Fill in details** opens a short Workday form (vendor from the list, item, price,
  category, project, fund). The row is written on submit.
- **This needs an EPIF** opens the interview on the EPIF path, vendor pre-filled.
- Either button: the requester, the assignee, any buyer while unassigned, or an admin.

A thread with an uploaded EPIF PDF is unchanged: it is the EPIF path, as today.

### 5. Approval happens once

Approval is the money decision and is never asked for twice. Choosing or changing the
path after approval is settled between the requester and the buyer.

A Workday request may switch to EPIF **until it is processed**. The same row is
rewritten through `log_writer` and the queue (invariant 2), and the EPIF is generated
then. After processed, the path is fixed.

> **Amends CONTEXT.md "approved — the row is written".** Under decision 4 an approved
> request can briefly have no row. The glossary records this as **waiting for
> details**.

### 6. The bot fills in the EPIF at approval, not at submit

A posted card can still be edited (ADR 0006 decision 8), so the EPIF is generated
once, at approval (or at the Workday→EPIF switch), from the final request.

- Source: the blank **`EPIF_TEMPLATE_HIRST`** PDF in the OneDrive `_TEMPLATE` folder,
  checked at startup like the other OneDrive paths.
- Every field the parser reads is written back to its AcroForm field, so
  `epif_parser.parse_epif(generated_pdf)` returns the request's own values. That
  round trip is the test.
- **PI of Funding** and **Name** (end user) are always *Charles Hirst*. Slack approval
  is the approval; this is what the lab already does by hand.
- Template fields the bot has no value for are left blank.
- With a BOM (two or more line items), *What is being purchased* reads
  `See attached BOM — N items` and *Amount* is the BOM total including shipping.

### 7. One naming rule for every archived EPIF

`<vendor>_EPIF_$<price>_<project id>.pdf` — e.g. `Winford_EPIF_$17.10_PG000025831.pdf`.

- Applies to generated EPIFs **and** EPIFs uploaded to a thread. The file in Slack is
  not renamed; only the archived copy.
- One EPIF per vendor per order (unchanged). If the name is already taken, append
  `_2`, `_3`, … before `.pdf`. Never overwrite.
- The vendor part is made filename-safe (characters Windows forbids are removed).

> **Supersedes** the row-prefixed EPIF naming (`NNNN_<file name>`) in the lifecycle
> spec. The BOM keeps ADR 0006's `NNNN_<Vendor>_BOM.xlsx`.

### 8. What the assignee is sent

- **EPIF path:** DM with the email draft to Tina / Ally **and the generated EPIF
  attached** (plus the BOM, if any). The thread says *"to email to purchasing"*.
- **Workday path:** a short DM — item, vendor, price, link, row — with **no email
  draft**. The thread says *"to place in Workday"*.

The shared *"to process in Workday / ShopUW"* line goes.

## Consequences

- `CONTEXT.md` gains **vendor list**, **waiting for details**, **bare-thread approval**
  and **filled EPIF**, and the **Workday path / EPIF path** entry is rewritten.
- A copy of the blank `EPIF_TEMPLATE_HIRST` must be committed under `tests/fixtures/`
  so the round-trip test fills the real form. The parser knows 25 of the template's
  28 fields; the other three are identified from that copy.
- `EPIF_TEMPLATE_HIRST` must exist in `_TEMPLATE` on the production server before
  deploy. That is a human task.

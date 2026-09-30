# 71: Developer — deploy and verify DM help and the linked cards on the server

**Status:** ready-for-developer

**Runner:** developer

**Auto-merge:** no

**Blocked by:** 62, 63, 64, 65, 66, 67, 68, 69, 70

**Spec:** `.scratch/dm-help-and-linked-cards/spec.md`
**Binding:** `docs/adr/0010-linked-cards-and-direct-message-help.md`

## What to build

A person at the production server and in Slack. **An agent must not claim this ticket.** Use test
requests and cancel or blank their rows by hand afterwards; a request cannot be cancelled once it
is processed.

## Acceptance criteria

- [ ] After merge and `@Purchasing update`, the startup alert is green and `@Purchasing health` is unchanged.
- [ ] DM the bot `I want to purchase this: <any link>`: **one** reply — the *Start a purchase request*
  button above the help text — no crash alert in the alert channel, and no second reply when Slack
  unfurls the link. Pressing the button opens a blank form. `remve-vendor x` in a DM gets "did you mean".
- [ ] Drop a test EPIF in a thread and approve it by typing `@<buyer> @Purchasing Approved`: the thread
  card becomes *Approved* with **Mark Processed** and **Cancel**, and the buyer's DM holds the email
  draft, the attachment, then a card with **Mark Processed**.
- [ ] Press Mark Processed **in the DM**: the thread card shows Processed with **Mark Confirmed**, and
  the DM card shows the same. Press Mark Confirmed **in the thread**: the DM card follows. Press Mark
  Delivered in the DM: neither card has a button.
- [ ] A different buyer pressing a stage button on the thread card is refused privately, naming the
  assigned buyer; the approver pressing it succeeds.
- [ ] On a second test request: Cancel from the thread retires the buyer's DM card; on a third, reassigning
  retires the first buyer's DM card and gives the second buyer a new one.
- [ ] The alert channel shows no crash alert and no *Purchase card problem* alert during any of the above.

## Comments

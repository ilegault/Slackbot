# ADR 0017 — P-card is for orders under $5,000; Req/PO at $5,000 and over

**Status:** accepted
**Date:** 2026-10-07

## Context

The interview asks EPIF-path requesters to pick **P-card** or **Req/PO** with no help on
the form. The FAQ text says only that a P-card "is a university credit card" and a
Req/PO is for vendors that require a requisition. Lab rule (stated by the lab): a P-card
covers orders under $5,000; an order of $5,000 or more is a purchase order and needs three
quotes. A Req/PO under $5,000 is also valid — some vendors only accept a PO.

## Decision

### 1. A P-card at $5,000.00 or more is refused

One rule in `validators.validate`: payment method P-card and total ≥ 5000.00 →
"P-card is for orders under $5,000. Pick Req/PO." It applies to the interview, Edit,
and uploaded EPIFs (at drop and at approval, ADR 0015). The threshold is a constant in
`config.py`. Exactly $5,000.00 is Req/PO.

### 2. Req/PO under $5,000 is allowed

No warning.

### 3. Three quotes are explained, not counted

The bot does not count files in the Quotes field: a sole-source order legitimately has
one quote, and the bot cannot tell which orders those are.

### 4. The difference is explained where the choice is made

A hint under the Payment Method dropdown on every form that shows it:

> P-card — the lab's university credit card, for orders under $5,000. Req/PO — a purchase
> order placed through UW purchasing; required at $5,000 and over (get 3 quotes), or
> whenever a vendor only accepts a PO.

The same text replaces the `p-card`, `req/po` and `req po` answers in
`interview.FAQ_ANSWERS`.

## Consequences

- `CONTEXT.md` gains **P-card** and **Req/PO**.

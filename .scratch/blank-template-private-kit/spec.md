# Spec — /blank-template sends the template kit privately

**Status:** ready-for-agent
**Binding:** ADR 0002 (the interface rule: a thing with no target is a slash command),
ADR 0016 (one rule for who is told), ADR 0019 (the BOM template), ADR 0001 (tests first,
no muted failures)
**Glossary:** `CONTEXT.md` — new: **Template kit**. Uses **BOM template**, **DM**, **Alert channel**.
**Tickets:** `issues/138-template-is-not-a-keyword.md`, `issues/139-blank-template-is-private.md`

## Problem

`/blank-template` posts the guide and the EPIF template publicly in whatever channel it is
typed in, because `app.handle_blank_template_command` builds a `say` that calls
`chat_postMessage` on the command's `channel_id`. In the purchasing channel everyone sees
it. The BOM template, by contrast, already goes to the asker's DM (`ops.send_bom_template`),
so the kit arrives split across two places. A missing EPIF template is reported publicly;
a missing BOM template tells the asker nothing. The guide text does not mention the BOM.

An undocumented `@Purchasing template` keyword (aliases `blank epif`, `blank form`) runs the
same public handler. Nobody has used it.

## Decisions

1. **`/blank-template` is the only way to get the template kit.** The `template`,
   `blank epif` and `blank form` keywords are removed. Typing them gets the ordinary
   unknown-word reply. This keeps ADR 0002's rule: a thing with no target is a slash command.
2. **The kit goes to the asker's DM as one message**: the guide text as the message, the
   blank EPIF template and the BOM template attached to it.
3. **Where they asked, a note only they can see** says the kit is in their DMs, with a
   link to that DM. No note when — and only when — the command was typed in the asker's own
   DM with the bot.
4. **A missing template file never stops the rest.** The DM carries whatever exists plus a
   line naming what could not be attached; the alert channel gets the storage-problem
   message naming the setting. If both files are missing the DM still goes, with the guide
   and both lines.
5. **If the DM cannot be sent**, the asker gets a private note where they asked. Nothing is
   posted publicly.
6. **The guide gains a BOM step**: two or more items means the BOM template too, one
   vendor, total equal to the EPIF amount.
7. **Help text** (App Home and `/purchasing-help`) says the command DMs both templates.
8. The Screen 2 **Send me the BOM template** button is unchanged.

## Out of scope

- No public variant of the kit, by keyword or by flag.
- No change to `ops.send_bom_template` or the Screen 2 button.
- No change to the startup storage check.

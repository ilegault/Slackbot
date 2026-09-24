# 37: An approved EPIF-path request produces a filled EPIF for the buyer

**Status:** ready-for-agent

**Blocked by:** 36

Spec: Implementation Decisions 2 and 3 (the EPIF-path half). Binding: ADR 0007 decisions 6–8, ADR 0006, ADR 0001.

**What to build:** Isaac orders from Winford through the interview on the EPIF path, and
Charlie approves it, assigning Dylan. The row is written. In the same all-or-nothing
queued write, the bot fills the blank `EPIF_TEMPLATE_HIRST` from the request and saves
it as `Winford_EPIF_$17.10_PG000025831.pdf` in `EPIFs/`. The thread says *"Assigned to
@Dylan (Dylan) to email to purchasing."* Dylan's DM has the email draft **with the
filled EPIF attached** (and the BOM, if there is one).

- [ ] A new pure domain module, `epif_filler`, takes the template bytes and the parsed request dict and returns PDF bytes (no Slack, no filesystem). It uses the same config field-name maps the parser uses, so the reader and writer cannot drift.
- [ ] It fills every field `epif_parser.parse_epif` reads. It ticks exactly one category checkbox and exactly one payment checkbox. PI of Funding and Name come from the new config constant `EPIF_PI_AND_END_USER = "Charles Hirst"`. Any other template field is left blank.
- [ ] With two or more line items, the "What is being purchased" field reads `See attached BOM — N items` and the amount is the BOM total including shipping.
- [ ] The three template fields the parser doesn't read are listed by name in the module docstring. If one looks like a required signature or approval field, stop and escalate (ADR 0001) rather than guess.
- [ ] The file is named by a pure function in `log_writer`: `<vendor>_EPIF_$<price>_<project id>.pdf`. The price has two decimals and no thousands separator. The vendor has `<>:"/\|?*` stripped and whitespace collapsed. If the name is already in `EPIFS_DIR`, it becomes `…_2.pdf`, `…_3.pdf`, and so on. It never overwrites.
- [ ] Filling happens at approval (never at submit), inside the queued write task. If the template is missing or unreadable, the task fails: no row, and failure messages go to the thread, the requester and the alert channel.
- [ ] `config.EPIF_TEMPLATE_PATH` defaults to `EPIF_TEMPLATE_HIRST.pdf` in the template directory and can be overridden by an env var. The startup storage check reports it as a **file**, like the others.
- [ ] The EPIF-path thread line reads `to email to purchasing`, and the unassigned line reads `Needs a buyer to email to purchasing.` Which path a request is on is decided by one function: the payload's `route`; with no route, an uploaded EPIF means `epif` and anything else means `workday`.
- [ ] The assignee's DM (at approval or on a later assign, through the one existing implementation) uploads the archived EPIF with the same upload helper the BOM uses, alongside the email draft and any BOM.
- [ ] **Round-trip test** on the committed fixture: for a request in each category, and for both P-card and Req/PO, `parse_epif(fill_epif(template, parsed))` returns the same values that went in, plus Charles Hirst for PI of Funding and end user. There is also a BOM case.
- [ ] **Scenario test**, fake client plus a temporary workbook and a temporary `EPIFs/`: an EPIF-path approval writes the row, archives exactly one correctly named EPIF, DMs the assignee a draft plus a file upload, and posts the thread line. A second identical order archives as `_2`, and the first file is byte-identical afterwards. A missing template writes no row.
- [ ] Existing tests asserting "process in Workday / ShopUW" on EPIF-path requests are updated, and the commit message cites ADR 0007.
- [ ] Full gate green (all four commands).

## Comments

# EPIF Slack bot — build guide

Your four-phase plan is sound in shape. Three things in it don't survive contact
with the actual files, and one of them would quietly damage the workbook. Those
are called out below where they come up.

---

## What I found in your files

**The EPIF is a real AcroForm.** 28 named fields, values stored in the PDF's form
dictionary. `pypdf.PdfReader(...).get_fields()` returns them all by name in one
call. Field names are things like `What is being purchased`, `Amount of Purchase`,
`Project ID Number`, `room address`, `Email add`. The nine category checkboxes and
the two payment checkboxes come back as `/On` or `/Off`.

So **Phase 3's coordinate mapping is unnecessary** — skip `pdfplumber` entirely.
The only case it would help is a flattened PDF (someone printed to PDF instead of
saving the filled form), and in that case the right answer is to bounce it back to
the requester, not to guess at pixel positions. The code does that.

**The Order Log is an Excel Table, not a plain range.**

| | |
|---|---|
| Table name | `OrderLog`, ref `A11:Z1999` |
| Header row | 11 (rows 3–8 are the greyed-out example block) |
| Data starts | row 12; first empty row today is **17** |
| Columns | **26 (A–Z)**, not 31 |
| Column A | array formula for Order ID — *don't write to it* |
| Column Z | array formula for Status — *don't write to it* |
| Columns H | already has `=Qty*Unit Price` on some rows |

Both formula columns are pre-filled all the way to row 1999, so "appending" really
means *filling in the blanks of a row that already exists*. Nothing needs to be
inserted or extended.

**14 dropdowns constrain what you're allowed to write.** Requester Name, Urgency,
How Buying, EPIF Category, Delivery Room, Project ID, Fund, Received By, Status.
Their source lists are on the `Roles & Lists` sheet and are mirrored into
`config.py`. Write a value that isn't in the list and Excel marks the cell invalid
— so validation has to check against the lists, not just check for "not empty".

---

## The one thing in Phase 4 that has to change

> *"Append the row using `pandas.ExcelWriter` with `mode='a'` and `if_sheet_exists='overlay'`."*

Don't. Here's why, measured on your actual file:

```
openpyxl.load_workbook(wb).save(wb)     # a no-op round trip

parts lost: xl/metadata.xml, xl/webextensions/*, xl/calcChain.xml
x14 conditional formatting blocks: 3 -> 0
```

Those three x14 blocks are your Status row colouring (pink / yellow / green) and
the grey-out of Name of System + Asset ID — the thing your own `Roles & Lists`
sheet documents in the "WHAT WORKS HOW FAR DOWN" section. `pandas.ExcelWriter`
goes through openpyxl, so it inherits the same loss. It fails silently: the bot
logs success, and a week later someone notices the colours are gone.

`log_writer.py` instead treats the `.xlsx` as what it is — a zip of XML — copies
every part across byte-for-byte, and edits only the `<c>` elements of the one row
being filled. There's a test in the suite (`test_openpyxl_would_have_destroyed_it`)
that asserts the openpyxl path *does* destroy the formatting, so if a future
openpyxl learns to preserve x14, that test fails and tells you to simplify.

The alternative worth knowing about: if the lab ever moves the workbook onto a
real SharePoint / M365 group site, the Microsoft Graph endpoint
`POST /workbook/tables/OrderLog/rows/add` lets Excel Online do the write. That
preserves everything by construction and removes the file-lock problem below. It
needs an Azure app registration, which is the reason not to start there.

---

## What the EPIF cannot tell you

Six of the 26 columns have no source on the form:

| Column | Where it has to come from |
|---|---|
| B Requester Name | the Slack user who posted the PDF (`SLACK_USER_TO_REQUESTER` map) |
| E Link to Item | scraped as the first URL inside the Purpose paragraph |
| F Qty | not on the EPIF — left blank |
| G Unit Price | not on the EPIF — left blank |
| L How Buying | **P-card / Req-PO is not the same axis as Workday / Out-of-Network** — left blank on purpose |
| N Urgency | not on the EPIF — left blank |

That last one is a decision for you, not the bot. If "P-card ⇒ Workday" is
actually true in your lab, add it to `build_row`; I didn't want to invent it.

Also note: your Prusa example EPIF has **neither** the P-card nor the Req/PO box
ticked, and no Asset ID. The validator rejects it for exactly that reason — which
is a good live demonstration that it works.

---

## Phase 1 — Slack app and environment

```bash
mkdir epif-bot && cd epif-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
git init && git add . && git commit -m "epif bot skeleton"
```

In PyCharm: *File → Settings → Project → Python Interpreter → Add → Existing → `.venv/bin/python`*.

At <https://api.slack.com/apps> → **Create New App → From scratch**, in your lab
workspace.

1. **Socket Mode** → toggle on. This is the right call: it holds an outbound
   WebSocket, so nothing has to reach your machine from outside. Campus NAT and
   firewalls stay out of it. Turning it on generates the **App-Level Token**
   (`xapp-…`) — give it the `connections:write` scope.
2. **OAuth & Permissions → Bot Token Scopes.** Your four, plus two:

   | Scope | Why |
   |---|---|
   | `app_mentions:read` | hear the trigger |
   | `channels:history` | read public-channel threads |
   | **`groups:history`** | **add this if #hirst-lab is private** — otherwise `conversations.replies` returns `channel_not_found` and it looks like the bot is broken |
   | `chat:write` | reply in thread, and DM a user by their `U…` ID |
   | `files:read` | download the attached PDF |
   | **`reactions:write`** | the ✅ on the approval message |

3. **Event Subscriptions → Subscribe to bot events → `app_mention`.**
4. Install to workspace → copy the **Bot User OAuth Token** (`xoxb-…`).
5. In Slack, `/invite @epif-bot` in the channel. The bot cannot read files in a
   channel it isn't a member of, regardless of scopes.

Put both tokens in `.env` (copy `.env.example`). `.env` is already gitignored —
if a token ever lands in a commit, Slack's scanner revokes it within minutes.

---

## Phase 2 — file location

Install the OneDrive client, sync the MUFFIN folder, then set:

```
PURCHASING_LOG_PATH=/home/viscosity_c/OneDrive/MUFFIN/Purchasing-Log.xlsx
```

Two things to know about editing a synced file from a script:

- **If anyone has the workbook open in Excel, OneDrive will conflict-copy your
  write.** Excel leaves a `~$Purchasing-Log.xlsx` lock file next to it while it's
  open. `log_writer` checks for that file and refuses, telling the channel who
  needs to close it. That's much better than producing
  `Purchasing-Log-isaac-pluto.xlsx` and splitting the lab's log in two.
- The write goes to a temp file in the same directory and then `os.replace`s it in.
  That's atomic on the same filesystem, so OneDrive never uploads a half-written
  zip.

---

## Phase 3 — extraction

```python
parsed = epif_parser.parse_epif(pdf_bytes)
# {'item_description': 'Prusa CORE One L+ INDX 4-Tool',
#  'total_price': 2799.0, 'project_id': 'PG000025831', 'fund': '150',
#  'category': 'Research/Lab Supplies (3105)', 'payment_method': None, ...}
```

The parser normalises three things the raw fields don't:

- `'$2799'` → `2799.0`
- `'09/03/26'` → `date(2026, 9, 3)` (tries five formats)
- the ticked checkbox → the **exact dropdown wording** in the log. `Services` on
  the form is `Machining / Prof Services` in the sheet; `Repairs/Maintenance` is
  `Repair & Maintenance`. Those mappings are in `config.CHECKBOX_TO_CATEGORY`.

Thread-walking uses `conversations.replies` as you planned, and takes the *newest*
PDF in the thread — so a corrected re-upload wins over the original.

---

## Phase 4 — validate, then write

`validators.validate()` returns a list of sentences. Empty list means write.
Anything else gets DM'd to the person who uploaded the PDF, not to the approver:

```
I couldn't log Prusa_EPIF__2799_PG000025831.pdf yet:
  • Fund '999' is not one of 133, 135, 144, 150, 233.
  • Tick either the P-card box or the Req/PO box (exactly one).
```

Then `build_row(parsed, requester)` produces `{'B': 'Isaac', 'C': '…', 'H': 2799.0}`
— column letters, not a 26-wide DataFrame. No pandas anywhere. A DataFrame buys
you nothing here: there's one row, the column order is fixed, and two of the
columns must be *skipped* rather than written.

---

## Running it

```bash
source .venv/bin/activate
set -a && source .env && set +a
python app.py
```

You'll see `⚡️ Bolt app is running`. Post an EPIF in the channel, reply in-thread
with `@epif-bot approved`, and watch the log.

To keep it up after you log out, a user systemd unit is the least-effort option:

```ini
# ~/.config/systemd/user/epif-bot.service
[Unit]
Description=EPIF Slack bot
[Service]
WorkingDirectory=/home/viscosity_c/epif-bot
EnvironmentFile=/home/viscosity_c/epif-bot/.env
ExecStart=/home/viscosity_c/epif-bot/.venv/bin/python app.py
Restart=always
[Install]
WantedBy=default.target
```

`systemctl --user enable --now epif-bot` and `loginctl enable-linger $USER`.

---

## Tests

```bash
python -m pytest tests/ -q     # 20 passed
```

They run against the real Prusa EPIF and a copy of the real workbook, and they
assert outcomes rather than "it didn't crash": the parser pulls `2799.0` out of
`$2799`, the blank template is rejected for having no category ticked, the ✅ path
lands `info@prusa3d.com` in `K17`, `M17` reads back as a real date, and the x14
colour rules are still there afterwards.

---

## Before you hand this to Claude Code

Two things need your input first, and neither is guessable:

1. **`SLACK_USER_TO_REQUESTER` in `config.py` is empty.** Every lab member's Slack
   member ID → their exact name in the Requester Name dropdown. Until it's filled
   in, every submission fails validation with "your Slack ID isn't in the
   requester map".
2. **`VALID_PROJECT_IDS` has exactly one entry** (`PG000025831`), because that's
   all the `Roles & Lists` sheet has. If the lab has more project IDs, add them to
   the sheet *and* to config, or every order on a different grant gets rejected.

Good follow-on tickets, roughly in order: replace the hardcoded requester map with
a `users.info` lookup + fuzzy match against the dropdown list; log every rejection
to a local file so you can see which EPIF field the lab gets wrong most often;
then decide whether Qty and Unit Price should be asked for in the Slack thread
rather than left blank.

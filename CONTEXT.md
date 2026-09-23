# CONTEXT.md — the vocabulary of P-Bot

The words this project uses, and the words it deliberately does not. If a term
here and the code disagree, **flag it; do not silently pick a side.**

Everything below is Hirst Lab vocabulary first and software vocabulary second.
When a lab member and a module use different words for the same thing, the lab
member's word wins and the module gets renamed.

---

## People and roles

Three roles, three permission lists, **independent of one another**. Conflating
any two is a bug, not a simplification.

**Approver** — the person who agrees to spend the money. Currently one: Charlie
Hirst, the PI. Charlie approves and never buys. Stored as Slack IDs in the
roster's `approvers`. Checked with `admin.is_approved_reviewer(user_id)`.

**Admin** — the person who manages the bot: the roster, the ops keywords, logs,
restart, update. Currently Isaac. Stored in the roster's `admins`. Being an admin
does not grant approval.

**Buyer** (also *purchase buyer*, *grad buyer*) — a grad student who processes an
approved purchase in Workday or ShopUW. Isaac, Finn, Smeet, Dylan. A buyer is
**assigned** a request — by the approver at approval time, or by any buyer while
the request is still unassigned — and then does the ordering. Being a buyer does
not grant approval. Stored as Slack IDs in the roster's `buyers`, checked with
`roster.is_buyer(user_id)`. Membership is what makes a person *nameable*; it is
not a licence to act on a request already assigned to someone else.

**Requester** — whoever asked for the purchase. Anyone in the lab. Mapped Slack ID
→ name in the roster's `requesters`. The name goes into the workbook, so it is
validated against `roster.json` as the only source — never against a hardcoded list.
`config.VALID_REQUESTERS` was deleted in ticket 11; `roster.get_valid_requesters()` reads
`roster.json`'s `requesters` directly. A name nobody holds is allowed and goes to an
admin for approval; a name another member already holds is refused outright. See
**Lab member** below.

**Purchasing guru** — the buyer currently holding purchasing duty. Charlie set up
a rotating arrangement, Dylan first. This is a **human arrangement, not a role in
the bot.** The bot still does not know whose turn it is — it knows the name the
approver types, and the approver is the person who set the rotation up. See ADR
0004.

**Lab member** — a person the bot knows: a Slack ID with a name in the roster's
`requesters`. Being a lab member is what makes someone a requester, and it is
independent of the three roles. Everyone in the lab should be one; only members
can be assigned requests or have their name written to the workbook.

**Register** — linking your Slack account to your roster name, with
`/roster-set-name`. One command covers all three cases: you are not in the roster
yet, you are and want to correct your name, or the name you want is new to the lab.
A name nobody holds needs an admin's approval before it lands; a name that only
differs from your current one by case, spacing or punctuation applies instantly; a
name another member already holds is refused and never reaches an admin.

**Remove a role** vs **remove a member** — two different acts and never
interchangeable. `remove-buyer` and `remove-approver` take one role away and leave
the person in the lab. **`remove-member` ends their membership**: the `requesters`
entry is hard-deleted and they are stripped from all three role lists at once.
"Dylan is off purchasing duty" is the first; "Katarina graduated" is the second.
Refused if it would leave the lab with no admin or no approver.

> Removing a member does **not** touch the workbook. The `Roles & Lists` mirror is
> append-only by design (ticket 11, requirement 2), so a removed name stays in the
> `Requester Name` dropdown and the bot says so in the alert channel, naming the
> cell. Deleting it is a human's call, because Order Log rows still reference it.

> Avoid "reviewer" as a synonym for approver in anything user-facing.
> `is_approved_reviewer` keeps the name for now because renaming it is a code
> change, not a vocabulary change — but the word in Slack is **approver**.

---

## The request and its stages

**Request** — one purchase, from the moment Charlie approves it. Before approval
there is only a conversation. A purchasing thread discusses freely — links,
quotes, "the 5 mm or the 10 mm" — and there is nothing to make a request *out of*
until someone agrees what to order. This is why approval is the creation moment.

**EPIF** — Equipment & Purchasing Information Form. The lab's purchase form, a
real AcroForm PDF with 28 named fields. Also the name of the non-Workday
purchasing path.

**Workday path / EPIF path** — the two routes a purchase can take. **Workday path**:
the vendor is on the vendor list; the buyer places the order in Workday, and no EPIF
or email exists. **EPIF path**: the vendor is not on the list; the bot fills in the
EPIF and the buyer emails it to purchasing. On the interview, the vendor pick decides.
In a thread, an uploaded EPIF means the EPIF path; no EPIF means the Workday path
(see **Bare-thread approval**). A Workday request can switch to the EPIF path until
it is processed, never after. See ADR 0007.

**Vendor list** — the vendors known to be on Workday. Being on it is what puts a
request on the Workday path. Admins add and remove vendors; requesters do not suggest
them through the interview.

**Filled EPIF** — an EPIF the bot fills in itself from a request's answers, created
once at approval (or at a switch to the EPIF path). PI of Funding and end user are
always Charles Hirst: the Slack approval is the approval. Archived under the same
name as every other EPIF: `<vendor>_EPIF_$<price>_<project id>.pdf`.

### The four stages

After approval, a purchase moves through four stages. **Each has exactly one
word**, used in the button label, the action id, the history line, the help text,
the App Home definitions, and the silent `@p-bot` keyword aliases.

| Word | Means | Excel |
|---|---|---|
| **approved** | Charlie has agreed to spend the money; the row is written (after a bare-thread approval, once the details are in — see **Waiting for details**) | — |
| **processed** | the request has gone to the purchasing team (Workday / ShopUW) | col U, *Date Processed* |
| **confirmed** | the order is confirmed by the vendor | col V, *Date Confirmed* |
| **delivered** | the package is in the lab | col W / X |

> **The word is `processed`.** Not *submitted*, not *submit*, not *ordered*. The
> workbook column has always been *Date Processed*. The code says `submitted` in
> eighteen places and `processed` in one; ticket 05 renames all of them at once.
> Do not add a nineteenth, and do not rename them piecemeal in an unrelated
> ticket.

**Posted** — a request exists and shows an Approve button, but nobody has
approved it. The state before `approved`.

**Bare-thread approval** — an approver approving a thread that has no EPIF and no
interview card: usually a screenshot and a link. The bot treats it as a Workday order,
says so in the thread, and asks the requester (whoever started the thread) to fill in
the details.

**Waiting for details** — approved, with no row yet, because the details have not
been filled in after a bare-thread approval. The only state in which an approved
request has no row. It leaves this state when the details are submitted, or when it
is cancelled.

**Assigned** — a buyer has been named as responsible for processing this request.
The approver names them in the approval message itself — `@Dylan @Purchasing
approved`, in either order — and the bot reads the one non-bot `<@U…>` mention in
it. A named person must already be on the buyers roster.

**Unassigned** — approved, written to the workbook, nobody named yet. A real and
legitimate state: a missing mention never costs an approval. Any buyer may assign
an unassigned request, including to themselves; once it is assigned, only an
approver, an admin or the current assignee may change it.

> **`claim` is dead.** It shipped in ticket 03 and was removed in ticket 08 before
> it ever ran in production. The word, the button, the keyword and the `claimed`
> state are all gone — see ADR 0004, which supersedes ADR 0002 decision 6. Do not
> reintroduce it as a synonym for assigning yourself; that is `assign`.

**Decline** — an approver's "no" on a request that has not been approved. No
reason, no logging, one click. The point is to reduce friction.

**Cancel** — killing a request that *was* approved, before it is processed.
Cancel **un-writes** the Excel row — blanks it, so the row can be recycled. The
workbook is a log of live approved purchases and their stage, nothing else, so a
cancelled purchase does not belong in it. The cancellation is visible as text in
the thread, which is the record. Both approvers and admins can cancel. Cancel is
**refused once a request is processed** — the bot says so clearly in-thread.

> Decline and cancel are different words for different moments and are never used
> interchangeably. Decline is before approval; cancel is after.

**Batch** — one request carrying multiple EPIFs. Big orders often do, plus
quotes. A batch is approved together and cancelled together: **no per-item
control.**

**Line item** — one row of an order: quantity, item name, part number, unit
price, link, description. Entered in the paste box on interview Screen 2 or through
**Add items** on a posted card. One line per item. Quantity is a field, not extra
lines. Carried in the card message's Slack metadata, never in a button value.
See ADR 0006.

**BOM** — bill of materials. The spreadsheet the bot makes from a request's line
items when there are **two or more distinct lines**. It goes to purchasing alongside
the EPIF, so Tina gets one file instead of a pile of links. **One EPIF per vendor is
unchanged; a BOM belongs to exactly one EPIF.** A draft is posted to the thread
before approval. At approval it is archived as `BOMS_DIR/NNNN_<Vendor>_BOM.xlsx`
(`NNNN` = the log row), named in the row's Notes column, and attached to the
assignee's email-draft DM. The items must add up to the EPIF amount (plus a
shipping line). Frozen at approval.

**Edit** — changing a **posted** card before anyone approves it. The requester, a
buyer or an admin may edit. A modal-born card reopens the full Screen 2 form. A
PDF-born card edits line items only, because the PDF is the source for everything
else. Every edit posts one thread line saying what changed. Not available after
approval; the way to change an approved request is **cancel** and resubmit.

**Superseded** — a posted card replaced by a corrected EPIF from the same requester
for the same vendor in the same thread. It is terminal: no buttons, just
"Superseded by a newer EPIF below". Only posted cards can be superseded.

---

## Surfaces

**The interface rule:**

> **If the action needs a target, it is a button on that target.
> If it does not, it is a slash command.**

Slash commands cannot carry thread context — the payload has `channel_id` but no
`thread_ts` — so anything acting on a specific request cannot be one. Block Kit
button clicks carry `channel.id`, `container.message_ts` and
`container.thread_ts`.

**Slash command** — `/new-purchase`, `/purchasing-help`, `/blank-template`,
`/roster-list`, `/roster-set-name`. Things with no target.

**Button** — Approve, Mark Processed, Mark Confirmed, Mark Delivered, Decline,
Cancel. Things with a target, rendered on the request message. **Assignment has
two inputs**: a `users_select` picker on the posted card, and an `@`-mention in the
approval text. Both resolve to one assignment function; if both are given, the
mention wins. ADR 0005 corrects ADR 0004's claim that a button cannot carry a
person — it can, and the earlier reasoning was never checked.

**Keyword** — `@p-bot <word>`. Two kinds: **admin ops** (`restart`, `logs`,
`update`, `health`, `queue`, `promote-admin`, `add-approver`, `remove-approver`,
`add-buyer`, `remove-buyer`, `remove-member`, `remove-vendor`) which are documented and admin-only;
and **lifecycle aliases** (`approved`, `assign`, `processed`, `confirmed`,
`delivered`, `quote`) which keep working so Charlie's habits do not break, but are
taught nowhere. User mentions are stripped from the text *before* a keyword is
matched, so a Slack ID can never be read as a keyword (ADR 0004 decision 8). The
first word after the mention is matched exactly against the canonical vocabulary
(no substring matching); two-word admin phrases match on the first two words. An
unknown word produces a reply naming the words the bot understands.

**The request message / the card** — the bot's post in the channel carrying the
summary, the history block, and one next-step button. It is also the store: state,
payload and history are serialized into the button's `value`, so a bot restart
cannot lose a request's position.

**DM** — where the bot notifies people. Notifications stay DMs across the whole
flow rather than moving to the alert channel, and they are consistent about it.

**Alert channel** — where the bot raises things an admin has to decide (a new
requester, a new vendor, a pending name confirmation). Not for notifications.
It is also the only place the `logs` keyword answers, because logs carry names
and purchase details.

---

## Storage

**The Purchasing Log** — `Purchasing-Log.xlsx` on OneDrive. **The final reference
for the current status of a purchase.** Slack is where the conversation happens;
the workbook is what the lab reads and acts on.

**The lock queue** — the retry queue that serialises every workbook write. The
file is routinely open in Excel on somebody's desktop; the queue turns "locked,
try later" into "written" instead of "lost".

**The roster** — `roster.json`. Requesters, admins, approvers, vendors (and,
after ticket 02, buyers). Admin-manageable from Slack; changes take effect
immediately because every getter re-reads from disk.

**The store** — `src/store.py`. **Currently a word with no referent: nothing in
`src/` imports it.** It acquired tests in ticket 06, which does not make it used. It describes itself as the request index with multi-item batch
mappings and card timestamps, but the request's state actually lives on the
message. Do not use "the store" to mean that module without saying so.

---

## Terms this project avoids

| Do not say | Say |
|---|---|
| submitted, submit, ordered | **processed** |
| reviewer (user-facing) | **approver** |
| grad student (as a permission) | **buyer** |
| claim, claimed, take, i will order | **assign**, **assigned** |
| cancel (before approval) | **decline** |
| decline (after approval) | **cancel** |
| ticket done / complete / completed | **done** (exactly this) |
| delete a member, deregister, kick | **remove-member** |
| remove a requester (meaning the role) | there is no requester *role* — see **Lab member** |

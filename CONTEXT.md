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
→ name in the roster's `requesters`; the name has to match `VALID_REQUESTERS`
exactly because it goes into the workbook.

**Purchasing guru** — the buyer currently holding purchasing duty. Charlie set up
a rotating arrangement, Dylan first. This is a **human arrangement, not a role in
the bot.** The bot still does not know whose turn it is — it knows the name the
approver types, and the approver is the person who set the rotation up. See ADR
0004.

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

**Workday path / EPIF path** — the two routes a purchase can take, decided by the
first question in the interview: *is the vendor on the Workday vendor list?* The
answer changes which detail fields are asked and whether a payment method is
rendered.

### The four stages

After approval, a purchase moves through four stages. **Each has exactly one
word**, used in the button label, the action id, the history line, the help text,
the App Home definitions, and the silent `@p-bot` keyword aliases.

| Word | Means | Excel |
|---|---|---|
| **approved** | Charlie has agreed to spend the money; the row is written | — |
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
Cancel. Things with a target, rendered on the request message. **Assigning is not
a button** — a button cannot carry a person, and the mention already does.

**Keyword** — `@p-bot <word>`. Two kinds: **admin ops** (`restart`, `logs`,
`update`, `health`, `queue`, `promote-admin`, `add-approver`, `remove-approver`,
`add-buyer`, `remove-buyer`, `remove-vendor`) which are documented and admin-only;
and **lifecycle aliases** (`approved`, `assign`, `processed`, `confirmed`,
`delivered`, `quote`) which keep working so Charlie's habits do not break, but are
taught nowhere. User mentions are stripped from the text *before* a keyword is
matched, so a Slack ID can never be read as a keyword (ADR 0004 decision 8).

**The request message / the card** — the bot's post in the channel carrying the
summary, the history block, and one next-step button. It is also the store: state,
payload and history are serialized into the button's `value`, so a bot restart
cannot lose a request's position.

**DM** — where the bot notifies people. Notifications stay DMs across the whole
flow rather than moving to the alert channel, and they are consistent about it.

**Alert channel** — where the bot raises things an admin has to decide (a new
requester, a new vendor, a pending name confirmation). Not for notifications.

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

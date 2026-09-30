"""Pure text parsing, extracting, and templating rules.

WHY THIS EXISTS:
----------------
This is the lowest pure domain layer for string operations, formatting, regex
matching, and email generation. It has no Slack dependencies, makes no network
or I/O calls, and contains no state.

Imports:
    - config (only)
May NOT import:
    - Slack SDK / Bolt
    - storage modules (log_writer, queue_worker, roster, etc.)
    - handlers or listeners
"""
import difflib
import re
import string
from collections.abc import Sequence

try:
    from . import config
except ImportError:
    import config



def parse_mentions(text: str, bot_user_id: str | None = None) -> tuple[str, list[str], list[str]]:
    """Return (text with all mentions removed, user ids excluding the bot, user-group ids).

    WHY THIS EXISTS:
    ----------------
    ADR 0004 decision 1: The approver names the responsible buyer in the approval message itself.
    Mentions must be parsed into user IDs (excluding the bot itself) and subteam user-group IDs.
    ADR 0004 decision 8: Mentions are stripped before keywords are matched, so a Slack ID containing
    substrings like 'log' or 'submit' cannot accidentally route to unrelated command handlers.
    """
    user_ids: list[str] = []
    group_ids: list[str] = []

    # Find user/bot mentions: <@U...>, <@W...>, <@BOT>, with optional |label
    for m in re.finditer(r"<@([A-Za-z0-9_]+)(?:\|[^>]*)?>", text):
        uid = m.group(1)
        if bot_user_id is None or uid.upper() != bot_user_id.upper():
            user_ids.append(uid)

    # Find subteam / user group mentions: <!subteam^S...>, with optional |label
    for m in re.finditer(r"<!subteam\^([A-Za-z0-9_]+)(?:\|[^>]*)?>", text):
        group_ids.append(m.group(1))

    # Strip all mentions from text
    stripped = re.sub(r"<@[A-Za-z0-9_]+(?:\|[^>]*)?>", "", text)
    stripped = re.sub(r"<!subteam\^[A-Za-z0-9_]+(?:\|[^>]*)?>", "", stripped)
    stripped = re.sub(r"@(?i:p-bot|purchasing)\b", "", stripped)
    stripped = re.sub(r" +", " ", stripped).strip()

    return stripped, user_ids, group_ids


def parse_keyword(stripped_text: str) -> str | None:
    """The first word or two-word keyword of a mention-stripped message,
    matched against the canonical vocabulary. None when it matches nothing.

    WHY THIS EXISTS:
    ----------------
    Ticket 16 / Hardening spec §5:
    Keyword routing was previously a chain of substring matches ('any(kw in text_lower)').
    Ticket 52 / ADR 0009 decision 1:
    A hyphen and a space are normalised to the same thing when matching two-word phrases,
    so 'remove-vendor', 'remove vendor', 'add-vendor', 'add vendor', 'blank-epif',
    'blank epif', etc. each resolve to one canonical keyword. For admin ops the
    canonical form in config is the hyphen form ('remove-vendor'); for lifecycle phrases
    it is the space form ('package confirmed').
    A first token that itself contains a hyphen ('remove-vendor') is split on the hyphen
    for matching.
    """
    if not stripped_text:
        return None

    tokens = stripped_text.strip().split()
    if not tokens:
        return None

    import string
    punct = string.punctuation + "“”‘’…"
    w1 = tokens[0].strip(punct).lower()
    if not w1:
        return None

    # Determine two-word candidates:
    # 1. Hyphen form inside the first token: 'remove-vendor' -> 'remove vendor'
    hyphen_two_words = None
    if "-" in w1:
        parts = [p.strip(punct).lower() for p in w1.split("-", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            hyphen_two_words = f"{parts[0]} {parts[1]}"

    # 2. Space form across first two tokens: 'remove' 'vendor' -> 'remove vendor'
    space_two_words = None
    if len(tokens) > 1:
        w2 = tokens[1].strip(punct).lower()
        if w2:
            space_two_words = f"{w1} {w2}"

    # Try two-word matches against all keyword tuples
    # Canonical tuples may have hyphen form ("remove-vendor") or space form ("package confirmed")
    candidates = []
    if hyphen_two_words:
        candidates.append(hyphen_two_words)
    if space_two_words and space_two_words not in candidates:
        candidates.append(space_two_words)

    if candidates:
        for candidate in candidates:
            for kw_tuple in config.ALL_KEYWORD_TUPLES:
                for kw in kw_tuple:
                    if "-" in kw or " " in kw:
                        kw_norm = kw.replace("-", " ")
                        if candidate == kw_norm:
                            return kw

    # Single-word match
    for kw_tuple in config.ALL_KEYWORD_TUPLES:
        if w1 in kw_tuple:
            return w1

    return None


def keyword_argument(stripped_text: str, keyword: str) -> str:
    """Return the text following the matched keyword, whichever spelling was typed.

    WHY THIS EXISTS:
    ----------------
    ADR 0009 decision 1 / Ticket 52:
    Two-word commands accept hyphen or space spellings ('remove-vendor' or 'remove vendor').
    Handlers (like ops.handle_add_vendor / ops.handle_remove_vendor) must not re-parse
    the raw text with their own bespoke regexes that only match one spelling.
    This pure domain function extracts whatever argument follows the matched keyword.
    """
    if not stripped_text or not keyword:
        return ""

    s = stripped_text.strip()
    if not s:
        return ""

    import string
    punct = string.punctuation + "“”‘’…"

    kw_tokens = [w.lower() for w in keyword.replace("-", " ").split()]
    if not kw_tokens:
        return ""

    tokens = s.split()
    if not tokens:
        return ""

    first_token = tokens[0]
    clean_first = first_token.strip(punct).lower()

    # Case 1: The entire keyword is in the first token (e.g. 'remove-vendor' or 'approved')
    if clean_first == keyword.lower() or ("-" in clean_first and clean_first.split("-") == kw_tokens):
        idx = s.find(first_token) + len(first_token)
        return s[idx:].strip()

    # Case 2: Multi-word keyword spanning multiple tokens (e.g. 'remove vendor')
    n = len(kw_tokens)
    if len(tokens) >= n:
        candidate_words = [tokens[i].strip(punct).lower() for i in range(n)]
        if candidate_words == kw_tokens:
            idx = s.find(tokens[0])
            for i in range(1, n):
                idx = s.find(tokens[i], idx + len(tokens[i - 1]))
            idx += len(tokens[n - 1])
            return s[idx:].strip()

    return ""


def closest_keyword(word: str, vocabulary: Sequence[str]) -> str | None:
    """Return the closest keyword from vocabulary, or None if no match meets cutoff.

    WHY THIS EXISTS:
    ----------------
    ADR 0009 Decision 3 / Ticket 53:
    When a user typos a command in a mention or DM, the bot teaches the correct keyword
    in-thread instead of crashing or giving a generic help message.
    Normalisation matches parse_keyword: hyphen = space, trying the first two tokens
    as a candidate phrase before trying the first token alone.
    """
    if not word or not vocabulary:
        return None

    tokens = word.strip().split()
    if not tokens:
        return None

    punct = string.punctuation + "“”‘’…"
    w1 = tokens[0].strip(punct).lower()
    if not w1:
        return None

    # Determine two-word candidates:
    # 1. Hyphen form inside the first token: 'remve-vendor' -> parts: 'remve', 'vendor'
    hyphen_two_words = None
    if "-" in w1:
        parts = [p.strip(punct).lower() for p in w1.split("-", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            hyphen_two_words = (f"{parts[0]} {parts[1]}", f"{parts[0]}-{parts[1]}")

    # 2. Space form across first two tokens: 'remve' 'vendor'
    space_two_words = None
    if len(tokens) > 1:
        w2 = tokens[1].strip(punct).lower()
        if w2:
            space_two_words = (f"{w1} {w2}", f"{w1}-{w2}")

    # Try two-word candidates first (space and hyphen forms against vocabulary)
    two_word_candidates = []
    if hyphen_two_words:
        for c in hyphen_two_words:
            if c not in two_word_candidates:
                two_word_candidates.append(c)
    if space_two_words:
        for c in space_two_words:
            if c not in two_word_candidates:
                two_word_candidates.append(c)

    for cand in two_word_candidates:
        matches = difflib.get_close_matches(cand, vocabulary, n=1, cutoff=config.KEYWORD_SUGGESTION_CUTOFF)
        if matches:
            return matches[0]

    # Single-word match on the first token
    matches = difflib.get_close_matches(w1, vocabulary, n=1, cutoff=config.KEYWORD_SUGGESTION_CUTOFF)
    if matches:
        return matches[0]

    return None


def format_unknown_keyword_message(word: str | None = None, suggestion: str | None = None) -> str:
    """Format the helpful unknown-keyword error reply with optional suggestion.

    WHY THIS EXISTS:
    ----------------
    ADR 0009 Decision 3 / Ticket 53:
    With a close match suggestion, teach the user the right command:
    🤔 I don't know "<word>". Did you mean `@Purchasing <suggestion>`?
    marking admin keywords with ' _(admin only)_'.
    Without a suggestion:
    🤔 I don't know "<word>". Send `@Purchasing help` for the list of commands.
    """
    if suggestion:
        admin_suffix = " _(admin only)_" if suggestion in getattr(config, "ADMIN_ONLY_KEYWORDS", ()) else ""
        if word:
            return f'🤔 I don\'t know "{word}". Did you mean `@Purchasing {suggestion}`?{admin_suffix}'
        return f'🤔 I didn\'t see a command. Did you mean `@Purchasing {suggestion}`?{admin_suffix}'

    if word:
        return f'🤔 I don\'t know "{word}". Send `@Purchasing help` for the list of commands.'
    return "🤔 I didn't see a command. Send `@Purchasing help` for the list of commands."



def extract_request_info(body: dict) -> tuple[str, str, str | None, str | None, bool]:
    """Extract (kind, identifier, user_id, channel_id, is_verbose_msg) from Slack Bolt request body."""
    if not isinstance(body, dict):
        return "unknown", "unknown", None, None, False

    # 1. Slash commands
    if "command" in body:
        return "command", body.get("command", ""), body.get("user_id"), body.get("channel_id"), False

    # 2. Block actions (interactive button clicks, select menus)
    if body.get("type") == "block_actions":
        actions = body.get("actions", [])
        act_id = actions[0].get("action_id", "unknown_action") if actions else "no_action"
        user_id = body.get("user", {}).get("id")
        channel_id = body.get("channel", {}).get("id")
        return "block_actions", act_id, user_id, channel_id, False

    # 3. View submission (modal submit)
    if body.get("type") == "view_submission":
        cb_id = body.get("view", {}).get("callback_id", "unknown_callback")
        user_id = body.get("user", {}).get("id")
        return "view_submission", cb_id, user_id, None, False

    # 4. View closed (modal cancel)
    if body.get("type") == "view_closed":
        cb_id = body.get("view", {}).get("callback_id", "unknown_callback")
        user_id = body.get("user", {}).get("id")
        return "view_closed", cb_id, user_id, None, False

    # 5. Events (app_mention, message, app_home_opened, etc.)
    if body.get("type") == "event_callback":
        ev = body.get("event", {})
        ev_type = ev.get("type", "unknown_event")
        user_id = ev.get("user")
        channel_id = ev.get("channel")
        is_verbose = (ev_type == "message" and (ev.get("channel_type") != "im" or ev.get("subtype") == "bot_message"))
        return "event", ev_type, user_id, channel_id, is_verbose

    # 6. Shortcuts
    if body.get("type") in ("shortcut", "message_action"):
        cb_id = body.get("callback_id", "unknown_shortcut")
        user_id = body.get("user", {}).get("id")
        channel_id = body.get("channel", {}).get("id")
        return "shortcut", cb_id, user_id, channel_id, False

    # Fallback
    b_type = body.get("type", "unknown")
    user_id = body.get("user_id") or body.get("user", {}).get("id")
    channel_id = body.get("channel_id") or body.get("channel", {}).get("id")
    return b_type, b_type, user_id, channel_id, False


def extract_row_from_text(text: str) -> int | None:
    """Extract explicit row number from message text (e.g. 'row 17', '#17')."""
    match = re.search(r"row\s*#?\s*(\d+)", text, re.I)
    if match:
        return int(match.group(1))
    match = re.search(r"\b(\d{2,4})\b", text)
    if match:
        val = int(match.group(1))
        if config.FIRST_DATA_ROW <= val <= config.LAST_DATA_ROW:
            return val
    return None


def extract_price_from_text(text: str) -> float | None:
    """Extract dollar amount or updated price from message text (e.g. '$152.49', '152.49')."""
    match = re.search(r"\$\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)", text)
    if match:
        val_str = match.group(1).replace(",", "")
        try:
            return float(val_str)
        except ValueError:
            pass
    match = re.search(r"(?:price|total|for|amount)\s*(?:of|is|:)?\s*\$?([0-9]+(?:\.[0-9]{1,2})?)", text, re.I)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


def _extract_modal_field(values: dict, block_id: str, action_id: str, field_type: str = "value"):
    """Safely extract field value from Slack modal state values dict."""
    block = values.get(block_id)
    if not isinstance(block, dict):
        return None
    action = block.get(action_id)
    if isinstance(action, dict):
        if field_type == "selected_option":
            opt = action.get("selected_option")
            return opt.get("value") if isinstance(opt, dict) else opt
        elif field_type == "selected_date":
            return action.get("selected_date")
        else:
            return action.get("value")
    return action


def generate_email_draft(parsed: dict, requester_name: str, bom_filename: str | None = None) -> str:
    """Generate a pre-filled email draft matching the lab's purchasing request format.

    When bom_filename is supplied (ticket 30 / ADR 0006 decision 6), an
    "Itemised BOM attached" line is added so Tina knows the spreadsheet accompanies the EPIF.
    """
    vendor = parsed.get("vendor") or "Vendor"
    amount = parsed.get("total_price")
    if isinstance(amount, (int, float)):
        amount_str = f"${amount:,.2f}"
    elif amount is not None:
        try:
            amount_num = float(str(amount).replace("$", "").replace(",", "").strip())
            amount_str = f"${amount_num:,.2f}"
        except (ValueError, TypeError):
            amount_str = str(amount)
    else:
        amount_str = "the specified amount"
    project_id = parsed.get("project_id") or "PG000025831"
    fund = parsed.get("fund")
    fund_str = f" (Fund {fund})" if fund else ""
    link = parsed.get("link") or "[Link to product / cart]"
    item = parsed.get("item_description") or "supplies"
    bom_line = f"Itemised BOM attached: {bom_filename}\n" if bom_filename else ""

    return (
        f"Subject: Hirst Lab purchase request - {vendor} - {item}\n\n"
        f"Hello Tina and Ally,\n\n"
        f"We would like to make a purchase from {vendor} for {amount_str} under project ID {project_id}{fund_str}.\n"
        f"Attached is the filled out EPIF and the link to the website:\n"
        f"{link}\n"
        f"{bom_line}"
        f"\nPlease let me know if you have any questions or edits that need to be made.\n\n"
        f"All the best,\n"
        f"{requester_name}"
    )


def normalize_requester_name(name: str) -> str:
    """Normalize a requester name for comparison: lowercase, stripped punctuation, collapsed whitespace.

    WHY THIS EXISTS:
    ----------------
    Ticket 19: Comparing requester names for impersonation guards and normalization-only
    corrections requires ignoring case, leading/trailing whitespace, internal spacing,
    and punctuation (e.g. 'Isaac' vs '  isaac ' vs 'Prof. Hirst' vs 'Prof Hirst').
    """
    s = name.lower()
    s = re.sub(r"[^\w\s]", "", s)
    return " ".join(s.split())


def storage_problem_message(setting: str, path: str, reason: str) -> str:
    """Format an in-thread warning when a storage location is unusable.

    WHY THIS EXISTS:
    ----------------
    ADR 0009 decision 6: Every operation that reads or writes a storage setting
    (saving an EPIF, confirmation, quote, or BOM; writing the workbook; sending
    the blank template) uses this shared message when that setting is unusable,
    replying in the thread to notify the user and ask an admin to fix the server's .env.
    """
    path_display = path if path else "not set"
    return f"⚠️ I can't reach a storage location. *{setting}* {reason}: `{path_display}`. An admin needs to fix the server's .env."



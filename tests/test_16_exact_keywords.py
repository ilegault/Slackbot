"""Tests for Ticket 16: One word, matched exactly, with a reply when it is unknown.

Covers all acceptance criteria in .scratch/hardening-and-self-service/issues/16-one-word-matched-exactly.md:
- text_rules.parse_keyword exists with pure behavior and matches exactly
- "@Purchasing can you check this?" writes nothing, calls no lifecycle handler, and produces unknown-word reply
- "@Purchasing please take a look" and "@Purchasing waiting on confirmation" produce unknown-word replies
- "@Purchasing approved" still approves, and "@Purchasing submitted" still marks processed
- A message mentioning a user whose Slack ID contains 'log' or 'submit' routes on the typed word, not the ID
- "@Purchasing remove buyer @user" matches as a two-word keyword, and "@Purchasing remove" alone does not
- "test" does not appear in any approval keyword tuple, and a message containing "check" writes no row
- Ordinary channel message with no mention produces no reply (assert on absence)
- Unknown-word reply arrives ephemerally via deny when event carries response_url/respond, and in-thread on app_mention
- CONTEXT.md Keyword entry describes exact matching and the unknown-word reply
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

from src import config, text_rules
from src.app import dispatch_command, on_direct_message


# ---------------------------------------------------------------------------
# 1. Pure function behavior and signature
# ---------------------------------------------------------------------------
def test_parse_keyword_exists_and_is_pure():
    """parse_keyword is pure: given same inputs it produces identical output without I/O."""
    assert hasattr(text_rules, "parse_keyword")

    # Single-word keywords
    assert text_rules.parse_keyword("approved") == "approved"
    assert text_rules.parse_keyword("submitted") == "submitted"
    assert text_rules.parse_keyword("submit") == "submit"
    assert text_rules.parse_keyword("ordered") == "ordered"
    assert text_rules.parse_keyword("processed") == "processed"
    assert text_rules.parse_keyword("help") == "help"
    assert text_rules.parse_keyword("logs") == "logs"
    assert text_rules.parse_keyword("status") == "status"
    assert text_rules.parse_keyword("queue") == "queue"
    assert text_rules.parse_keyword("restart") == "restart"
    assert text_rules.parse_keyword("assign") == "assign"
    assert text_rules.parse_keyword("confirmed") == "confirmed"
    assert text_rules.parse_keyword("delivered") == "delivered"
    assert text_rules.parse_keyword("quote") == "quote"

    # Two-word admin and command keywords
    assert text_rules.parse_keyword("remove buyer") == "remove buyer"
    assert text_rules.parse_keyword("add buyer") == "add buyer"
    assert text_rules.parse_keyword("promote admin") == "promote admin"
    assert text_rules.parse_keyword("add approver") == "add approver"
    assert text_rules.parse_keyword("remove approver") == "remove approver"
    assert text_rules.parse_keyword("remove vendor") == "remove vendor"
    assert text_rules.parse_keyword("git pull") == "git pull"
    assert text_rules.parse_keyword("lock queue") == "lock queue"

    # Hyphenated variants
    assert text_rules.parse_keyword("remove-buyer") == "remove-buyer"
    assert text_rules.parse_keyword("add-buyer") == "add-buyer"
    assert text_rules.parse_keyword("promote-admin") == "promote-admin"
    assert text_rules.parse_keyword("add-approver") == "add-approver"
    assert text_rules.parse_keyword("remove-approver") == "remove-approver"

    # Punctuation stripping around words
    assert text_rules.parse_keyword("approved!") == "approved"
    assert text_rules.parse_keyword("*approved*") == "approved"
    assert text_rules.parse_keyword('"approved"') == "approved"
    assert text_rules.parse_keyword("help?") == "help"
    assert text_rules.parse_keyword("remove buyer:") == "remove buyer"

    # Non-matching words return None
    assert text_rules.parse_keyword("") is None
    assert text_rules.parse_keyword("   ") is None
    assert text_rules.parse_keyword("check") is None
    assert text_rules.parse_keyword("test") is None
    assert text_rules.parse_keyword("can you check this?") is None
    assert text_rules.parse_keyword("please take a look") is None
    assert text_rules.parse_keyword("waiting on confirmation") is None
    assert text_rules.parse_keyword("remove") is None
    assert text_rules.parse_keyword("add") is None

    # Substrings inside longer words do NOT match
    assert text_rules.parse_keyword("confirmation") is None
    assert text_rules.parse_keyword("quoted") is None
    assert text_rules.parse_keyword("submitting") is None


# ---------------------------------------------------------------------------
# 2. "@Purchasing can you check this?"
# ---------------------------------------------------------------------------
def test_can_you_check_this_writes_nothing_calls_no_lifecycle_and_replies_unknown():
    """'@Purchasing can you check this?' writes nothing, calls no lifecycle handler, and replies."""
    client = MagicMock()
    say = MagicMock()

    with (
        patch("lifecycle.handle_epif_processing") as mock_epif,
        patch("lifecycle.handle_processed") as mock_processed,
        patch("lifecycle.handle_confirmation") as mock_conf,
        patch("lifecycle.handle_delivery") as mock_deliv,
        patch("lifecycle.handle_assign") as mock_assign,
        patch("log_writer.append_row") as mock_append,
        patch("queue_worker.submit_write_task") as mock_queue,
    ):
        dispatch_command(
            client=client,
            say=say,
            channel="C_REQ",
            thread_ts="100.1",
            user="U_USER",
            event_ts="100.2",
            text="<@U_BOT> can you check this?",
            bot_user_id="U_BOT",
        )

        # Assert no lifecycle handlers called
        mock_epif.assert_not_called()
        mock_processed.assert_not_called()
        mock_conf.assert_not_called()
        mock_deliv.assert_not_called()
        mock_assign.assert_not_called()

        # Assert no writes attempted
        mock_append.assert_not_called()
        mock_queue.assert_not_called()

        # Assert unknown-word reply sent in-thread
        say.assert_called_once()
        reply = say.call_args[1]["text"]
        assert say.call_args[1]["thread_ts"] == "100.1"
        assert '🤔 I don\'t know the word "can".' in reply
        assert "In a request thread I understand:" in reply
        assert "   approved · assign · processed · confirmed · delivered · quote · decline" in reply
        assert "Or use the buttons on the request message above." in reply


# ---------------------------------------------------------------------------
# 3. "@Purchasing please take a look" and "@Purchasing waiting on confirmation"
# ---------------------------------------------------------------------------
def test_unknown_words_please_and_waiting():
    """'please take a look' and 'waiting on confirmation' produce unknown-word replies."""
    client = MagicMock()
    say = MagicMock()

    with (
        patch("lifecycle.handle_epif_processing") as mock_epif,
        patch("lifecycle.handle_confirmation") as mock_conf,
        patch("lifecycle.handle_assign") as mock_assign,
    ):
        # 1. "please take a look"
        dispatch_command(
            client=client,
            say=say,
            channel="C_REQ",
            thread_ts="100.1",
            user="U_USER",
            event_ts="100.2",
            text="<@U_BOT> please take a look",
            bot_user_id="U_BOT",
        )
        mock_epif.assert_not_called()
        mock_assign.assert_not_called()
        say.assert_called_once()
        assert '🤔 I don\'t know the word "please".' in say.call_args[1]["text"]

        # 2. "waiting on confirmation"
        say.reset_mock()
        dispatch_command(
            client=client,
            say=say,
            channel="C_REQ",
            thread_ts="100.1",
            user="U_USER",
            event_ts="100.3",
            text="<@U_BOT> waiting on confirmation",
            bot_user_id="U_BOT",
        )
        mock_conf.assert_not_called()
        say.assert_called_once()
        assert '🤔 I don\'t know the word "waiting".' in say.call_args[1]["text"]


# ---------------------------------------------------------------------------
# 4. Documented aliases survive
# ---------------------------------------------------------------------------
def test_approved_and_submitted_aliases_survive():
    """'@Purchasing approved' still approves, and '@Purchasing submitted' still marks processed."""
    client = MagicMock()
    say = MagicMock()

    with (
        patch("src.lifecycle.handle_epif_processing") as mock_epif,
        patch("src.lifecycle.handle_processed") as mock_processed,
        patch("src.app.admin.is_approved_reviewer", return_value=True),
        patch("src.app.slack_io.find_row_in_thread", return_value=None),
        patch("src.app.slack_io.find_card_in_thread", return_value=(None, None, None, None)),
    ):
        # @Purchasing approved -> approval handler
        dispatch_command(
            client=client,
            say=say,
            channel="C_REQ",
            thread_ts="100.1",
            user="U_CHARLIE",
            event_ts="100.2",
            text="<@U_BOT> approved",
            bot_user_id="U_BOT",
        )
        mock_epif.assert_called_once()

        # @Purchasing submitted -> processed handler
        dispatch_command(
            client=client,
            say=say,
            channel="C_REQ",
            thread_ts="100.1",
            user="U_BUYER",
            event_ts="100.3",
            text="<@U_BOT> submitted",
            bot_user_id="U_BOT",
        )
        mock_processed.assert_called_once()

        # @Purchasing submit -> processed handler
        mock_processed.reset_mock()
        dispatch_command(
            client=client,
            say=say,
            channel="C_REQ",
            thread_ts="100.1",
            user="U_BUYER",
            event_ts="100.4",
            text="<@U_BOT> submit",
            bot_user_id="U_BOT",
        )
        mock_processed.assert_called_once()


# ---------------------------------------------------------------------------
# 5. User IDs with keyword-shaped tokens (regression on ADR 0004 decision 8)
# ---------------------------------------------------------------------------
def test_mention_id_containing_keyword_substring_routes_on_typed_word():
    """User ID containing 'log' or 'submit' does not trigger unrelated handlers."""
    client = MagicMock()
    say = MagicMock()

    with (
        patch("src.app.ops.handle_logs") as mock_logs,
        patch("src.lifecycle.handle_processed") as mock_processed,
        patch("src.lifecycle.handle_epif_processing") as mock_epif,
        patch("src.app.admin.is_approved_reviewer", return_value=True),
        patch("src.app.slack_io.find_row_in_thread", return_value=None),
        patch("src.app.slack_io.find_card_in_thread", return_value=(None, None, None, None)),
        patch("src.roster.is_buyer", return_value=True),
        patch("src.app.slack_io.resolve_requester", return_value="Dylan"),
    ):
        # <@U_BOT> approved <@U0LOGS99> -> routes to approved, NOT logs
        dispatch_command(
            client=client,
            say=say,
            channel="C_REQ",
            thread_ts="100.1",
            user="U_CHARLIE",
            event_ts="100.2",
            text="<@U_BOT> approved <@U0LOGS99>",
            bot_user_id="U_BOT",
        )
        mock_logs.assert_not_called()
        mock_epif.assert_called_once()
        assert mock_epif.call_args[1]["assignee_id"] == "U0LOGS99"

        # <@U_BOT> approved <@U0SUBMIT123> -> routes to approved, NOT processed
        mock_epif.reset_mock()
        dispatch_command(
            client=client,
            say=say,
            channel="C_REQ",
            thread_ts="100.1",
            user="U_CHARLIE",
            event_ts="100.3",
            text="<@U_BOT> approved <@U0SUBMIT123>",
            bot_user_id="U_BOT",
        )
        mock_processed.assert_not_called()
        mock_epif.assert_called_once()


# ---------------------------------------------------------------------------
# 6. Two-word keyword matching vs single word
# ---------------------------------------------------------------------------
def test_two_word_keyword_and_remove_alone():
    """'@Purchasing remove buyer @user' matches as two words; '@Purchasing remove' alone does not."""
    client = MagicMock()
    say = MagicMock()

    with (
        patch("src.app.ops.handle_remove_buyer") as mock_remove_buyer,
        patch("src.ops.admin.is_admin_user", return_value=True),
    ):
        # 1. Two-word keyword matches
        dispatch_command(
            client=client,
            say=say,
            channel="C_REQ",
            thread_ts="100.1",
            user="U_ADMIN",
            event_ts="100.2",
            text="<@U_BOT> remove buyer <@U_TARGET>",
            bot_user_id="U_BOT",
        )
        mock_remove_buyer.assert_called_once()

        # 2. "remove" alone is not a keyword
        mock_remove_buyer.reset_mock()
        dispatch_command(
            client=client,
            say=say,
            channel="C_REQ",
            thread_ts="100.1",
            user="U_ADMIN",
            event_ts="100.3",
            text="<@U_BOT> remove",
            bot_user_id="U_BOT",
        )
        mock_remove_buyer.assert_not_called()
        say.assert_called_once()
        assert '🤔 I don\'t know the word "remove".' in say.call_args[1]["text"]


# ---------------------------------------------------------------------------
# 7. No "test" in approval keywords; message containing "check" writes no row
# ---------------------------------------------------------------------------
def test_no_test_in_approval_keywords_and_check_writes_no_row():
    """'test' is not in approval keywords, and 'check' writes no row."""
    # Check approval keyword tuple in config
    assert hasattr(config, "APPROVAL_KEYWORDS")
    assert "test" not in config.APPROVAL_KEYWORDS
    assert "check" not in config.APPROVAL_KEYWORDS
    assert "test" not in (config.TRIGGER_KEYWORD,)

    client = MagicMock()
    say = MagicMock()

    with (
        patch("src.log_writer.append_row") as mock_append,
        patch("src.queue_worker.submit_write_task") as mock_queue,
        patch("src.lifecycle.handle_epif_processing") as mock_epif,
    ):
        dispatch_command(
            client=client,
            say=say,
            channel="C_REQ",
            thread_ts="100.1",
            user="U_CHARLIE",
            event_ts="100.2",
            text="<@U_BOT> check this out",
            bot_user_id="U_BOT",
        )
        mock_append.assert_not_called()
        mock_queue.assert_not_called()
        mock_epif.assert_not_called()


# ---------------------------------------------------------------------------
# 8. Ordinary channel message with no mention produces NO reply
# ---------------------------------------------------------------------------
def test_ordinary_channel_message_with_no_mention_produces_no_reply():
    """Ordinary channel message without mention produces no reply (assert on absence)."""
    client = MagicMock()
    say = MagicMock()

    event = {
        "type": "message",
        "channel_type": "channel",
        "channel": "C_GENERAL",
        "text": "can you check this purchase order?",
        "user": "U_MEMBER",
        "ts": "100.1",
        "files": [],
    }

    on_direct_message(event=event, client=client, say=say, context={})

    # Assert completely silent
    say.assert_not_called()
    client.chat_postMessage.assert_not_called()


# ---------------------------------------------------------------------------
# 9. Unknown-word reply routing: ephemeral via deny vs in-thread
# ---------------------------------------------------------------------------
def test_unknown_word_reply_routing_deny_vs_in_thread():
    """Unknown word reply goes via deny with response_url/respond, and in-thread on app_mention."""
    client = MagicMock()
    say = MagicMock()
    mock_respond = MagicMock()

    # Case A: with respond helper (response_url present) -> ephemeral via deny
    with patch("src.app.slack_io.deny") as mock_deny:
        dispatch_command(
            client=client,
            say=say,
            channel="C_REQ",
            thread_ts="100.1",
            user="U_USER",
            event_ts="100.2",
            text="<@U_BOT> foobar",
            bot_user_id="U_BOT",
            respond=mock_respond,
        )
        mock_deny.assert_called_once()
        assert mock_deny.call_args[0][0] == mock_respond
        assert '🤔 I don\'t know the word "foobar".' in mock_deny.call_args[0][1]
        say.assert_not_called()

    # Case B: without respond (standard app_mention in thread) -> say in thread
    say.reset_mock()
    dispatch_command(
        client=client,
        say=say,
        channel="C_REQ",
        thread_ts="100.1",
        user="U_USER",
        event_ts="100.3",
        text="<@U_BOT> foobar",
        bot_user_id="U_BOT",
        respond=None,
    )
    say.assert_called_once()
    assert say.call_args[1]["thread_ts"] == "100.1"
    assert '🤔 I don\'t know the word "foobar".' in say.call_args[1]["text"]


# ---------------------------------------------------------------------------
# 10. CONTEXT.md Keyword entry describes exact matching
# ---------------------------------------------------------------------------
def test_context_md_describes_exact_matching_and_unknown_reply():
    """CONTEXT.md Keyword entry describes exact matching and the unknown-word reply."""
    context_text = Path("CONTEXT.md").read_text(encoding="utf-8")
    assert "exact" in context_text.lower() or "matched exactly" in context_text.lower()
    assert "unknown" in context_text.lower()

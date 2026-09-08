"""The Slack side. Everything here is plumbing - the thinking is in the other files.

Flow of operations:

    someone posts an EPIF pdf in #hirst-lab
      -> Charlie replies in that thread: "@epif-bot approved"
      -> app_mention fires
      -> we walk back up the thread and find the newest .pdf
      -> download it with the bot token
      -> parse -> validate
           fail -> DM the person who posted the PDF, listing what's wrong
           pass -> write one row into Purchasing-Log.xlsx, react with a checkmark
"""
import logging
import os

import requests
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

import config
import epif_parser
import log_writer
import validators

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("epif-bot")

app = App(token=os.environ["SLACK_BOT_TOKEN"])


def find_epif_in_thread(client, channel: str, thread_ts: str):
    """Newest PDF posted in the thread, plus who posted it."""
    replies = client.conversations_replies(channel=channel, ts=thread_ts, limit=200)
    for message in reversed(replies["messages"]):
        for attachment in message.get("files", []):
            name = attachment.get("name", "").lower()
            if name.endswith(".pdf"):
                return attachment, message.get("user")
    return None, None


def download(file_obj) -> bytes:
    """Slack file URLs need the bot token as a bearer header."""
    response = requests.get(
        file_obj["url_private_download"],
        headers={"Authorization": f"Bearer {os.environ['SLACK_BOT_TOKEN']}"},
        timeout=30,
    )
    response.raise_for_status()
    if response.content[:4] != b"%PDF":
        # Slack hands back an HTML login page when the scope is missing.
        raise RuntimeError(
            "Slack returned something that isn't a PDF - the bot is probably "
            "missing the files:read scope, or isn't a member of this channel."
        )
    return response.content


def tell(client, user_id: str, text: str):
    client.chat_postMessage(channel=user_id, text=text)


@app.event("app_mention")
def on_mention(event, client, say):
    text = event.get("text", "").lower()
    if config.TRIGGER_KEYWORD not in text:
        return

    channel = event["channel"]
    thread_ts = event.get("thread_ts") or event["ts"]
    approver = event["user"]

    file_obj, poster = find_epif_in_thread(client, channel, thread_ts)
    if file_obj is None:
        say(text="I couldn't find a PDF in this thread.", thread_ts=thread_ts)
        return

    requester = config.SLACK_USER_TO_REQUESTER.get(poster)

    try:
        parsed = epif_parser.parse_epif(download(file_obj))
    except epif_parser.FlattenedPdfError as error:
        tell(client, poster or approver, str(error))
        say(text="That EPIF has no fillable fields - I've DM'd the requester.",
            thread_ts=thread_ts)
        return

    problems = validators.validate(parsed, requester_name=requester)
    if problems:
        bullets = "\n".join(f"  • {p}" for p in problems)
        tell(
            client,
            poster or approver,
            f"I couldn't log *{file_obj.get('name')}* yet:\n{bullets}\n\n"
            "Fix those in the EPIF, re-upload it to the thread, and ask for "
            "approval again.",
        )
        say(text=f"Not logged - {len(problems)} problem(s), requester DM'd.",
            thread_ts=thread_ts)
        return

    try:
        row = log_writer.append_row(log_writer.build_row(parsed, requester))
    except (log_writer.WorkbookLockedError, log_writer.LogFullError) as error:
        say(text=str(error), thread_ts=thread_ts)
        return

    client.reactions_add(channel=channel, timestamp=event["ts"], name="white_check_mark")
    say(
        text=(
            f"Logged to row {row}: {parsed['item_description']} — "
            f"${parsed['total_price']:,.2f} from {parsed['vendor']} "
            f"({parsed['category']})."
        ),
        thread_ts=thread_ts,
    )


if __name__ == "__main__":
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()

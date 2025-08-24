from dataclasses import dataclass
import os
import re
import random
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk.errors import SlackApiError
from dotenv import load_dotenv
import pydapper
from pydapper.main import connect as db_connect
from src.ping import ping

load_dotenv()

db_url = os.getenv("DATABASE_URL")

@dataclass
class Connection:
    main_chan_id: str
    ping_chan_id: str

app = App()
client = app.client

def wrapper(func):
    def inner(ack, body, command, respond):
        try:
            return func(ack, body, command, respond)
        except Exception as e:
            respond(":tw_interrobang: Oh no, something went wrong!")
            raise e
    return inner

def is_a_member_in_private(channel_id: str) -> bool:
    try:
        info = client.conversations_info(
            channel=channel_id
        )
    except SlackApiError:
        return False
    channel = info["channel"]
    assert channel is not None
    return channel.get("is_private", False)

def members_of(channel_id: str) -> list[str]:
    members = []
    cursor = None
    while True:
        if cursor is None:
            resp = client.conversations_members(
                channel=channel_id,
                limit=200
            )
        else:
            resp = client.conversations_members(
                channel=channel_id,
                limit=200,
                cursor=cursor
            )
        members.extend(resp.get("members", []))
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    return members

def channel_creator_of(channel_id: str) -> str:
    info = client.conversations_info(
        channel=channel_id
    )
    channel = info["channel"]
    assert channel is not None
    return channel.get("creator", "")

def say(channel_id: str, text: str):
    return client.chat_postMessage(
        channel=channel_id,
        text=text
    )

def say_custom(channel_id: str, text: str, mimic_user_id: str):
    user_info = client.users_info(user=mimic_user_id)
    user = user_info.get("user")
    assert user is not None
    icon_url = user["profile"].get("image_72", "")
    username = user["profile"].get("display_name", "")
    if username is None or username == "":
        username = user["profile"].get("real_name", "oiac")
    else:
        username = f"{username} (oiac)"
    return client.chat_postMessage(
        channel=channel_id,
        text=text,
        username=username,
        icon_url=icon_url
    )

def invite_safe(channel_id: str, user_id: str):
    try:
        client.conversations_invite(
            channel=channel_id,
            users=user_id
        )
    except SlackApiError as e:
        error = e.response.get("error")
        assert error is not None
        if error == "already_in_channel":
            pass
        else:
            raise e

@app.command("/optin")
@wrapper
def handle_optin(ack, body, command, respond):
    assert db_url is not None, "DATABASE_URL is not set"
    ack()
    user_id = body["user_id"]
    channel_id = body["channel_id"]
    self_user_id = client.auth_test()["user_id"]
    assert self_user_id is not None
    with db_connect(db_url) as db:
        connection = db.query_single_or_default(
            "SELECT main_chan_id, ping_chan_id FROM connections WHERE main_chan_id = ?channel_id?",
            param={"channel_id": channel_id},
            model=Connection,
            default=None
        )
        if connection is None:
            respond(":tw_warning: This channel does not implement oiac.")
            return
        ping_channel_id = connection.ping_chan_id
        if not is_a_member_in_private(ping_channel_id):
            respond(f""":tw_interrobang: Huh?! I don't seem to be in <#{ping_channel_id}>.
Either someone kicked me out or there's a catastrophic failure.""")
            return
    client.conversations_invite(channel=ping_channel_id, users=user_id)
    respond(f":tw_white_check_mark: Opted in to oiac pings from <#{channel_id}|> via <#{ping_channel_id}|>")

@app.command("/optout")
@wrapper
def handle_optout(ack, body, command, respond):
    assert db_url is not None, "DATABASE_URL is not set"
    ack()
    user_id = body["user_id"]
    channel_id = body["channel_id"]
    self_user_id = client.auth_test()["user_id"]
    assert self_user_id is not None
    with db_connect(db_url) as db:
        connection = db.query_single_or_default(
            "SELECT main_chan_id, ping_chan_id FROM connections WHERE main_chan_id = ?channel_id?",
            param={"channel_id": channel_id},
            model=Connection,
            default=None
        )
        if connection is None:
            respond(":tw_warning: This channel does not implement oiac.")
            return
        ping_channel_id = connection.ping_chan_id
        if not is_a_member_in_private(ping_channel_id):
            respond(f""":tw_interrobang: Huh?! I don't seem to be in <#{ping_channel_id}>.
Either someone kicked me out or there's a catastrophic failure.""")
            return
    client.conversations_kick(channel=ping_channel_id, user=user_id)
    respond(f":tw_white_check_mark: Opted out of oiac pings from <#{channel_id}|>")

@app.command("/oiac-on")
@wrapper
def handle_oiac_on(ack, body, command, respond):
    assert db_url is not None, "DATABASE_URL is not set"
    ack()
    user_id = body["user_id"]
    channel_id = body["channel_id"]
    self_user_id = client.auth_test()["user_id"]
    assert self_user_id is not None
    target_channel_id = None
    matches = re.findall(r"<#(C\w+[^>|]*)(?:\|[^>]*)?>", command["text"])
    if channel_creator_of(channel_id) != user_id:
        respond(":tw_warning: You must be a channel creator to enable oiac.")
        return
    with db_connect(db_url) as db:
        connection = db.query_single_or_default(
            "SELECT main_chan_id, ping_chan_id FROM connections WHERE main_chan_id = ?channel_id?",
            param={"channel_id": channel_id},
            model=Connection,
            default=None
        )
        if connection is not None:
            respond(":tw_warning: This channel already implements oiac.")
            return
    if len(matches) == 1:
        target_channel_id = matches[0]
        if not is_a_member_in_private(target_channel_id):
            respond(f""":tw_warning: Either the channel <#{target_channel_id}|> is not private or you need to invite me to it.""")
            return
        if user_id not in members_of(target_channel_id):
            respond(f""":tw_warning: Woah! You aren't a member of <#{target_channel_id}|>.""")
            return
        if channel_creator_of(target_channel_id) not in [self_user_id, user_id]:
            respond(f""":tw_warning: You (or I) need to have created <#{target_channel_id}|>.""")
        with db_connect(db_url) as db:
            connection = db.query_first_or_default(
                "SELECT main_chan_id, ping_chan_id FROM connections WHERE ping_chan_id = ?channel_id?",
                param={"channel_id": target_channel_id},
                model=Connection,
                default=None
            )
            if connection is not None:
                respond(f""":tw_warning: <#{target_channel_id}|> is already taken!""")
    elif len(matches) > 1:
        respond(":tw_warning: Please specify only one channel.")
        return
    else:
        chosen_name = re.sub(r"[^a-z0-9-_]", "-", command["text"].strip().lower())

        channel_info = client.conversations_info(
            channel=channel_id
        )
        channel_name = channel_info.get("channel", {}).get("name")
        assert channel_name is not None
        target_channel_name = channel_name + "-ping" if chosen_name == "" else chosen_name
        try:
            req = client.conversations_create(
                name=target_channel_name,
                is_private=True
            )
        except SlackApiError as e:
            error = e.response.get("error")
            assert error is not None
            if error == "name_taken":
                if chosen_name != "":
                    respond(f""":tw_warning: The channel name `{target_channel_name}` is already taken. Please choose a different name.
If you meant to use an already existing channel, please mention it instead.""")
                    return
                target_channel_name += f"-{random.randint(1000000000, 9999999999)}"
                req = client.conversations_create(
                    name=target_channel_name,
                    is_private=True
                )
            else:
                raise e
        target_channel_id = req.get("channel", {}).get("id")
        assert target_channel_id is not None
    with db_connect(db_url) as db:
        db.execute(
            "INSERT INTO connections (main_chan_id, ping_chan_id) VALUES (?channel_id?, ?ping_channel_id?) ON CONFLICT(main_chan_id) DO UPDATE SET ping_chan_id = ?ping_channel_id?",
            param={"channel_id": channel_id, "ping_channel_id": target_channel_id}
        )
    say(target_channel_id, f":tw_information_source: This channel is now used for oiac pings from <#{channel_id}>. Enabled by <@{user_id}>.")
    invite_safe(target_channel_id, user_id)
    respond(f":tw_white_check_mark: oiac is now ON. Pings will be sent via <#{target_channel_id}|>.")

@app.command("/oiac-off")
@wrapper
def handle_oiac_off(ack, body, command, respond):
    assert db_url is not None, "DATABASE_URL is not set"
    ack()
    user_id = body["user_id"]
    channel_id = body["channel_id"]
    self_user_id = client.auth_test()["user_id"]
    assert self_user_id is not None
    if channel_creator_of(channel_id) != user_id:
        respond(":tw_warning: You must be a channel creator to enable oiac.")
        return
    with db_connect(db_url) as db:
        connection = db.query_single_or_default(
            "SELECT main_chan_id, ping_chan_id FROM connections WHERE main_chan_id = ?channel_id?",
            param={"channel_id": channel_id},
            model=Connection,
            default=None
        )
        if connection is None:
            respond(":tw_warning: This channel does not implement oiac.")
            return
        ping_channel_id = connection.ping_chan_id
        try:
            info = client.conversations_info(
                channel=ping_channel_id
            )
        except SlackApiError:
            respond(f":tw_interrobang: Huh?! The associated ping channel <#{ping_channel_id}|> doesn't seem to exist.")
            return
        if not is_a_member_in_private(ping_channel_id):
            respond(f""":tw_interrobang: Huh?! I don't seem to be in <#{ping_channel_id}>.
Either someone kicked me out or there's a catastrophic failure.""")
            return
        db.execute(
            "DELETE FROM connections WHERE main_chan_id = ?channel_id?",
            param={"channel_id": channel_id}
        )
    respond(":tw_white_check_mark: oiac is now OFF.")

@app.command("/oiac")
@wrapper
def handle_oiac(ack, body, command, respond):
    assert db_url is not None, "DATABASE_URL is not set"
    ack()
    user_id = body["user_id"]
    channel_id = body["channel_id"]
    self_user_id = client.auth_test()["user_id"]
    text = command["text"].strip()
    assert self_user_id is not None
    with db_connect(db_url) as db:
        connection = db.query_single_or_default(
            "SELECT main_chan_id, ping_chan_id FROM connections WHERE main_chan_id = ?channel_id?",
            param={"channel_id": channel_id},
            model=Connection,
            default=None
        )
    if connection is None:
        respond(":tw_warning: This channel does not implement oiac.")
        return
    ping_channel_id = connection.ping_chan_id
    if not is_a_member_in_private(ping_channel_id):
        respond(f""":tw_interrobang: Huh?! I don't seem to be in <#{ping_channel_id}>.""")
    if channel_creator_of(channel_id) != user_id:
        respond(":tw_warning: You must be a channel creator to use oiac.")
        return
    x = say_custom(channel_id, text, user_id)
    ref = f"https://hackclub.slack.com/archives/{x['channel']}/p{x['ts'].replace('.', '')}" # type: ignore
    ping(app, ping_channel_id, ref)

def main():
    handler = SocketModeHandler(app, os.getenv("SLACK_APP_TOKEN"))
    handler.start()

if __name__ == "__main__":
    main()
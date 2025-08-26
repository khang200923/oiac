from dataclasses import dataclass
import os
from pathlib import Path
import re
import random
from functools import lru_cache
from traceback import format_exc
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk.errors import SlackApiError
from dotenv import load_dotenv
import pydapper
from pydapper.main import connect as db_connect
from src.ping import ping
from src.logger import get_logger

load_dotenv()
required_envs = [
    "DATABASE_URL",
    "SLACK_APP_TOKEN",
    "SLACK_BOT_TOKEN",
    "OWNER_ID",
    "LOG_FILE"
]
if not all(env in os.environ for env in required_envs):
    missing = [env for env in required_envs if env not in os.environ]
    raise EnvironmentError(f"Missing required environment variable(s): {', '.join(missing)}")

db_url = os.environ["DATABASE_URL"]
channel_pattern = re.compile(r"<#([CG]\w+)(?:\|[^>]*)?>")
user_pattern = re.compile(r"<@(U\w+)(?:\|[^>]*)?>")

@dataclass
class Connection:
    main_chan_id: str
    ping_chan_id: str

@dataclass
class ChanUserRel:
    chan_id: str
    user_id: str

app = App()
client = app.client
owner_id = os.getenv("OWNER_ID")
domain = client.team_info().get("team", {})["domain"] # type: ignore
assert domain is not None
logger = get_logger(debug_log_file=Path(os.environ["LOG_FILE"]))

def wrapper(func):
    def inner(ack, body, command, respond):
        try:
            return func(ack, body, command, respond)
        except Exception:
            respond(f""":tw_interrobang: Oh no, something went wrong!
Send <@{owner_id}> the following stack trace:
```
{format_exc()}
```""")
            logger.error("Error in command handler: %s", format_exc())
            ack()
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
    # if we can even find out the private channel, we are in it
    # big brain moment
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

@lru_cache(maxsize=128)
def channel_creator_of(channel_id: str) -> str:
    info = client.conversations_info(
        channel=channel_id
    )
    channel = info["channel"]
    assert channel is not None
    return channel.get("creator", "")

def has_ping_perm(channel_id: str, user_id: str) -> bool:
    with db_connect(db_url) as db:
        rel = db.query_single_or_default(
            "SELECT chan_id, user_id FROM pingers WHERE chan_id = ?channel_id? AND user_id = ?user_id?",
            param={"channel_id": channel_id, "user_id": user_id},
            model=ChanUserRel,
            default=None
        )
        if rel is not None:
            return True
    if channel_creator_of(channel_id) == user_id:
        db.execute(
            "INSERT INTO pingers (chan_id, user_id) VALUES (?channel_id?, ?user_id?)",
            param={"channel_id": channel_id, "user_id": user_id}
        )
        return True
    return False

def has_ping_manager_perm(channel_id: str, user_id: str) -> bool:
    with db_connect(db_url) as db:
        rel = db.query_single_or_default(
            "SELECT chan_id, user_id FROM ping_managers WHERE chan_id = ?channel_id? AND user_id = ?user_id?",
            param={"channel_id": channel_id, "user_id": user_id},
            model=ChanUserRel,
            default=None
        )
        if rel is not None:
            return True
    if channel_creator_of(channel_id) == user_id:
        db.execute(
            "INSERT INTO ping_managers (chan_id, user_id) VALUES (?channel_id?, ?user_id?)",
            param={"channel_id": channel_id, "user_id": user_id}
        )
        return True
    return False

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
    username = f"{username} (oiac)"
    return client.chat_postMessage(
        channel=channel_id,
        text=text,
        username=username,
        icon_url=icon_url
    )

def invite_safe(channel_id: str, user_id: str) -> bool:
    try:
        client.conversations_invite(
            channel=channel_id,
            users=user_id
        )
        return True
    except SlackApiError as e:
        error = e.response.get("error")
        if error == "already_in_channel":
            return False
        else:
            raise e
        
def kick_safe(channel_id: str, user_id: str) -> bool:
    try:
        client.conversations_kick(
            channel=channel_id,
            user=user_id
        )
        return True
    except SlackApiError as e:
        error = e.response.get("error")
        if error == "not_in_channel":
            return False
        else:
            raise e
        
def check_postgres(connection_string: str) -> bool:
    try:
        with db_connect(connection_string) as db:
            db.execute("SELECT 1")
        return True
    except Exception:
        return False

@app.command("/optin")
@wrapper
def handle_optin(ack, body, command, respond):
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
            logger.warning("In /optin, bot not in ping channel %s", ping_channel_id)
            return
    invited = invite_safe(ping_channel_id, user_id)
    if not invited:
        respond(f":tw_warning: You are already in <#{ping_channel_id}>.")
        return
    respond(f":tw_white_check_mark: Opted in to oiac pings from <#{channel_id}> via <#{ping_channel_id}>")
    logger.info("In /optin, user %s opted in to channel %s", user_id, channel_id)

@app.command("/optout")
@wrapper
def handle_optout(ack, body, command, respond):
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
            logger.warning("In /optout, bot not in ping channel %s", ping_channel_id)
            return
    kicked = kick_safe(ping_channel_id, user_id)
    if not kicked:
        respond(f":tw_warning: You are not in <#{ping_channel_id}>.")
        return
    respond(f":tw_white_check_mark: Opted out of oiac pings from <#{channel_id}>")
    logger.info("In /optout, user %s opted out of channel %s", user_id, channel_id)

@app.command("/oiac-on")
@wrapper
def handle_oiac_on(ack, body, command, respond):
    ack()
    user_id = body["user_id"]
    channel_id = body["channel_id"]
    self_user_id = client.auth_test()["user_id"]
    assert self_user_id is not None
    target_channel_id = None
    matches = re.findall(channel_pattern, command["text"])
    if not has_ping_manager_perm(channel_id, user_id):
        respond(":tw_warning: You must be a ping manager to enable oiac.")
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
            respond(f""":tw_warning: Either the channel <#{target_channel_id}> is not private or you need to invite me to it.""")
            return
        if user_id not in members_of(target_channel_id):
            respond(f""":tw_warning: Woah! You aren't a member of <#{target_channel_id}>.""")
            logger.warning("In /oiac-on, user %s not in target channel %s", user_id, target_channel_id)
            return
        if channel_creator_of(target_channel_id) not in [self_user_id, user_id]:
            respond(f""":tw_warning: You (or I) need to have created <#{target_channel_id}>.""")
            return
        with db_connect(db_url) as db:
            connection = db.query_single_or_default(
                "SELECT main_chan_id, ping_chan_id FROM connections WHERE ping_chan_id = ?channel_id?",
                param={"channel_id": target_channel_id},
                model=Connection,
                default=None
            )
            if connection is not None:
                respond(f""":tw_warning: <#{target_channel_id}> is already taken!""")
                return
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
    respond(f":tw_white_check_mark: oiac is now ON. Pings will be sent via <#{target_channel_id}>.")
    logger.info("In /oiac-on, user %s enabled oiac for channel %s with ping channel %s", user_id, channel_id, target_channel_id)

@app.command("/oiac-off")
@wrapper
def handle_oiac_off(ack, body, command, respond):
    ack()
    user_id = body["user_id"]
    channel_id = body["channel_id"]
    self_user_id = client.auth_test()["user_id"]
    assert self_user_id is not None
    if not has_ping_manager_perm(channel_id, user_id):
        respond(":tw_warning: You must be a ping manager to disable oiac.")
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
            respond(f":tw_interrobang: Huh?! The associated ping channel <#{ping_channel_id}> doesn't seem to exist.")
            logger.warning("In /oiac-off, ping channel %s does not exist", ping_channel_id)
            return
        if not is_a_member_in_private(ping_channel_id):
            respond(f""":tw_interrobang: Huh?! I don't seem to be in <#{ping_channel_id}>.
Either someone kicked me out or there's a catastrophic failure.""")
            logger.warning("In /oiac-off, bot not in ping channel %s", ping_channel_id)
            return
        db.execute(
            "DELETE FROM connections WHERE main_chan_id = ?channel_id?",
            param={"channel_id": channel_id}
        )
    respond(":tw_white_check_mark: oiac is now OFF.")
    logger.info("In /oiac-off, user %s disabled oiac for channel %s", user_id, channel_id)

@app.command("/oiac")
@wrapper
def handle_oiac(ack, body, command, respond):
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
        logger.warning("In /oiac, bot not in ping channel %s", ping_channel_id)
        return
    if not has_ping_perm(channel_id, user_id):
        respond(":tw_warning: You must be a pinger to send pings.")
        return
    x = say_custom(channel_id, text, user_id)
    ref = f"https://{domain}.slack.com/archives/{x['channel']}/p{x['ts'].replace('.', '')}" # type: ignore
    ping(app, ping_channel_id, ref)
    logger.info("In /oiac, user %s sent ping from channel %s with ref %s", user_id, channel_id, ref)

@app.command("/oiac-add-pinger")
@wrapper
def handle_oiac_add_pinger(ack, body, command, respond):
    ack()
    user_id = body["user_id"]
    channel_id = body["channel_id"]
    self_user_id = client.auth_test()["user_id"]
    assert self_user_id is not None
    matches = re.findall(user_pattern, command["text"])
    logger.debug(command["text"])
    if not has_ping_manager_perm(channel_id, user_id):
        respond(":tw_warning: You must be a ping manager to add pingers.")
        return
    if len(matches) != 1:
        respond(":tw_warning: Please mention exactly one user to add as a pinger.")
        return
    new_pinger_id = matches[0]
    with db_connect(db_url) as db:
        if has_ping_perm(channel_id, new_pinger_id):
            respond(f":tw_warning: <@{new_pinger_id}> is already a pinger.")
            return
        db.execute(
            "INSERT INTO pingers (chan_id, user_id) VALUES (?channel_id?, ?user_id?)",
            param={"channel_id": channel_id, "user_id": new_pinger_id}
        )
    respond(f":tw_white_check_mark: Added <@{new_pinger_id}> as a pinger.")
    logger.info("In /oiac-add-pinger, user %s added pinger %s for channel %s", user_id, new_pinger_id, channel_id)

@app.command("/oiac-remove-pinger")
@wrapper
def handle_oiac_remove_pinger(ack, body, command, respond):
    ack()
    user_id = body["user_id"]
    channel_id = body["channel_id"]
    self_user_id = client.auth_test()["user_id"]
    assert self_user_id is not None
    matches = re.findall(user_pattern, command["text"])
    if not has_ping_manager_perm(channel_id, user_id):
        respond(":tw_warning: You must be a ping manager to remove pingers.")
        return
    if len(matches) != 1:
        respond(":tw_warning: Please mention exactly one user to remove as a pinger.")
        return
    remove_pinger_id = matches[0]
    with db_connect(db_url) as db:
        if not has_ping_perm(channel_id, remove_pinger_id):
            respond(f":tw_warning: <@{remove_pinger_id}> is not a pinger.")
            return
        if channel_creator_of(channel_id) == remove_pinger_id:
            respond(f":tw_warning: You cannot remove the channel creator <@{remove_pinger_id}> as a pinger.")
            return
        db.execute(
            "DELETE FROM pingers WHERE chan_id = ?channel_id? AND user_id = ?user_id?",
            param={"channel_id": channel_id, "user_id": remove_pinger_id}
        )
    respond(f":tw_white_check_mark: Removed <@{remove_pinger_id}> as a pinger.")
    logger.info("In /oiac-remove-pinger, user %s removed pinger %s for channel %s", user_id, remove_pinger_id, channel_id)

@app.command("/oiac-list-pingers")
@wrapper
def handle_oiac_list_pingers(ack, body, command, respond):
    ack()
    user_id = body["user_id"]
    channel_id = body["channel_id"]
    self_user_id = client.auth_test()["user_id"]
    assert self_user_id is not None
    with db_connect(db_url) as db:
        pingers = db.query(
            "SELECT chan_id, user_id FROM pingers WHERE chan_id = ?channel_id?",
            param={"channel_id": channel_id},
            model=ChanUserRel
        )
        pingers = [x.user_id for x in pingers]
        pingers.append(channel_creator_of(channel_id))
        pingers = set(pingers)
        pinger_mentions = [f"<@{p}>" for p in pingers]
        respond(":tw_information_source: Pingers for this channel:\n" + "\n".join(pinger_mentions))

@app.command("/oiac-add-manager")
@wrapper
def handle_oiac_add_manager(ack, body, command, respond):
    ack()
    user_id = body["user_id"]
    channel_id = body["channel_id"]
    self_user_id = client.auth_test()["user_id"]
    assert self_user_id is not None
    matches = re.findall(user_pattern, command["text"])
    if not has_ping_manager_perm(channel_id, user_id):
        respond(":tw_warning: You must be a ping manager to add ping managers.")
        return
    if len(matches) != 1:
        respond(":tw_warning: Please mention exactly one user to add as a ping manager.")
        return
    new_manager_id = matches[0]
    with db_connect(db_url) as db:
        if has_ping_manager_perm(channel_id, new_manager_id):
            respond(f":tw_warning: <@{new_manager_id}> is already a ping manager.")
            return
        db.execute(
            "INSERT INTO ping_managers (chan_id, user_id) VALUES (?channel_id?, ?user_id?)",
            param={"channel_id": channel_id, "user_id": new_manager_id}
        )
    respond(f":tw_white_check_mark: Added <@{new_manager_id}> as a ping manager.")
    logger.info("In /oiac-add-manager, user %s added ping manager %s for channel %s", user_id, new_manager_id, channel_id)

@app.command("/oiac-remove-manager")
@wrapper
def handle_oiac_remove_manager(ack, body, command, respond):
    ack()
    user_id = body["user_id"]
    channel_id = body["channel_id"]
    self_user_id = client.auth_test()["user_id"]
    assert self_user_id is not None
    matches = re.findall(user_pattern, command["text"])
    if not has_ping_manager_perm(channel_id, user_id):
        respond(":tw_warning: You must be a ping manager to remove ping managers.")
        return
    if len(matches) != 1:
        respond(":tw_warning: Please mention exactly one user to remove as a ping manager.")
        return
    remove_manager_id = matches[0]
    with db_connect(db_url) as db:
        if not has_ping_manager_perm(channel_id, remove_manager_id):
            respond(f":tw_warning: <@{remove_manager_id}> is not a ping manager.")
            return
        if channel_creator_of(channel_id) == remove_manager_id:
            respond(f":tw_warning: You cannot remove the channel creator <@{remove_manager_id}> as a ping manager.")
            return
        db.execute(
            "DELETE FROM ping_managers WHERE chan_id = ?channel_id? AND user_id = ?user_id?",
            param={"channel_id": channel_id, "user_id": remove_manager_id}
        )
    respond(f":tw_white_check_mark: Removed <@{remove_manager_id}> as a ping manager.")
    logger.info("In /oiac-remove-manager, user %s removed ping manager %s for channel %s", user_id, remove_manager_id, channel_id)

@app.command("/oiac-list-managers")
@wrapper
def handle_oiac_list_managers(ack, body, command, respond):
    ack()
    user_id = body["user_id"]
    channel_id = body["channel_id"]
    self_user_id = client.auth_test()["user_id"]
    assert self_user_id is not None
    with db_connect(db_url) as db:
        managers = db.query(
            "SELECT chan_id, user_id FROM ping_managers WHERE chan_id = ?channel_id?",
            param={"channel_id": channel_id},
            model=ChanUserRel
        )
        managers = [x.user_id for x in managers]
        managers.append(channel_creator_of(channel_id))
        managers = set(managers)
        manager_mentions = [f"<@{p}>" for p in managers]
        respond(":tw_information_source: Ping managers for this channel:\n" + "\n".join(manager_mentions))

def main():
    if not check_postgres(db_url):
        logger.critical("Cannot connect to PostgreSQL database. Exiting.")
        return
    handler = SocketModeHandler(app, os.getenv("SLACK_APP_TOKEN"))
    logger.info("Starting oiac bot...")
    handler.start()

if __name__ == "__main__":
    main()
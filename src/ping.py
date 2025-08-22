from slack_bolt import App

def has_perms(
    app: App,
    channel_id: str,
    user_id: str
) -> bool:
    try:
        info = app.client.conversations_info(
            channel=channel_id
        )
    except:
        return False
    channel = info['channel']
    assert channel is not None
    if not channel['is_member']:
        act = app.client.conversations_join(
            channel=channel_id
        )
        assert act['ok']
    members_req = app.client.conversations_members(
        channel=channel_id
    )
    assert members_req['ok']
    members = members_req['members']
    assert members is not None
    return user_id in members

def ping(
    app: App,
    channel_id: str,
    user_id: str,
    text: str
) -> bool:
    if not has_perms(app, channel_id, user_id):
        return False
    app.client.chat_postMessage(
        channel="C09BYASLGNM",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"<!channel> {text}",
                },
            },
        ],
    )
    return True
from slack_bolt import App

def ping(
    app: App,
    channel_id: str,
    text: str
) -> bool:
    # this is a nuclear weapon
    # so we gotta be safe
    # by adding a safety mechanism

    info = app.client.conversations_info(
        channel=channel_id
    )
    channel = info["channel"]
    assert channel is not None
    if not channel.get("is_private", False):
        return False
    
    # end of safety mechanism

    app.client.chat_postMessage(
        channel=channel_id,
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"<!channel> {text}",
                },
            },
        ],
        text=text,
    )
    return True
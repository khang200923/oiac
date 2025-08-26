# oiac
A Slack bot for **opt-in** @channel Slack pings.

There's a common problem on Hack Club Slack: [at-channel](https://github.com/SkyfallWasTaken/at-channel) pings are disruptive, while an alternative like opt-in group pings are easily exploited, since people talking on threads with group pings will ping them again.
![image of group ping and peeps being annoying on slack](example.png)

Since @channel pings don't have this ping-on-reply feature, oiac uses @channel pings on opted-in users only, by sending @channel in separate channels. This solves both problems at once.

## Commands

- `/oiac` - Ping opted-in users using @channel
- `/optin` - Opt-in to oiac pings on this channel
- `/optout` - Opt-out of oiac pings on this channel
- `/oiac-on [ping channel name]` - Turns oiac on for this channel
- `/oiac-off` - Turns oiac off for this channel

- `/oiac-add-pinger [user]` - Add an oiac pinger
- `/oiac-remove-pinger [user]` - Remove an oiac pinger
- `/oiac-list-pingers` - List all oiac pingers in this channel
- `/oiac-add-manager [user]` - Add an oiac manager
- `/oiac-remove-manager [user]` - Remove an oiac manager
- `/oiac-list-managers` - List all oiac managers in this channel

## Setup

### Prerequisites

- Python 3.8+
- A Slack workspace

### Installation

1. Clone this repository

```bash
git clone https://github.com/khang200923/oiac
cd oiac
```

2. Create a Slack app with this manifest

```json
{
    "display_information": {
        "name": "oiac"
    },
    "features": {
        "bot_user": {
            "display_name": "oiac",
            "always_online": false
        },
        "slash_commands": [
            {
                "command": "/optin",
                "description": "Opt-in to oiac pings on this channel",
                "should_escape": false
            },
            {
                "command": "/optout",
                "description": "Opt-out of oiac pings on this channel",
                "should_escape": false
            },
            {
                "command": "/oiac-on",
                "description": "Turns oiac on for this channel",
                "usage_hint": "[ping channel name]",
                "should_escape": true
            },
            {
                "command": "/oiac-off",
                "description": "Turns oiac off for this channel",
                "should_escape": false
            },
            {
                "command": "/oiac",
                "description": "Ping opted-in users using @channel",
                "should_escape": false
            },
            {
                "command": "/oiac-add-pinger",
                "description": "Give a user perm to oiac ping",
                "usage_hint": "[user]",
                "should_escape": true
            },
            {
                "command": "/oiac-remove-pinger",
                "description": "Remove a oiac pinger ",
                "usage_hint": "[user]",
                "should_escape": true
            },
            {
                "command": "/oiac-list-pingers",
                "description": "List all oiac pingers in this channel",
                "should_escape": false
            },
            {
                "command": "/oiac-add-manager",
                "description": "Add an oiac manager",
                "usage_hint": "[user]",
                "should_escape": true
            },
            {
                "command": "/oiac-remove-manager",
                "description": "Remove an oiac manager",
                "usage_hint": "[user]",
                "should_escape": true
            },
            {
                "command": "/oiac-list-managers",
                "description": "List all oiac managers in this channel",
                "should_escape": true
            }
        ]
    },
    "oauth_config": {
        "scopes": {
            "user": [
                "admin.roles:read",
                "channels:write",
                "groups:write"
            ],
            "bot": [
                "channels:read",
                "channels:write.invites",
                "chat:write",
                "chat:write.customize",
                "chat:write.public",
                "commands",
                "groups:read",
                "groups:write",
                "im:read",
                "mpim:read",
                "users:read",
                "team:read"
            ]
        }
    },
    "settings": {
        "interactivity": {
            "is_enabled": true
        },
        "org_deploy_enabled": false,
        "socket_mode_enabled": true,
        "token_rotation_enabled": false
    }
}
```

3. Install dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

4. Create a `.env` file

```ini
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
DATABASE_URL=...
OWNER_ID=U...
LOG_FILE=...
```

5. Initialize and run the bot

```bash
bash init.sh
bash run.sh
```
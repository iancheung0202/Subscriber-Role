# Subscriber Role

[![Website](https://img.shields.io/badge/Website-af4875)](https://subscriber.iancheung.dev)
[![Discord](https://img.shields.io/badge/Invite%20Discord%20Bot-5865F2)](https://discord.com/oauth2/authorize?client_id=1490081882140840016)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)

> A Discord bot that verifies YouTube channel subscriptions and automatically assigns a role to subscribers. That's it.

## Overview

**Subscriber Role** is built specifically for any YouTube creator's Discord server. When a server member runs `/verify`, the bot authenticates them through Google OAuth2, checks their YouTube subscription status via the YouTube Data API, and automatically grants or revokes the configured "Subscriber" role, all without any manual work from the server admin.

1. **Admin setup** - A server admin runs `/setup` (requires Administrator permission), specifying the YouTube channel ID and the Discord role to assign to verified subscribers.
2. **Member verification** - A member runs `/verify`, which opens a Google OAuth2 flow to securely link their YouTube account.
3. **Subscription check** - The bot queries the YouTube Data API to confirm the member is subscribed to the configured channel.
4. **Role assignment** - If subscribed, the bot immediately grants the configured role. Roles are automatically removed if a subscription is later revoked.

| Command | Permission | Description |
|---|---|---|
| `/setup` | Administrator | Configure the YouTube channel and subscriber role for this server |
| `/verify` | Everyone | Link your YouTube account and verify your subscription to earn the role |
| `/premium` | Administrator | Enable premium for this server |

The bot is free for one YouTube channel per server. Premium adds:

- Up to 5 YouTube channels per server
- A custom message sent to members when they verify
- A custom message sent to members when they lose the role
- Priority and more frequent subscription checks
- Tier roles that reward long-time subscribers

## Tech Stack

| File | Purpose |
|---|---|
| `main.py` | Starts the bot and API server |
| `bot.py` | Discord client, events and slash commands |
| `views.py` | Setup and verification screens |
| `sync.py` | Background sync that keeps roles up to date |
| `api.py` | Web server handling the Google OAuth2 callback |
| `database.py` | Database interactions (tokens, server configs) |
| `utils.py` | Shared helpers (YouTube API calls, role management) |
| `pages/` | Website pages (home, privacy policy, terms of service) |
| `tests/` | Tests for the background sync |

## Self-Hosting

This project is licensed under the **AGPL-3.0**, which means you are free to fork and self-host this bot. However, the setup involves multiple external services (Discord, Google Cloud, YouTube Data API, a database, and a publicly accessible server) and is non-trivial. **No support will be provided for self-hosting.** You're on your own.

### What you need

- A server with [Docker](https://docs.docker.com/engine/install/) and a domain that serves port `4700` over HTTPS
- A PostgreSQL database. The bot creates its own tables on first start
- A [Discord application](https://discord.com/developers/applications) with a bot token
- A [Google Cloud project](https://console.cloud.google.com/) with the YouTube Data API v3 enabled, an API key, and an OAuth client whose redirect URI is `https://your-domain/callback` with the `youtube.readonly` scope

### Run it

```
git clone https://github.com/iancheung0202/Subscriber-Role.git
cd Subscriber-Role
cp .env.example .env
docker compose up -d --build
```

Fill in `.env` before the last command. The container uses the host network, so `DATABASE_URL` can point at a database on the same machine and the web server is reachable on port `4700`. It restarts on its own after a crash or reboot.

| Task | Command |
|---|---|
| View logs | `docker compose logs -f` |
| Restart | `docker compose restart` |
| Update | `git pull && docker compose up -d --build` |
| Stop | `docker compose down` |

### Configuration

Every setting lives in `.env`.

| Key | Purpose |
|---|---|
| `DISCORD_TOKEN` | Bot token of your Discord application |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Google OAuth client used when members link their YouTube account |
| `GOOGLE_API_KEY` | Google API key used to look up YouTube channel names |
| `DATABASE_URL` | PostgreSQL connection string |
| `OAUTH_REDIRECT_URI` | `https://your-domain/callback`, matching the Google OAuth client |
| `ALLOWED_HOST`, `CORS_ORIGIN` | Domain and origin the web server answers to |
| `STATE_SECRET` | Random string that signs verification links |
| `TOKEN_ENCRYPTION_KEY` | Key that encrypts stored tokens. Generate it with `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `OWNER_IDS` | Comma-separated Discord user IDs treated as bot owners |
| `DISCORD_PREMIUM_SKU_ID` | Discord SKU that unlocks premium. Leave empty to run without premium |
| `GUILD_LOG_CHANNEL_ID`, `COMMAND_LOG_CHANNEL_ID`, `PREMIUM_LOG_CHANNEL_ID`, `SYNC_LOG_CHANNEL_ID` | Discord channels that receive owner logs. Leave empty to turn a log off |
| `SYNC_INTERVAL_HOURS` | Hours between background syncs |
| `SYNC_RECHECK_HOURS` | Hours before a subscribed member is checked again |
| `SYNC_UNSUBSCRIBED_RECHECK_HOURS` | Hours before a member who is not subscribed is checked again |
| `SYNC_BATCH_SIZE` | Members checked at the same time |
| `SYNC_DAILY_LIMIT` | YouTube quota units the sync may use per day. Leave empty for no limit |
| `TOKEN_RETENTION_DAYS` | Days a stored token is kept after its last check |
| `CHANNEL_NAME_REFRESH_HOURS` | Hours a YouTube channel name is cached |
| `BLOCKED_USER_AGENTS`, `ALLOWED_CRAWLERS` | Comma-separated user agents the website blocks or always allows |
| `SITE_NOTICE` | Optional notice shown on the website and in `/verify` |

### Development

```
pip install -r requirements.txt pytest pre-commit
pytest
pre-commit run --all-files
```

## Privacy & Data

Subscriber Role only accesses the minimum data required to function. The bot does **not** access your email, watch history, private content, or any other Google data. You can revoke access at any time from your [Google Account Permissions](https://myaccount.google.com/permissions) page.

See the full [Privacy Policy](https://subscriber.iancheung.dev/privacy) and [Terms of Service](https://subscriber.iancheung.dev/terms) for details.

*Copyright (c) 2026 Ian Cheung. See [LICENSE](LICENSE) for details.*

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

## Tech Stack

| File | Purpose |
|---|---|
| `main.py` | Starts the bot and API server |
| `bot.py` | Discord bot logic and slash command handlers |
| `api.py` | Web server handling the Google OAuth2 callback |
| `database.py` | Database interactions (tokens, server configs) |
| `utils.py` | Shared helpers (YouTube API calls, role management) |

## Self-Hosting
 
This project is licensed under the **AGPL-3.0**, which means you are free to fork and self-host this bot. However, the setup involves multiple external services (Discord, Google Cloud, YouTube Data API, a database, and a publicly accessible server) and is non-trivial. **No support will be provided for self-hosting.** You're on your own.

## Privacy & Data

Subscriber Role only accesses the minimum data required to function. The bot does **not** access your email, watch history, private content, or any other Google data. You can revoke access at any time from your [Google Account Permissions](https://myaccount.google.com/permissions) page.

See the full [Privacy Policy](https://subscriber.iancheung.dev/privacy) and [Terms of Service](https://subscriber.iancheung.dev/terms) for details.

*Copyright (c) 2026 Ian Cheung. See [LICENSE](LICENSE) for details.*
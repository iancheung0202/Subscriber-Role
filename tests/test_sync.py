import asyncio
import datetime
import types

import discord
import pytest

import sync

GUILD_ID, SERVER_ID, CHANNEL_ID = 1, 10, "UC123"
SNIPPET = {"channelId": "UCmember", "publishedAt": "2024-01-01T00:00:00Z"}


class Role:
    def __init__(self, role_id):
        self.id, self.mention = role_id, f"<@&{role_id}>"


class Member:
    def __init__(self, member_id, roles=(), forbidden=False):
        self.id, self.roles, self.forbidden, self.dms = (
            member_id,
            list(roles),
            forbidden,
            [],
        )

    async def _change(self, change, roles):
        if self.forbidden:
            raise discord.errors.Forbidden(
                types.SimpleNamespace(status=403, reason=""), ""
            )
        for role in roles:
            change(role)

    async def add_roles(self, *roles):
        await self._change(self.roles.append, roles)

    async def remove_roles(self, *roles):
        await self._change(self.roles.remove, roles)

    async def send(self, embed):
        self.dms.append(embed.description)


class Guild:
    name = "Guild"

    def __init__(self, members=()):
        self.members = {member.id: member for member in members}

    async def fetch_member(self, member_id):
        if member_id not in self.members:
            raise discord.errors.NotFound(
                types.SimpleNamespace(status=404, reason=""), ""
            )
        return self.members[member_id]


class World:
    def __init__(self, monkeypatch, check=SNIPPET):
        self.quota, self.statuses, self.cleared, self.logs, self.claimed = (
            0,
            [],
            [],
            [],
            [],
        )
        self.check = check
        patches = {
            "add_quota_usage": self.add_quota,
            "decrypt_token": lambda token: token,
            "check_subscription": lambda token, channel, discord_id: self.check,
            "update_subscription_status": self.update_status,
            "clear_user_refresh_token": self.clear_token,
            "claim_account_hash": self.claim,
            "log_action": self.log,
        }
        for name, patch in patches.items():
            monkeypatch.setattr(sync, name, patch)

    async def add_quota(self, units=1):
        self.quota += units

    async def update_status(self, user_id, server_id, channel, subscribed):
        self.statuses.append((user_id, subscribed))

    async def clear_token(self, user_id):
        self.cleared.append(user_id)

    async def claim(self, user_id, guild_id, account_hash):
        self.claimed.append(user_id)

    async def log(self, guild_id, message, color=None, server_id=None):
        self.logs.append(message)


def new_stats():
    return {"checked": 0, "removed": 0, "added": 0, "failed": 0}


def row(discord_id=5, token="token", account_hash="hash", **extra):
    return {
        "user_id": 50,
        "discord_id": discord_id,
        "refresh_token": token,
        "yt_account_hash": account_hash,
        **extra,
    }


def target(guild, role, **config):
    config = {
        "id": SERVER_ID,
        "guild_id": GUILD_ID,
        "yt_channel_id": CHANNEL_ID,
        "stack_tiers": False,
        **config,
    }
    return {
        "config": config,
        "guild": guild,
        "role": role,
        "channel_name": "Channel",
        "tiers": [],
    }


def run(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture
def role():
    return Role(7)


def test_subscribed_member_with_role_is_kept(monkeypatch, role):
    world, member, stats = World(monkeypatch), Member(5, [role]), new_stats()
    run(sync.sync_member(row(), target(Guild([member]), role), stats))
    assert (
        member.roles == [role] and world.statuses == [(50, True)] and world.quota == 1
    )
    assert (
        stats == {"checked": 1, "removed": 0, "added": 0, "failed": 0}
        and not world.logs
    )


def test_subscribed_member_without_role_gets_it(monkeypatch, role):
    world, member, stats = World(monkeypatch), Member(5), new_stats()
    run(sync.sync_member(row(account_hash=None), target(Guild([member]), role), stats))
    assert member.roles == [role] and stats["added"] == 1 and len(world.logs) == 1
    assert world.claimed == [50]


def test_unsubscribed_member_loses_role_and_is_told(monkeypatch, role):
    world, member, stats = (
        World(monkeypatch, check=False),
        Member(5, [role]),
        new_stats(),
    )
    run(
        sync.sync_member(
            row(), target(Guild([member]), role, unsubscribe_dm_content="Bye"), stats
        )
    )
    assert member.roles == [] and stats["removed"] == 1 and member.dms == ["Bye"]
    assert world.statuses == [(50, False)] and len(world.logs) == 1


def test_failed_check_keeps_role(monkeypatch, role):
    world, member, stats = (
        World(monkeypatch, check=None),
        Member(5, [role]),
        new_stats(),
    )
    run(sync.sync_member(row(), target(Guild([member]), role), stats))
    assert member.roles == [role] and world.statuses == []
    assert stats == {"checked": 0, "removed": 0, "added": 0, "failed": 1}


def test_revoked_access_clears_token_and_removes_role(monkeypatch, role):
    world, member, stats = (
        World(monkeypatch, check=sync.REVOKED),
        Member(5, [role]),
        new_stats(),
    )
    run(sync.sync_member(row(), target(Guild([member]), role), stats))
    assert world.cleared == [50] and member.roles == [] and stats["removed"] == 1


def test_member_without_token_is_skipped(monkeypatch, role):
    world, member, stats = World(monkeypatch), Member(5), new_stats()
    run(sync.sync_member(row(token=None), target(Guild([member]), role), stats))
    assert world.quota == 0 and member.roles == [] and stats["checked"] == 0


def test_member_who_left_costs_no_quota_and_loses_token(monkeypatch, role):
    world, stats = World(monkeypatch), new_stats()
    run(sync.sync_member(row(), target(Guild(), role), stats))
    assert world.quota == 0 and world.statuses == [] and world.cleared == [50]
    assert stats["checked"] == 0


def test_missing_permission_does_not_stop_the_sync(monkeypatch, role):
    world, member, stats = (
        World(monkeypatch, check=False),
        Member(5, [role], forbidden=True),
        new_stats(),
    )
    run(sync.sync_member(row(), target(Guild([member]), role), stats))
    assert member.roles == [role] and stats["removed"] == 0 and stats["checked"] == 1
    assert len(world.logs) == 1


class Pool:
    def __init__(self, rows):
        self.rows = rows

    def acquire(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *error):
        return False

    async def fetch(self, query, *args):
        return self.rows


def sync_rows(monkeypatch, rows, premium=(), limit=0, used=0, results=None):
    calls, cleared = [], []
    guilds = {
        1: types.SimpleNamespace(get_role=lambda role_id: Role(role_id)),
        2: types.SimpleNamespace(get_role=lambda role_id: Role(role_id)),
    }

    async def configs():
        return [
            {
                "id": guild_id * 10,
                "guild_id": guild_id,
                "role_id": 7,
                "yt_channel_id": CHANNEL_ID,
            }
            for guild_id in guilds
        ]

    async def member(row, target, stats):
        calls.append(row["discord_id"])
        outcome = (results or {}).get(row["discord_id"])
        if outcome:
            raise outcome
        stats["checked"] += 1

    async def value(result):
        return result

    async def no_sleep(seconds):
        pass

    monkeypatch.setattr(sync, "SYNC_DAILY_LIMIT", limit)
    monkeypatch.setattr(sync.bot, "get_guild", guilds.get)
    monkeypatch.setattr(sync, "get_all_server_configs", configs)
    monkeypatch.setattr(sync, "get_premium_guild_ids", lambda: value(set(premium)))
    monkeypatch.setattr(sync, "get_tiers", lambda: value([]))
    monkeypatch.setattr(sync, "get_pool", lambda: value(Pool(rows)))
    monkeypatch.setattr(sync, "get_quota_usage", lambda: value(used + len(calls)))
    monkeypatch.setattr(
        sync, "get_youtube_channel_name", lambda channel: value("Channel")
    )
    monkeypatch.setattr(
        sync, "clear_stale_refresh_tokens", lambda before: value(cleared.append(before))
    )
    monkeypatch.setattr(sync, "sync_member", member)
    monkeypatch.setattr(sync.asyncio, "sleep", no_sleep)
    stats = asyncio.run(sync.run_sync())
    return calls, stats, cleared


def due(discord_id, guild_id=1, hours_ago=None, subscribed=True):
    checked = (
        datetime.datetime.now() - datetime.timedelta(hours=hours_ago)
        if hours_ago
        else None
    )
    return {
        "server_id": guild_id * 10,
        "guild_id": guild_id,
        "user_id": discord_id,
        "discord_id": discord_id,
        "refresh_token": "token",
        "yt_account_hash": None,
        "is_subscribed": subscribed,
        "last_checked": checked,
    }


def test_recently_checked_members_wait_unless_premium(monkeypatch):
    rows = [
        due(1),
        due(2, hours_ago=30),
        due(3, hours_ago=10),
        due(4, guild_id=2, hours_ago=10),
    ]
    calls, stats, cleared = sync_rows(monkeypatch, rows, premium=[2])
    assert calls == [4, 1, 2] and stats["checked"] == 3 and stats["remaining"] == 0
    assert len(cleared) == 1


def test_daily_limit_pauses_the_sync(monkeypatch):
    calls, stats, cleared = sync_rows(
        monkeypatch, [due(1), due(2), due(3), due(4)], limit=3, used=0
    )
    assert (
        calls == [1, 2]
        and stats["limit_hit"]
        and stats["remaining"] == 2
        and not cleared
    )


def test_exhausted_quota_stops_the_sync(monkeypatch):
    rows = [due(1), due(2), due(3), due(4)]
    calls, stats, cleared = sync_rows(
        monkeypatch, rows, results={2: sync.QuotaExhausted("quota")}
    )
    assert (
        calls == [1, 2]
        and stats["quota_hit"]
        and stats["remaining"] == 3
        and not cleared
    )


def test_one_failing_member_does_not_stop_the_rest(monkeypatch):
    calls, stats, cleared = sync_rows(
        monkeypatch, [due(1), due(2), due(3)], results={1: RuntimeError("boom")}
    )
    assert calls == [1, 2, 3] and stats["failed"] == 1 and stats["checked"] == 2


def test_unsubscribed_members_are_rechecked_weekly(monkeypatch):
    rows = [
        due(1, hours_ago=30, subscribed=False),
        due(2, hours_ago=200, subscribed=False),
        due(3, guild_id=2, hours_ago=30, subscribed=False),
    ]
    calls, stats, cleared = sync_rows(monkeypatch, rows, premium=[2])
    assert calls == [3, 2]

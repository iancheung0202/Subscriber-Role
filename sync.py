import asyncio
import datetime
import logging
import os

import discord
from discord.ext import tasks
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from bot import bot, log_action, owner_log
from database import (
    add_quota_usage,
    claim_account_hash,
    clear_stale_refresh_tokens,
    clear_user_refresh_token,
    decrypt_token,
    get_all_server_configs,
    get_last_sync,
    get_pool,
    get_quota_usage,
    get_tiers,
    hash_account,
    set_last_sync,
    update_subscription_status,
)
from utils import (
    CHECK,
    CROSS,
    NEUTRAL,
    SKU_ID,
    WARN,
    get_youtube_channel_name,
)

SYNC_INTERVAL_HOURS = int(os.environ["SYNC_INTERVAL_HOURS"])
SYNC_RECHECK_HOURS = int(os.environ["SYNC_RECHECK_HOURS"])
SYNC_UNSUBSCRIBED_RECHECK_HOURS = int(os.environ["SYNC_UNSUBSCRIBED_RECHECK_HOURS"])
SYNC_BATCH_SIZE = int(os.environ["SYNC_BATCH_SIZE"])
SYNC_DAILY_LIMIT = int(os.environ.get("SYNC_DAILY_LIMIT") or 0)
TOKEN_RETENTION_DAYS = int(os.environ["TOKEN_RETENTION_DAYS"])
QUOTA_REASONS = ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded")


REVOKED = {}


class QuotaExhausted(Exception):
    pass


def check_subscription(refresh_token: str, yt_channel_id: str, discord_id: int):
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
    )
    try:
        youtube = build("youtube", "v3", credentials=creds)
        req = youtube.subscriptions().list(
            part="snippet", mine=True, forChannelId=yt_channel_id
        )
        res = req.execute()
        items = res.get("items", [])
        return items[0]["snippet"] if items else False
    except RefreshError as e:
        if "invalid_grant" in str(e):
            return REVOKED
        logging.error(f"Could not refresh token for {discord_id}: {e}")
        return None
    except HttpError as e:
        if any(reason in str(e) for reason in QUOTA_REASONS):
            raise QuotaExhausted(str(e))
        logging.error(f"Error for {discord_id}: {e}")
        return None
    except Exception as e:
        logging.error(f"Error for {discord_id}: {e}")
        return None


async def sync_tier_roles(member, guild, config, tiers, channel_name, snippet):
    roles = [
        (tier["days"], guild.get_role(tier["role_id"]))
        for tier in tiers
        if guild.get_role(tier["role_id"])
    ]
    earned = []
    if snippet and snippet.get("publishedAt"):
        since = datetime.datetime.fromisoformat(
            snippet["publishedAt"].replace("Z", "+00:00")
        )
        age = (datetime.datetime.now(datetime.timezone.utc) - since).days
        earned = [role for days, role in roles if age >= days]
    wanted = earned if config["stack_tiers"] else earned[-1:]
    added = [role for role in wanted if role not in member.roles]
    removed = [role for _, role in roles if role in member.roles and role not in wanted]
    try:
        if added:
            await member.add_roles(*added)
            await log_action(
                config["guild_id"],
                f"{CHECK} Added {' '.join(role.mention for role in added)} to <@{member.id}> for how long they have been subscribed to [{channel_name}](https://www.youtube.com/channel/{config['yt_channel_id']}).",
                discord.Color.green(),
                server_id=config["id"],
            )
        if removed:
            await member.remove_roles(*removed)
    except Exception as e:
        logging.error(f"Error syncing tier roles for {member.id}: {e}")


async def set_role(member, target: dict, is_subscribed: bool, stats: dict):
    config = target["config"]
    role = target["role"]
    channel = f"[{target['channel_name']}](https://www.youtube.com/channel/{config['yt_channel_id']})"
    if is_subscribed:
        change, action, stat = member.add_roles, "add", "added"
        message = f"{CHECK} Added {role.mention} to <@{member.id}> because they subscribed to {channel}."
        failure = f"{CROSS} Attempted to add {role.mention} to <@{member.id}> for {channel} but bot lacks permission in role hierarchy."
        color = discord.Color.green()
    else:
        change, action, stat = member.remove_roles, "remove", "removed"
        message = f"{NEUTRAL} Removed {role.mention} from <@{member.id}> because they are no longer subscribed to {channel}."
        failure = f"{CROSS} Attempted to remove {role.mention} from <@{member.id}> for {channel} but bot lacks permission in role hierarchy."
        color = discord.Color.red()
    try:
        await change(role)
        stats[stat] += 1
    except discord.errors.Forbidden:
        logging.error(f"Failed to {action} role for {member.id}: Bot lacks permission.")
        message, color = failure, discord.Color.orange()
    else:
        if (
            not is_subscribed
            and target["premium"]
            and config.get("unsubscribe_dm_content")
        ):
            try:
                dm_embed = discord.Embed(
                    description=config["unsubscribe_dm_content"], color=0xAF4875
                )
                dm_embed.set_footer(text=f"Sent from {target['guild'].name}")
                await member.send(embed=dm_embed)
            except Exception as e:
                logging.error(f"Error sending unsubscribe DM to {member.id}: {e}")
    try:
        await log_action(config["guild_id"], message, color, server_id=config["id"])
    except Exception as e:
        logging.error(f"Error logging role change for {member.id}: {e}")


async def sync_member(row, target: dict, stats: dict):
    config = target["config"]
    guild = target["guild"]
    role = target["role"]
    channel_name = target["channel_name"]
    server_id = config["id"]
    guild_id = config["guild_id"]
    yt_channel_id = config["yt_channel_id"]
    user_id = row["user_id"]
    discord_id = row["discord_id"]
    refresh_token = decrypt_token(row["refresh_token"])
    if not refresh_token:
        return
    try:
        member = await guild.fetch_member(discord_id)
    except discord.errors.NotFound:
        await clear_user_refresh_token(user_id)
        return
    await add_quota_usage()
    snippet = await asyncio.to_thread(
        check_subscription, refresh_token, yt_channel_id, discord_id
    )
    if snippet is None:
        stats["failed"] += 1
        return
    is_subscribed = bool(snippet)
    if snippet is REVOKED:
        await clear_user_refresh_token(user_id)
    if is_subscribed and not row["yt_account_hash"] and snippet.get("channelId"):
        claimed = await claim_account_hash(
            user_id, guild_id, hash_account(snippet["channelId"])
        )
        if not claimed and role not in member.roles:
            await clear_user_refresh_token(user_id)
            return
    if is_subscribed != (role in member.roles):
        await set_role(member, target, is_subscribed, stats)
    if target["tiers"]:
        await sync_tier_roles(
            member, guild, config, target["tiers"], channel_name, snippet
        )
    await update_subscription_status(user_id, server_id, yt_channel_id, is_subscribed)
    stats["checked"] += 1


async def get_premium_guild_ids() -> set:
    if not SKU_ID:
        return set()
    try:
        return {
            entitlement.guild_id
            async for entitlement in bot.entitlements(limit=None, exclude_ended=True)
            if entitlement.sku_id == SKU_ID and entitlement.guild_id
        }
    except Exception as e:
        logging.error(f"Error fetching premium guilds: {e}")
        return set()


async def run_sync() -> dict:
    stats = {
        "checked": 0,
        "removed": 0,
        "added": 0,
        "failed": 0,
        "remaining": 0,
        "quota_hit": False,
        "limit_hit": False,
    }
    targets = {}
    for config in await get_all_server_configs():
        guild = bot.get_guild(config["guild_id"])
        if not guild:
            logging.error(f"Guild {config['guild_id']} not found, skipping...")
            continue
        role = guild.get_role(config["role_id"])
        if not role:
            logging.info(
                f"Role {config['role_id']} not found in guild {config['guild_id']}, skipping..."
            )
            continue
        targets[config["id"]] = {"config": config, "guild": guild, "role": role}
    premium_guilds = await get_premium_guild_ids()
    tiers = await get_tiers()
    for server_id, target in targets.items():
        target["premium"] = target["config"]["guild_id"] in premium_guilds
        target["tiers"] = [
            tier
            for tier in tiers
            if tier["server_id"] == server_id and target["premium"]
        ]
    now = datetime.datetime.now()
    slack = datetime.timedelta(hours=SYNC_INTERVAL_HOURS) / 2
    pool = await get_pool()
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            "SELECT s.id AS server_id, s.guild_id, u.id AS user_id, u.discord_id, u.refresh_token, u.yt_account_hash, sub.is_subscribed, sub.last_checked FROM servers s JOIN users u ON u.guild_id = s.guild_id LEFT JOIN subscriptions sub ON sub.user_id = u.id AND sub.server_id = s.id WHERE u.refresh_token IS NOT NULL AND (sub.last_checked IS NULL OR sub.last_checked < $1) ORDER BY sub.last_checked ASC NULLS FIRST, u.id",
            now - slack,
        )
    stale = now - datetime.timedelta(hours=SYNC_RECHECK_HOURS) + slack
    stale_unsubscribed = (
        now - datetime.timedelta(hours=SYNC_UNSUBSCRIBED_RECHECK_HOURS) + slack
    )
    rows = [
        row
        for row in rows
        if row["server_id"] in targets
        and (
            row["guild_id"] in premium_guilds
            or not row["last_checked"]
            or row["last_checked"]
            < (stale if row["is_subscribed"] else stale_unsubscribed)
        )
    ]
    rows.sort(key=lambda row: row["guild_id"] not in premium_guilds)
    stats["remaining"] = len(rows)
    for start in range(0, len(rows), SYNC_BATCH_SIZE):
        batch = rows[start : start + SYNC_BATCH_SIZE]
        if SYNC_DAILY_LIMIT and await get_quota_usage() + len(batch) > SYNC_DAILY_LIMIT:
            stats["limit_hit"] = True
            break
        for row in batch:
            target = targets[row["server_id"]]
            if "channel_name" not in target:
                target["channel_name"] = await get_youtube_channel_name(
                    target["config"]["yt_channel_id"]
                )
        results = await asyncio.gather(
            *[sync_member(row, targets[row["server_id"]], stats) for row in batch],
            return_exceptions=True,
        )
        stats["remaining"] -= len(batch)
        for row, result in zip(batch, results):
            if isinstance(result, QuotaExhausted):
                stats["quota_hit"] = True
                stats["remaining"] += 1
            elif isinstance(result, Exception):
                stats["failed"] += 1
                logging.error(f"Error syncing {row['discord_id']}: {result}")
        if stats["quota_hit"]:
            logging.info("YouTube quota exhausted, stopping sync until the next run.")
            break
        await asyncio.sleep(1)
    await clear_stale_refresh_tokens(
        now - datetime.timedelta(days=TOKEN_RETENTION_DAYS)
    )
    return stats


@tasks.loop(hours=SYNC_INTERVAL_HOURS)
async def sync_roles():
    logging.info("Running background sync task...")
    try:
        await set_last_sync(datetime.datetime.now())
        stats = await run_sync()
    except Exception as e:
        logging.exception(e)
        await owner_log(
            "SYNC_LOG_CHANNEL_ID",
            f"{CROSS} Sync failed: {e}",
            discord.Color.red(),
        )
        return
    summary = f"Checked {stats['checked']:,} members, removed {stats['removed']:,} roles, added {stats['added']:,} roles, {stats['failed']:,} checks failed, {stats['remaining']:,} left for the next run. {await get_quota_usage():,} quota units used today."
    if stats["limit_hit"]:
        await owner_log(
            "SYNC_LOG_CHANNEL_ID",
            f"{WARN} Sync paused at the daily limit. {summary}",
            discord.Color.orange(),
        )
    elif stats["quota_hit"]:
        await owner_log(
            "SYNC_LOG_CHANNEL_ID",
            f"{WARN} Sync stopped because the YouTube quota ran out. {summary}",
            discord.Color.orange(),
        )
    else:
        await owner_log("SYNC_LOG_CHANNEL_ID", f"{CHECK} Sync completed. {summary}")
    logging.info(f"Background sync task completed. {summary}")


@sync_roles.before_loop
async def wait_for_schedule():
    now = datetime.datetime.now()
    last_run = await get_last_sync()
    if not last_run:
        last_run = now
        await set_last_sync(now)
    next_run = last_run + datetime.timedelta(hours=SYNC_INTERVAL_HOURS)
    if next_run > now:
        await asyncio.sleep((next_run - now).total_seconds())


@bot.listen()
async def on_ready():
    if not sync_roles.is_running():
        sync_roles.start()

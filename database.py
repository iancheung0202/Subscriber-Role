import asyncio
import datetime
import hashlib
import hmac
import logging
import os
import zoneinfo

import asyncpg
from cryptography.fernet import Fernet, InvalidToken

pool = None
_init_lock = None
_fernet = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = os.environ.get("TOKEN_ENCRYPTION_KEY")
        if not key:
            raise RuntimeError(
                "TOKEN_ENCRYPTION_KEY is not set. Generate one with: "
                'python -c "from cryptography.fernet import Fernet; logging.info(Fernet.generate_key().decode())"'
            )
        _fernet = Fernet(key.encode())
    return _fernet


def encrypt_token(token: str) -> str:
    return _get_fernet().encrypt(token.encode()).decode()


def decrypt_token(stored: str) -> str:
    if not stored:
        return stored
    try:
        return _get_fernet().decrypt(stored.encode()).decode()
    except InvalidToken:
        return stored


def hash_account(account_id: str) -> str:
    return hmac.new(
        os.environ["TOKEN_ENCRYPTION_KEY"].encode(), account_id.encode(), hashlib.sha256
    ).hexdigest()


def _is_encrypted(stored: str) -> bool:
    try:
        _get_fernet().decrypt(stored.encode())
        return True
    except InvalidToken:
        return False


async def _encrypt_existing_tokens(connection):
    rows = await connection.fetch(
        "SELECT id, refresh_token FROM users WHERE refresh_token IS NOT NULL"
    )
    migrated = 0
    for row in rows:
        if not _is_encrypted(row["refresh_token"]):
            await connection.execute(
                "UPDATE users SET refresh_token = $1 WHERE id = $2",
                encrypt_token(row["refresh_token"]),
                row["id"],
            )
            migrated += 1
    if migrated:
        logging.info(f"Encrypted {migrated} stored refresh tokens")


async def init_db():
    global pool, _init_lock
    if _init_lock is None:
        _init_lock = asyncio.Lock()
    async with _init_lock:
        if pool is not None:
            return
        _get_fernet()
        new_pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
        async with new_pool.acquire() as connection:
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS servers (id SERIAL PRIMARY KEY, guild_id BIGINT NOT NULL, yt_channel_id TEXT NOT NULL, role_id BIGINT NOT NULL, log_channel_id BIGINT, verification_dm_content TEXT, unsubscribe_dm_content TEXT)"
            )
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, guild_id BIGINT NOT NULL, discord_id BIGINT NOT NULL, refresh_token TEXT, UNIQUE(guild_id, discord_id))"
            )
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS subscriptions (user_id INTEGER NOT NULL, server_id INTEGER NOT NULL, yt_channel_id TEXT NOT NULL, is_subscribed BOOLEAN, last_checked TIMESTAMP, PRIMARY KEY (user_id, server_id), FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE, FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE)"
            )
            await connection.execute(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS yt_account_hash TEXT"
            )
            await connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS users_guild_account ON users (guild_id, yt_account_hash)"
            )
            await connection.execute(
                "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS created_at TIMESTAMP, ADD COLUMN IF NOT EXISTS changed_at TIMESTAMP"
            )
            await connection.execute(
                "ALTER TABLE servers ADD COLUMN IF NOT EXISTS stack_tiers BOOLEAN NOT NULL DEFAULT TRUE"
            )
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS tiers (server_id INTEGER NOT NULL, days INTEGER NOT NULL, role_id BIGINT NOT NULL, PRIMARY KEY (server_id, days), FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE)"
            )
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS channel_names (yt_channel_id TEXT PRIMARY KEY, name TEXT NOT NULL, updated_at TIMESTAMP NOT NULL)"
            )
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS quota_usage (day DATE PRIMARY KEY, units INTEGER NOT NULL)"
            )
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS sync_state (id BOOLEAN PRIMARY KEY DEFAULT TRUE, last_run TIMESTAMP NOT NULL)"
            )
            await _encrypt_existing_tokens(connection)
        pool = new_pool


async def get_pool():
    global pool
    if pool is None:
        await init_db()
    return pool


async def set_server_config(
    guild_id: int,
    yt_channel_id: str,
    role_id: int,
    log_channel_id: int = None,
    server_id: int = None,
    verification_dm_content: str = None,
    unsubscribe_dm_content: str = None,
):
    pool = await get_pool()
    async with pool.acquire() as connection:
        if server_id:
            await connection.execute(
                "UPDATE servers SET yt_channel_id = $1, role_id = $2, log_channel_id = $3, verification_dm_content = $4, unsubscribe_dm_content = $5 WHERE id = $6 AND guild_id = $7",
                yt_channel_id,
                role_id,
                log_channel_id,
                verification_dm_content,
                unsubscribe_dm_content,
                server_id,
                guild_id,
            )
            return server_id
        else:
            new_id = await connection.fetchval(
                "INSERT INTO servers (guild_id, yt_channel_id, role_id, log_channel_id, verification_dm_content, unsubscribe_dm_content) VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
                guild_id,
                yt_channel_id,
                role_id,
                log_channel_id,
                verification_dm_content,
                unsubscribe_dm_content,
            )
            return new_id


async def get_all_server_configs():
    pool = await get_pool()
    async with pool.acquire() as connection:
        return await connection.fetch(
            "SELECT id, guild_id, yt_channel_id, role_id, log_channel_id, verification_dm_content, unsubscribe_dm_content, stack_tiers FROM servers ORDER BY guild_id, id"
        )


async def get_user_id(guild_id: int, discord_id: int):
    pool = await get_pool()
    async with pool.acquire() as connection:
        user = await connection.fetchrow(
            "SELECT id FROM users WHERE guild_id = $1 AND discord_id = $2",
            guild_id,
            discord_id,
        )
        if user:
            return user["id"]
        return await connection.fetchval(
            "INSERT INTO users (guild_id, discord_id) VALUES ($1, $2) RETURNING id",
            guild_id,
            discord_id,
        )


async def update_user_refresh_token(user_id: int, refresh_token: str):
    pool = await get_pool()
    async with pool.acquire() as connection:
        await connection.execute(
            "UPDATE users SET refresh_token = $1 WHERE id = $2",
            encrypt_token(refresh_token),
            user_id,
        )


async def update_subscription_status(
    user_id: int, server_id: int, yt_channel_id: str, is_subscribed: bool
):
    pool = await get_pool()
    async with pool.acquire() as connection:
        await connection.execute(
            "INSERT INTO subscriptions (user_id, server_id, yt_channel_id, is_subscribed, last_checked, created_at, changed_at) VALUES ($1, $2, $3, $4, $5, $5, $5) ON CONFLICT (user_id, server_id) DO UPDATE SET changed_at = CASE WHEN subscriptions.is_subscribed IS DISTINCT FROM EXCLUDED.is_subscribed THEN EXCLUDED.last_checked ELSE subscriptions.changed_at END, is_subscribed = EXCLUDED.is_subscribed, last_checked = EXCLUDED.last_checked",
            user_id,
            server_id,
            yt_channel_id,
            is_subscribed,
            datetime.datetime.now(),
        )


async def get_server_config_by_id(server_id: int):
    pool = await get_pool()
    async with pool.acquire() as connection:
        return await connection.fetchrow(
            "SELECT id, guild_id, yt_channel_id, role_id, log_channel_id, verification_dm_content, unsubscribe_dm_content, stack_tiers FROM servers WHERE id = $1",
            server_id,
        )


async def delete_server_config(server_id: int):
    pool = await get_pool()
    async with pool.acquire() as connection:
        await connection.execute("DELETE FROM servers WHERE id = $1", server_id)


async def get_server_configs_for_guild(guild_id: int):
    pool = await get_pool()
    async with pool.acquire() as connection:
        return await connection.fetch(
            "SELECT id, guild_id, yt_channel_id, role_id, log_channel_id, verification_dm_content, unsubscribe_dm_content, stack_tiers FROM servers WHERE guild_id = $1 ORDER BY id",
            guild_id,
        )


async def get_account_holder(guild_id: int, account_hash: str, user_id: int):
    pool = await get_pool()
    async with pool.acquire() as connection:
        return await connection.fetchrow(
            "SELECT id, discord_id FROM users WHERE guild_id = $1 AND yt_account_hash = $2 AND id != $3",
            guild_id,
            account_hash,
            user_id,
        )


async def set_account_hash(user_id: int, account_hash: str = None):
    pool = await get_pool()
    async with pool.acquire() as connection:
        await connection.execute(
            "UPDATE users SET yt_account_hash = $1 WHERE id = $2", account_hash, user_id
        )


async def claim_account_hash(user_id: int, guild_id: int, account_hash: str):
    pool = await get_pool()
    async with pool.acquire() as connection:
        await connection.execute(
            "UPDATE users SET yt_account_hash = $1 WHERE id = $2 AND yt_account_hash IS NULL AND NOT EXISTS (SELECT 1 FROM users WHERE guild_id = $3 AND yt_account_hash = $1)",
            account_hash,
            user_id,
            guild_id,
        )


async def clear_stale_refresh_tokens(before: datetime.datetime):
    pool = await get_pool()
    async with pool.acquire() as connection:
        await connection.execute(
            "UPDATE users SET refresh_token = NULL WHERE refresh_token IS NOT NULL AND (SELECT MAX(last_checked) FROM subscriptions WHERE user_id = users.id) < $1",
            before,
        )


async def clear_user_refresh_token(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as connection:
        await connection.execute(
            "UPDATE users SET refresh_token = NULL WHERE id = $1", user_id
        )


async def get_guild_stats(guild_id: int):
    now = datetime.datetime.now()
    pool = await get_pool()
    async with pool.acquire() as connection:
        return await connection.fetch(
            "SELECT s.id, s.yt_channel_id, COUNT(sub.user_id) AS verified, COUNT(*) FILTER (WHERE sub.is_subscribed) AS subscribed, COUNT(*) FILTER (WHERE sub.created_at >= $2) AS new_week, COUNT(*) FILTER (WHERE sub.created_at >= $3) AS new_month, COUNT(*) FILTER (WHERE NOT sub.is_subscribed AND sub.changed_at >= $3) AS lost_month, MAX(sub.last_checked) AS last_checked FROM servers s LEFT JOIN subscriptions sub ON sub.server_id = s.id WHERE s.guild_id = $1 GROUP BY s.id ORDER BY s.id",
            guild_id,
            now - datetime.timedelta(days=7),
            now - datetime.timedelta(days=30),
        )


async def get_tiers(server_id: int = None):
    pool = await get_pool()
    async with pool.acquire() as connection:
        if server_id:
            return await connection.fetch(
                "SELECT server_id, days, role_id FROM tiers WHERE server_id = $1 ORDER BY days",
                server_id,
            )
        return await connection.fetch(
            "SELECT server_id, days, role_id FROM tiers ORDER BY days"
        )


async def set_tier(server_id: int, days: int, role_id: int = None):
    pool = await get_pool()
    async with pool.acquire() as connection:
        if role_id:
            await connection.execute(
                "INSERT INTO tiers (server_id, days, role_id) VALUES ($1, $2, $3) ON CONFLICT (server_id, days) DO UPDATE SET role_id = EXCLUDED.role_id",
                server_id,
                days,
                role_id,
            )
        else:
            await connection.execute(
                "DELETE FROM tiers WHERE server_id = $1 AND days = $2", server_id, days
            )


async def set_stack_tiers(server_id: int, stack_tiers: bool):
    pool = await get_pool()
    async with pool.acquire() as connection:
        await connection.execute(
            "UPDATE servers SET stack_tiers = $1 WHERE id = $2", stack_tiers, server_id
        )


async def get_channel_name(yt_channel_id: str):
    pool = await get_pool()
    async with pool.acquire() as connection:
        return await connection.fetchrow(
            "SELECT name, updated_at FROM channel_names WHERE yt_channel_id = $1",
            yt_channel_id,
        )


async def set_channel_name(yt_channel_id: str, name: str):
    pool = await get_pool()
    async with pool.acquire() as connection:
        await connection.execute(
            "INSERT INTO channel_names (yt_channel_id, name, updated_at) VALUES ($1, $2, $3) ON CONFLICT (yt_channel_id) DO UPDATE SET name = EXCLUDED.name, updated_at = EXCLUDED.updated_at",
            yt_channel_id,
            name,
            datetime.datetime.now(),
        )


def quota_day() -> datetime.date:
    return datetime.datetime.now(zoneinfo.ZoneInfo("America/Los_Angeles")).date()


async def add_quota_usage(units: int = 1):
    pool = await get_pool()
    async with pool.acquire() as connection:
        await connection.execute(
            "INSERT INTO quota_usage (day, units) VALUES ($1, $2) ON CONFLICT (day) DO UPDATE SET units = quota_usage.units + EXCLUDED.units",
            quota_day(),
            units,
        )


async def get_quota_usage() -> int:
    pool = await get_pool()
    async with pool.acquire() as connection:
        return (
            await connection.fetchval(
                "SELECT units FROM quota_usage WHERE day = $1", quota_day()
            )
            or 0
        )


async def get_last_sync():
    pool = await get_pool()
    async with pool.acquire() as connection:
        return await connection.fetchval("SELECT last_run FROM sync_state")


async def set_last_sync(last_run: datetime.datetime):
    pool = await get_pool()
    async with pool.acquire() as connection:
        await connection.execute(
            "INSERT INTO sync_state (id, last_run) VALUES (TRUE, $1) ON CONFLICT (id) DO UPDATE SET last_run = EXCLUDED.last_run",
            last_run,
        )

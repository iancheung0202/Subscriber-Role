import asyncpg
import asyncio
import os
import datetime

pool = None
_init_lock = None

async def init_db():
    global pool, _init_lock
    
    if _init_lock is None:
        _init_lock = asyncio.Lock()
    async with _init_lock:
        if pool is not None:
            return
        pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
        async with pool.acquire() as connection:
            await connection.execute("CREATE TABLE IF NOT EXISTS servers (id SERIAL PRIMARY KEY, guild_id BIGINT NOT NULL, yt_channel_id TEXT NOT NULL, role_id BIGINT NOT NULL, log_channel_id BIGINT, verification_dm_content TEXT, unsubscribe_dm_content TEXT)")
            await connection.execute("CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, guild_id BIGINT NOT NULL, discord_id BIGINT NOT NULL, refresh_token TEXT, UNIQUE(guild_id, discord_id))")
            await connection.execute("CREATE TABLE IF NOT EXISTS subscriptions (user_id INTEGER NOT NULL, server_id INTEGER NOT NULL, yt_channel_id TEXT NOT NULL, is_subscribed BOOLEAN, last_checked TIMESTAMP, PRIMARY KEY (user_id, server_id), FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE, FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE)")
        
async def get_pool():
    global pool
    if pool is None:
        await init_db()
    return pool

async def set_server_config(guild_id: int, yt_channel_id: str, role_id: int, log_channel_id: int = None, server_id: int = None, verification_dm_content: str = None, unsubscribe_dm_content: str = None):
    pool = await get_pool()
    async with pool.acquire() as connection:
        if server_id:
            await connection.execute("UPDATE servers SET yt_channel_id = $1, role_id = $2, log_channel_id = $3, verification_dm_content = $4, unsubscribe_dm_content = $5 WHERE id = $6 AND guild_id = $7", yt_channel_id, role_id, log_channel_id, verification_dm_content, unsubscribe_dm_content, server_id, guild_id)
            return server_id
        else:
            new_id = await connection.fetchval("INSERT INTO servers (guild_id, yt_channel_id, role_id, log_channel_id, verification_dm_content, unsubscribe_dm_content) VALUES ($1, $2, $3, $4, $5, $6) RETURNING id", guild_id, yt_channel_id, role_id, log_channel_id, verification_dm_content, unsubscribe_dm_content)
            return new_id

async def get_all_server_configs():
    pool = await get_pool()
    async with pool.acquire() as connection:
        return await connection.fetch("SELECT id, guild_id, yt_channel_id, role_id, log_channel_id, verification_dm_content, unsubscribe_dm_content FROM servers ORDER BY guild_id, id")

async def get_user_id(guild_id: int, discord_id: int):
    pool = await get_pool()
    async with pool.acquire() as connection:
        user = await connection.fetchrow("SELECT id FROM users WHERE guild_id = $1 AND discord_id = $2", guild_id, discord_id)
        if user:
            return user['id']
        return await connection.fetchval("INSERT INTO users (guild_id, discord_id) VALUES ($1, $2) RETURNING id", guild_id, discord_id)

async def update_user_refresh_token(user_id: int, refresh_token: str):
    pool = await get_pool()
    async with pool.acquire() as connection:
        await connection.execute("UPDATE users SET refresh_token = $1 WHERE id = $2", refresh_token, user_id)

async def update_subscription_status(user_id: int, server_id: int, yt_channel_id: str, is_subscribed: bool):
    pool = await get_pool()
    async with pool.acquire() as connection:
        await connection.execute("INSERT INTO subscriptions (user_id, server_id, yt_channel_id, is_subscribed, last_checked) VALUES ($1, $2, $3, $4, $5) ON CONFLICT (user_id, server_id) DO UPDATE SET is_subscribed = EXCLUDED.is_subscribed, last_checked = EXCLUDED.last_checked", user_id, server_id, yt_channel_id, is_subscribed, datetime.datetime.now())

async def get_server_config_by_id(server_id: int):
    pool = await get_pool()
    async with pool.acquire() as connection:
        return await connection.fetchrow("SELECT id, guild_id, yt_channel_id, role_id, log_channel_id, verification_dm_content, unsubscribe_dm_content FROM servers WHERE id = $1", server_id)

async def delete_server_config(server_id: int):
    pool = await get_pool()
    async with pool.acquire() as connection:
        await connection.execute("DELETE FROM servers WHERE id = $1", server_id)

async def get_server_configs_for_guild(guild_id: int):
    pool = await get_pool()
    async with pool.acquire() as connection:
        return await connection.fetch("SELECT id, guild_id, yt_channel_id, role_id, log_channel_id, verification_dm_content, unsubscribe_dm_content FROM servers WHERE guild_id = $1 ORDER BY id", guild_id)



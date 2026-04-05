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
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS servers (
                    id SERIAL PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    yt_channel_id TEXT NOT NULL,
                    role_id BIGINT NOT NULL,
                    log_channel_id BIGINT
                )
            """)
            
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    discord_id BIGINT NOT NULL,
                    refresh_token TEXT,
                    UNIQUE(guild_id, discord_id)
                )
            """)
            
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    user_id INTEGER NOT NULL,
                    server_id INTEGER NOT NULL,
                    yt_channel_id TEXT NOT NULL,
                    is_subscribed BOOLEAN,
                    last_checked TIMESTAMP,
                    PRIMARY KEY (user_id, server_id),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE
                )
            """)
            
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS premium (
                    guild_id BIGINT PRIMARY KEY,
                    is_premium BOOLEAN NOT NULL DEFAULT FALSE
                )
            """)
        
async def get_pool():
    global pool
    if pool is None:
        await init_db()
    return pool

async def set_server_config(guild_id: int, yt_channel_id: str, role_id: int, log_channel_id: int = None, server_id: int = None):
    """Create or update server configuration. Returns server_id."""
    pool = await get_pool()
    async with pool.acquire() as connection:
        if server_id:
            await connection.execute(
                "UPDATE servers SET yt_channel_id = $1, role_id = $2, log_channel_id = $3 WHERE id = $4 AND guild_id = $5",
                yt_channel_id, role_id, log_channel_id, server_id, guild_id
            )
            return server_id
        else:
            new_id = await connection.fetchval(
                "INSERT INTO servers (guild_id, yt_channel_id, role_id, log_channel_id) VALUES ($1, $2, $3, $4) RETURNING id",
                guild_id, yt_channel_id, role_id, log_channel_id
            )
            return new_id

async def get_all_server_configs():
    """Get all server subscriptions"""
    pool = await get_pool()
    async with pool.acquire() as connection:
        return await connection.fetch(
            "SELECT id, guild_id, yt_channel_id, role_id, log_channel_id FROM servers ORDER BY guild_id, id"
        )

async def get_user_id(guild_id: int, discord_id: int):
    """Get or create user ID for a guild/discord_id pair"""
    pool = await get_pool()
    async with pool.acquire() as connection:
        user = await connection.fetchrow(
            "SELECT id FROM users WHERE guild_id = $1 AND discord_id = $2",
            guild_id, discord_id
        )
        
        if user:
            return user['id']
        
        return await connection.fetchval(
            "INSERT INTO users (guild_id, discord_id) VALUES ($1, $2) RETURNING id",
            guild_id, discord_id
        )

async def update_user_refresh_token(user_id: int, refresh_token: str):
    """Update user's refresh token"""
    pool = await get_pool()
    async with pool.acquire() as connection:
        await connection.execute(
            "UPDATE users SET refresh_token = $1 WHERE id = $2",
            refresh_token, user_id
        )

async def update_subscription_status(user_id: int, server_id: int, yt_channel_id: str, is_subscribed: bool):
    """Update user's subscription status for a server"""
    pool = await get_pool()
    async with pool.acquire() as connection:
        await connection.execute(
            """INSERT INTO subscriptions (user_id, server_id, yt_channel_id, is_subscribed, last_checked)
               VALUES ($1, $2, $3, $4, $5)
               ON CONFLICT (user_id, server_id) DO UPDATE SET
                   is_subscribed = EXCLUDED.is_subscribed,
                   last_checked = EXCLUDED.last_checked""",
            user_id, server_id, yt_channel_id, is_subscribed, datetime.datetime.now()
        )

async def get_server_config_by_id(server_id: int):
    """Get server configuration by ID"""
    pool = await get_pool()
    async with pool.acquire() as connection:
        return await connection.fetchrow(
            "SELECT id, guild_id, yt_channel_id, role_id, log_channel_id FROM servers WHERE id = $1",
            server_id
        )

async def delete_server_config(server_id: int):
    """Delete a server configuration"""
    pool = await get_pool()
    async with pool.acquire() as connection:
        await connection.execute(
            "DELETE FROM servers WHERE id = $1",
            server_id
        )

async def get_server_configs_for_guild(guild_id: int):
    """Get all server configurations for a guild"""
    pool = await get_pool()
    async with pool.acquire() as connection:
        return await connection.fetch(
            "SELECT id, guild_id, yt_channel_id, role_id, log_channel_id FROM servers WHERE guild_id = $1 ORDER BY id",
            guild_id
        )

async def is_premium(guild_id: int):
    """Check if guild has premium status"""
    pool = await get_pool()
    async with pool.acquire() as connection:
        result = await connection.fetchval(
            "SELECT is_premium FROM premium WHERE guild_id = $1",
            guild_id
        )
        return result is True

async def set_premium(guild_id: int, premium: bool = True):
    """Set premium status for a guild"""
    pool = await get_pool()
    async with pool.acquire() as connection:
        await connection.execute(
            "INSERT INTO premium (guild_id, is_premium) VALUES ($1, $2) ON CONFLICT (guild_id) DO UPDATE SET is_premium = $2",
            guild_id, premium
        )

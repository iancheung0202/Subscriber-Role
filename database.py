import asyncpg
import os

pool = None

async def init_db():
    global pool
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
    async with pool.acquire() as connection:
        await connection.execute("""
            CREATE TABLE IF NOT EXISTS users (
                discord_id BIGINT PRIMARY KEY,
                refresh_token TEXT,
                is_subscribed BOOLEAN,
                last_checked TIMESTAMP
            )
        """)
        
async def get_pool():
    if not pool:
        await init_db()
    return pool


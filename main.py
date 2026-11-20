import asyncio
import logging
import os

import uvicorn
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

from api import app
from bot import bot


async def main():
    token = os.environ.get("DISCORD_TOKEN")

    if not token:
        logging.error("Missing Discord token")
        return

    config = uvicorn.Config(app=app, host="0.0.0.0", port=4700, log_level="info")
    server = uvicorn.Server(config)

    api_task = asyncio.create_task(server.serve())
    bot_task = asyncio.create_task(bot.start(token))

    await asyncio.wait({api_task, bot_task}, return_when=asyncio.FIRST_COMPLETED)
    server.should_exit = True
    await bot.close()
    for result in await asyncio.gather(api_task, bot_task, return_exceptions=True):
        if isinstance(result, Exception):
            raise result


if __name__ == "__main__":
    asyncio.run(main())

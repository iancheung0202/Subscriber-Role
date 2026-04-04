import asyncio
import os
import uvicorn

from dotenv import load_dotenv
load_dotenv()

from api import app
from bot import bot

async def main():
    token = os.environ.get("DISCORD_TOKEN")
    
    if not token:
        print("Missing Discord token")
        return
        
    config = uvicorn.Config(app=app, host="0.0.0.0", port=4700, log_level="info")
    server = uvicorn.Server(config)
    
    api_task = asyncio.create_task(server.serve())
    bot_task = asyncio.create_task(bot.start(token))
    
    await asyncio.gather(api_task, bot_task)

if __name__ == "__main__":
    asyncio.run(main())

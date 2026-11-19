import asyncio
import datetime
import os

import discord
from googleapiclient.discovery import build

from database import add_quota_usage, get_channel_name, set_channel_name

CHANNEL_NAME_TTL = datetime.timedelta(
    hours=int(os.environ["CHANNEL_NAME_REFRESH_HOURS"])
)


def fetch_youtube_channel_name(channel_id: str):
    youtube = build("youtube", "v3", developerKey=os.environ.get("GOOGLE_API_KEY"))
    request = youtube.channels().list(part="snippet", id=channel_id)
    response = request.execute()
    items = response.get("items", [])
    if items:
        return items[0]["snippet"]["title"]
    return None


async def get_youtube_channel_name(channel_id: str) -> str:
    cached = await get_channel_name(channel_id)
    if cached and datetime.datetime.now() - cached["updated_at"] < CHANNEL_NAME_TTL:
        return cached["name"]
    try:
        await add_quota_usage()
        name = await asyncio.to_thread(fetch_youtube_channel_name, channel_id)
        if name:
            await set_channel_name(channel_id, name)
            return name
    except Exception as e:
        print(f"Error fetching YouTube channel name for {channel_id}: {e}")
    return cached["name"] if cached else "Unknown Channel"


CHECK = "<:checkmark:1490467092296761384>"
NEUTRAL = "<:neutralmark:1490467105701756979>"
CROSS = "<:crossmark:1490467125389819904>"
RED_BIN = "<:red_bin:1490468332565037218>"
BIN = "<:bin:1490469928283672686>"
EDIT = "<:sliders:1490469545922531359>"
COG = "<:settings:1490470704963915806>"
ADD = "<:command:1490470996447199384>"
LOG = "<:message:1490471216308551991>"
ROLE = "<:role:1490471628121968882>"
YT = "<:yt:1490472036135342352>"
WARN = "<:warning:1490472664131961083>"
HOME = "<:home:1490473060032315506>"
INFO = "<:info:1490473446117998724>"
FLAG = "<:flag:1490473634844643440>"
HELP = "<:help:1490473862368854197>"
PREMIUM = "<:premium:1490478274097189016>"
MAIL = "<:mail:1490844152827613354>"
REPLY = "<:reply:1036792837821435976>"

COLOR = 0xAF4875
TIER_DURATIONS = {
    7: "7 days",
    30: "30 days",
    90: "90 days",
    180: "6 months",
    365: "1 year",
    730: "2 years",
    1095: "3 years",
    1460: "4 years",
    1825: "5 years",
}
PREMIUM_PERKS = f"{YT} Configure up to 5 YouTube channels\n{MAIL} Set verification success messages\n{FLAG} Set unsubscribe notifications\n{EDIT} Priority and more frequent subscription checks\n{ROLE} Reward long-time subscribers with tier roles"
SKU_ID = int(os.environ.get("DISCORD_PREMIUM_SKU_ID", 0))


async def is_guild_premium(interaction: discord.Interaction) -> bool:
    if not interaction or not interaction.entitlements:
        return False
    for entitlement in interaction.entitlements:
        if (
            entitlement.sku_id == SKU_ID
            and entitlement.guild_id == interaction.guild_id
        ):
            return True
    return False

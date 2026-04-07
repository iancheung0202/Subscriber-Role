import os
import discord

from googleapiclient.discovery import build

from database import is_premium

async def get_youtube_channel_name(channel_id: str) -> str:
    try:
        youtube = build('youtube', 'v3', developerKey=os.environ.get("GOOGLE_API_KEY"))
        request = youtube.channels().list(part="snippet", id=channel_id)
        response = request.execute()
        items = response.get("items", [])
        if items:
            return items[0]['snippet']['title']
    except Exception as e:
        print(f"Error fetching YouTube channel name for {channel_id}: {e}")
    return "Unknown Channel"

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
SKU_ID = os.environ.get("DISCORD_PREMIUM_SKU_ID")

async def check_guild_premium_entitlements(interaction: discord.Interaction) -> bool:
    if not interaction.entitlements:
        return False
    for entitlement in interaction.entitlements:
        if entitlement.sku_id == SKU_ID and entitlement.guild_id == interaction.guild_id:
            return True
    return False

async def get_guild_premium_status(guild_id: int, interaction: discord.Interaction = None) -> bool:
    if interaction:
        has_entitlement = await check_guild_premium_entitlements(interaction)
        if has_entitlement:
            return True
    return await is_premium(guild_id)

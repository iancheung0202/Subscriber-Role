import discord
import os
import asyncio
import urllib.parse

from discord.ext import commands, tasks

from database import get_pool

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.tree.command(name="verify", description="Link your YouTube account to verify your subscription.")
async def verify(interaction: discord.Interaction):
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    redirect_uri = os.environ.get("OAUTH_REDIRECT_URI", "http://subscriber.iancheung.dev/callback")
    
    # State parameter holds the discord user ID
    state = str(interaction.user.id)
    
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/youtube.readonly",
        "access_type": "offline",
        "prompt": "consent",
        "state": state
    }
    
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    
    embed = discord.Embed(
        title="YouTube Account Verification",
        description=f"Click [here]({url}) to link your YouTube account and sync your subscriber role.\n\n"
                    f"*Note: You will be redirected to Google to authorize access.*",
        color=discord.Color.red()
    )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")
    
    if not sync_roles.is_running():
        sync_roles.start()

async def log_action(message, color=discord.Color.blue()):
    log_channel_id = os.environ.get("LOG_CHANNEL_ID")
    if log_channel_id:
        channel = bot.get_channel(int(log_channel_id))
        if channel:
            embed = discord.Embed(description=message, color=color)
            await channel.send(embed=embed)

@tasks.loop(hours=24)
async def sync_roles():
    print("Running background sync task...")
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials
    import datetime
    pool = await get_pool()
    channel_id = os.environ["YT_CHANNEL_ID"]
    guild_id = int(os.environ["GUILD_ID"])
    role_id = int(os.environ["ROLE_ID"])
    guild = bot.get_guild(guild_id)
    if not guild:
        return
        
    role = guild.get_role(role_id)
    if not role:
        return
        
    async with pool.acquire() as connection:
        rows = await connection.fetch("SELECT discord_id, refresh_token FROM users")
        
        for row in rows:
            discord_id = row['discord_id']
            refresh_token = row['refresh_token']
            
            creds = Credentials(
                token=None,
                refresh_token=refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=os.environ["GOOGLE_CLIENT_ID"],
                client_secret=os.environ["GOOGLE_CLIENT_SECRET"]
            )
            
            def check_sub():
                try:
                    youtube = build('youtube', 'v3', credentials=creds)
                    req = youtube.subscriptions().list(part="snippet", mine=True, forChannelId=channel_id)
                    res = req.execute()
                    items = res.get("items", [])
                    return len(items) > 0
                except Exception as e:
                    print(f"Error for {discord_id}: {e}")
                    return False
                
            is_subscribed = await asyncio.to_thread(check_sub)
                    
            try:
                member = await guild.fetch_member(discord_id)
            except discord.errors.NotFound:
                member = None

            if member:
                has_role = role in member.roles
                
                if not is_subscribed and has_role:
                    try:
                        await member.remove_roles(role)
                        try:
                            await log_action(f"Removed automated role from <@{discord_id}> because they are no longer subscribed.", discord.Color.orange())
                        except Exception as e:
                            print(f"Role removed but failed to log: {e}")
                    except discord.errors.Forbidden:
                        print(f"Failed to remove role from {discord_id}: Bot lacks permission.")
                        try:
                            await log_action(f"⚠️ Attempted to remove role from <@{discord_id}> but bot lacks permission in role hierarchy.", discord.Color.red())
                        except Exception:
                            pass
                    
                if is_subscribed and not has_role:
                    try:
                        await member.add_roles(role)
                        try:
                            await log_action(f"Added automated role back to <@{discord_id}> because they re-subscribed.", discord.Color.green())
                        except Exception as e:
                            print(f"Role added but failed to log: {e}")
                    except discord.errors.Forbidden:
                        print(f"Failed to add role to {discord_id}: Bot lacks permission.")
                        try:
                            await log_action(f"⚠️ Attempted to add role to <@{discord_id}> but bot lacks permission in role hierarchy.", discord.Color.red())
                        except Exception:
                            pass
                    
            now = datetime.datetime.now()
            await connection.execute("""
                UPDATE users
                SET is_subscribed = $1, last_checked = $2
                WHERE discord_id = $3
            """, is_subscribed, now, discord_id)

@sync_roles.before_loop
async def before_sync_roles():
    await bot.wait_until_ready()

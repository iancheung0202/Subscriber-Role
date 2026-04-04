import discord
import os
import aiohttp
import asyncio
import datetime

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

from database import get_pool
from bot import bot, log_action

app = FastAPI()

@app.get("/", response_class=HTMLResponse)
async def homepage():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Subscriber Role - Home</title>
        <style>body { font-family: sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; line-height: 1.6; }</style>
    </head>
    <body>
        <h1>Subscriber Role</h1>
        <p>Welcome to the <strong>Subscriber Role</strong> Discord application.</p>
        <h2>What does this app do?</h2>
        <p>This application is a Discord bot designed to verify whether a Discord user is subscribed to a specific YouTube channel. It uses the YouTube Data API to securely check the user's subscription status. If verified, the user is automatically granted a designated "Subscriber" role within the Discord server.</p>
        <h2>How to use it</h2>
        <p>To use this bot, you must run the <code>/verify</code> command in the designated Discord server. This will provide you with a secure login link to authenticate via your Google account.</p>
        <hr>
        <p><a href="/privacy">View our Privacy Policy</a></p>
    </body>
    </html>
    """

@app.get("/privacy", response_class=HTMLResponse)
async def privacy_policy():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Subscriber Role - Privacy Policy</title>
        <style>body { font-family: sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; line-height: 1.6; }</style>
    </head>
    <body>
        <h1>Privacy Policy for Subscriber Role</h1>
        <p>Last updated: """ + datetime.datetime.now().strftime("%B %d, %Y") + """</p>
        <p>This Privacy Policy explains how the <strong>Subscriber Role</strong> Discord bot collects, uses, and protects your information.</p>
        
        <h2>1. Information We Collect</h2>
        <p>When you use the <code>/verify</code> command and authenticate securely through Google OAuth2, we collect the following:</p>
        <ul>
            <li><strong>Discord ID:</strong> Your unique identifier on Discord, so we know which user to assign the role to.</li>
            <li><strong>YouTube Subscription Status:</strong> We check if you are subscribed to the required YouTube channel based on your Google account.</li>
            <li><strong>OAuth2 Refresh Token:</strong> We securely store an offline access token to periodically re-check your subscription status. We do NOT store your Google password or have access to modify your account.</li>
        </ul>

        <h2>2. How We Use Your Information</h2>
        <p>We use your information exclusively to provide the core functionality of the bot:</p>
        <ul>
            <li>To verify your subscription to the required YouTube channel.</li>
            <li>To assign or remove the designated "Subscriber" role automatically in Discord.</li>
        </ul>
        <p>We do not sell, rent, or share your data with any third parties.</p>

        <h2>3. Data Retention and Deletion</h2>
        <p>Your authentication tokens are stored securely in our database. If you wish to revoke our access at any time, you can do so from your <a href="https://myaccount.google.com/permissions" target="_blank">Google Account Permissions page</a>. Doing so will result in the automatic removal of your "Subscriber" role on Discord during the next automated check.</p>

        <hr>
        <p><a href="/">Return to Home</a></p>
    </body>
    </html>
    """

def check_youtube_subscription_sync(credentials, channel_id: str):
    try:
        youtube = build('youtube', 'v3', credentials=credentials)
        request = youtube.subscriptions().list(part="snippet", mine=True, forChannelId=channel_id)
        response = request.execute()
        items = response.get("items", [])
        return len(items) > 0
    except Exception as e:
        print(f"Error checking sub status: {e}")
        return False

async def get_tokens(code: str, redirect_uri: str):
    async with aiohttp.ClientSession() as session:
        data = {
            "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri
        }
        async with session.post("https://oauth2.googleapis.com/token", data=data) as response:
            return await response.json()

def render_page(title: str, content: str) -> str:
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Subscriber Role - {title}</title>
        <style>body {{ font-family: sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; line-height: 1.6; text-align: center; }}</style>
    </head>
    <body>
        <h1>{title}</h1>
        <p>{content}</p>
        <hr>
        <p><a href="/">Return to Home</a></p>
    </body>
    </html>
    """

@app.get("/callback")
async def callback(request: Request):
    code = request.query_params.get("code")
    state = request.query_params.get("state")  # This is the discord_id
    
    if not code or not state:
        return HTMLResponse(render_page("Invalid Request", "Missing code or state."))
    
    discord_id = int(state)
    redirect_uri = os.environ.get("OAUTH_REDIRECT_URI", "http://subscriber.iancheung.dev/callback")
    
    token_response = await get_tokens(code, redirect_uri)
    
    if "error" in token_response:
        return HTMLResponse(render_page("Authentication Error", f"Error authenticating: {token_response.get('error_description', 'Unknown error')}"))
        
    access_token = token_response.get("access_token")
    refresh_token = token_response.get("refresh_token")
    
    if not refresh_token:
        # User already consented before, missing refresh token. Prompt consent was required.
        # Check database for exisitng refresh token if available
        pool = await get_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow("SELECT refresh_token FROM users WHERE discord_id = $1", discord_id)
            if row and row['refresh_token']:
                refresh_token = row['refresh_token']
            else:
                return HTMLResponse(render_page("Access Denied", "Could not retrieve a refresh token. Please re-authenticate and make sure to allow offline access."))
        
    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"]
    )
    
    channel_id = os.environ["YT_CHANNEL_ID"]
    
    is_subscribed = await asyncio.to_thread(check_youtube_subscription_sync, creds, channel_id)
    
    pool = await get_pool()
    now = datetime.datetime.now()
    
    async with pool.acquire() as connection:
        await connection.execute("""
            INSERT INTO users (discord_id, refresh_token, is_subscribed, last_checked)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (discord_id) DO UPDATE SET
                refresh_token = EXCLUDED.refresh_token,
                is_subscribed = EXCLUDED.is_subscribed,
                last_checked = EXCLUDED.last_checked
        """, discord_id, refresh_token, is_subscribed, now)
        
    guild_id = int(os.environ["GUILD_ID"])
    role_id = int(os.environ["ROLE_ID"])
    
    guild = bot.get_guild(guild_id)
    if not guild:
        return HTMLResponse(render_page("Bot Error", "Internal bot error: Cannot find Discord server."))
    
    try:
        member = await guild.fetch_member(discord_id)
    except discord.errors.NotFound:
        return HTMLResponse(render_page("User Not Found", "Cannot find your user in the Discord server. Are you sure you are in it?"))
    except discord.errors.Forbidden:
        return HTMLResponse(render_page("Permission Error", "Bot lacks permission to fetch users from the Discord server. (Is Server Members intent enabled?)"))
    except Exception as e:
        return HTMLResponse(render_page("Unexpected Error", f"An unexpected error occurred while fetching your Discord profile: {e}"))
        
    role = guild.get_role(role_id)
    if not role:
        return HTMLResponse(render_page("Role Not Found", "Internal bot error: Cannot find the specified role."))
        
    if is_subscribed:
        try:
            await member.add_roles(role)
        except discord.errors.Forbidden:
            try:
                await log_action(f"⚠️ Verification succeeded for <@{discord_id}>, but I don't have permission to assign the role.", discord.Color.orange())
            except:
                pass
            return HTMLResponse(render_page("Permission Error", "Bot lacks permission to assign this role. Please explicitly ensure the bot's role is higher in the hierarchy than the Subscriber role."))
        except Exception as e:
            return HTMLResponse(render_page("Unexpected Error", f"An unexpected error occurred while assigning the role: {e}"))

        try:
            await log_action(f"✅ Verified <@{discord_id}> and added the Subscriber role.", discord.Color.green())
        except Exception as e:
            return HTMLResponse(render_page("Success", f"Success! However, the bot failed to send a log message to the log channel. Please check the log channel permissions. Error: {e}"))
            
        return HTMLResponse(render_page("Verification Successful", "Success! Your subscription has been verified and you have been granted the role on Discord. You may now close this window."))
    else:
        try:
            await log_action(f"❌ <@{discord_id}> attempted to verify, but is not subscribed to the target channel.", discord.Color.red())
        except Exception as e:
            pass # Keep returning the normal error message
        return HTMLResponse(render_page("Verification Failed", "Verification failed: You are not subscribed to the required channel. Please subscribe and try again."))

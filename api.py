import discord
import os
import aiohttp
import asyncio
import datetime

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

from database import get_pool, get_user_id, update_user_refresh_token, update_subscription_status, get_server_config_by_id
from bot import bot, log_action
from utils import get_youtube_channel_name, CHECK, NEUTRAL, CROSS

app = FastAPI()

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(CORSMiddleware, allow_origins=[os.environ.get("CORS_ORIGIN", "http://subscriber.iancheung.dev")], allow_credentials=True, allow_methods=["GET"], allow_headers=["Content-Type"], max_age=600,)

app.add_middleware(TrustedHostMiddleware, allowed_hosts=[os.environ.get("ALLOWED_HOST", "subscriber.iancheung.dev")])

MAX_REQUEST_SIZE = 1_000_000

BLOCKED_USER_AGENTS = ["bot", "crawler", "spider", "scraper", "curl", "wget", "python-requests"]

@app.middleware("http")
async def validate_request_size_and_user_agent(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_REQUEST_SIZE:
        return HTMLResponse(content="Request too large", status_code=413)
    
    user_agent = request.headers.get("user-agent", "").lower()
    if any(blocked in user_agent for blocked in BLOCKED_USER_AGENTS):
        return HTMLResponse(content="Access denied", status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    
    return response

@app.get("/", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def homepage(request: Request):
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Subscriber Role - Discord Bot</title>
        <link rel="icon" href="https://cdn.discordapp.com/avatars/1490081882140840016/72f8e045f550fc5ac768d525f1d60ba7.png?size=32" type="image/png">
        <style>body { font-family: sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; line-height: 1.6; } a { color: #af4875; border: 2px solid #d8c3cd; padding: 8px 12px; border-radius: 8px; text-decoration: none; display: inline-block; margin: 2px; transition: all 0.3s ease; } a:hover { opacity: 0.85; transform: translateY(-2px); box-shadow: 0 2px 8px rgba(0,0,0,0.15); } a:active { transform: translateY(0); } footer { text-align: center; margin-top: 40px; padding-top: 20px; border-top: 1px solid #ccc; font-size: 0.9em; color: #666; }</style>
    </head>
    <body>
        <h1>Subscriber Role</h1>
        <p>Welcome to the <strong>Subscriber Role</strong> Discord application.</p>
        <p><a href="https://discord.com/oauth2/authorize?client_id=1490081882140840016">Invite the bot to your server</a></p>
        <h2>What does this app do?</h2>
        <p>This is a simple Discord bot designed to verify whether a Discord user is subscribed to a specific YouTube channel. It uses the YouTube API to securely check the user's subscription status. If verified, the user is automatically granted a designated "Subscriber" role within the Discord server.</p>
        <h3>For Server Admins</h3>
        <p>Run the <code>/setup</code> command (requires administrator permissions) to configure the bot for your server. You'll need to specify a YouTube channel and subscriber role.</p>
        <h3>For Members</h3>
        <p>Run the <code>/verify</code> command to link your YouTube account and verify your subscription. You will get the subscriber role as long as you're subscribed to the configured channel.</p>
        
        <p><a href="https://github.com/iancheung0202/Subscriber-Role">GitHub</a> <a href="/privacy">Privacy Policy</a> <a href="/terms">Terms of Service</a></p>
        <footer>
            <p>Developed by Ian Cheung • All rights reserved.</p>
        </footer>
    </body>
    </html>
    """

@app.get("/privacy", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def privacy_policy(request: Request):
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Subscriber Role - Privacy Policy</title>
        <link rel="icon" href="https://cdn.discordapp.com/avatars/1490081882140840016/72f8e045f550fc5ac768d525f1d60ba7.png?size=32" type="image/png">
        <style>body { font-family: sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; line-height: 1.6; } a { color: #af4875; border: 2px solid #d8c3cd; padding: 8px 12px; border-radius: 8px; text-decoration: none; display: inline-block; margin: 2px; transition: all 0.3s ease; } a:hover { opacity: 0.85; transform: translateY(-2px); box-shadow: 0 2px 8px rgba(0,0,0,0.15); } a:active { transform: translateY(0); } footer { text-align: center; margin-top: 40px; padding-top: 20px; border-top: 1px solid #ccc; font-size: 0.9em; color: #666; }</style>
    </head>
    <body>
        <h1>Privacy Policy for Subscriber Role</h1>
        <p><a href="/">Return to Home</a></p>
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

        <footer>
            <p>Developed by Ian Cheung • All rights reserved.</p>
        </footer>
    </body>
    </html>
    """

@app.get("/terms", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def terms_of_service(request: Request):
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Subscriber Role - Terms of Service</title>
        <link rel="icon" href="https://cdn.discordapp.com/avatars/1490081882140840016/72f8e045f550fc5ac768d525f1d60ba7.png?size=32?size=32" type="image/png">
        <style>body { font-family: sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; line-height: 1.6; } a { color: #af4875; border: 2px solid #d8c3cd; padding: 8px 12px; border-radius: 8px; text-decoration: none; display: inline-block; margin: 2px; transition: all 0.3s ease; } a:hover { opacity: 0.85; transform: translateY(-2px); box-shadow: 0 2px 8px rgba(0,0,0,0.15); } a:active { transform: translateY(0); } footer { text-align: center; margin-top: 40px; padding-top: 20px; border-top: 1px solid #ccc; font-size: 0.9em; color: #666; }</style>
    </head>
    <body>
        <h1>Terms of Service for Subscriber Role</h1>
        <p><a href="/">Return to Home</a></p>
        <p>Last updated: """ + datetime.datetime.now().strftime("%B %d, %Y") + """</p>
        <p>By using the <strong>Subscriber Role</strong> Discord bot, you agree to the following terms and conditions.</p>
        
        <h2>1. Acceptance of Terms</h2>
        <p>By inviting and using the Subscriber Role bot in your Discord server, you agree to be bound by these Terms of Service. If you do not agree with any of these terms, you should not use the bot.</p>

        <h2>2. Use of the Bot</h2>
        <p>The Subscriber Role bot is provided as-is for the purpose of verifying YouTube channel subscriptions and assigning Discord roles. You agree to use this bot in compliance with Discord's Terms of Service and Community Guidelines.</p>

        <h2>3. User Responsibilities</h2>
        <p>As a server administrator, you are responsible for:</p>
        <ul>
            <li>Configuring the bot appropriately with a valid YouTube channel ID and role.</li>
            <li>Ensuring all users in your server understand and consent to the verification process.</li>
            <li>Maintaining compliance with applicable laws and Discord policies.</li>
            <li>Handling user data appropriately and respecting user privacy.</li>
        </ul>

        <h2>4. Limitation of Liability</h2>
        <p>The Subscriber Role bot is provided on an "AS-IS" basis without warranties of any kind. We are not responsible for:</p>
        <ul>
            <li>Service interruptions, downtime, or data loss.</li>
            <li>Errors in subscription verification or role assignment.</li>
            <li>Discord API changes that may affect bot functionality.</li>
            <li>Any damages or losses resulting from the use of this bot.</li>
        </ul>

        <h2>5. Modification and Termination</h2>
        <p>We reserve the right to modify or discontinue the bot at any time without notice. We also reserve the right to terminate access to the bot for any user or server that violates these terms.</p>

        <h2>6. Disclaimer</h2>
        <p>This bot is not affiliated with Discord, Google, or YouTube. Discord, Google, and YouTube are trademarks of their respective owners.</p>

        <footer>
            <p>Developed by Ian Cheung • All rights reserved.</p>
        </footer>
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
        data = {"client_id": os.environ["GOOGLE_CLIENT_ID"], "client_secret": os.environ["GOOGLE_CLIENT_SECRET"], "code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri}
        async with session.post("https://oauth2.googleapis.com/token", data=data) as response:
            return await response.json()

def render_page(title: str, content: str) -> str:
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Subscriber Role - {title}</title>
        <link rel="icon" href="https://cdn.discordapp.com/avatars/1490081882140840016/72f8e045f550fc5ac768d525f1d60ba7.png?size=32" type="image/png">
        <style>body {{ font-family: sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; line-height: 1.6; text-align: center; }} a {{ color: #af4875; border: 2px solid #d8c3cd; padding: 8px 12px; border-radius: 8px; text-decoration: none; display: inline-block; margin: 2px; transition: all 0.3s ease; }} a:hover {{ opacity: 0.85; transform: translateY(-2px); box-shadow: 0 2px 8px rgba(0,0,0,0.15); }} a:active {{ transform: translateY(0); }} footer {{ text-align: center; margin-top: 40px; padding-top: 20px; border-top: 1px solid #ccc; font-size: 0.9em; color: #666; }}</style>
    </head>
    <body>
        <h1>{title}</h1>
        <p>{content}</p>
        <p><a href="/">Return to Home</a></p>
        <footer>
            <p>Developed by Ian Cheung • All rights reserved.</p>
        </footer>
    </body>
    </html>
    """

@app.get("/callback")
@limiter.limit("10/minute")
async def callback(request: Request):
    code = request.query_params.get("code")
    state = request.query_params.get("state")  # guild_id_discord_id_server_id
    
    if not code or not state:
        return HTMLResponse(render_page("Invalid Request", "Missing code or state."))
    
    try:
        parts = state.split("_")
        if len(parts) != 3:
            raise ValueError("Invalid state format")
        guild_id = int(parts[0])
        discord_id = int(parts[1])
        server_id = int(parts[2])
    except (ValueError, IndexError):
        return HTMLResponse(render_page("Invalid Request", "Invalid state parameter."))
    
    server_config = await get_server_config_by_id(server_id)
    
    if not server_config:
        return HTMLResponse(render_page("Configuration Error", "This server hasn't been configured yet. Ask an admin to run `/setup`."))
    
    yt_channel_id = server_config['yt_channel_id']
    channel_name = await get_youtube_channel_name(yt_channel_id)
    role_id = server_config['role_id']
    
    redirect_uri = os.environ.get("OAUTH_REDIRECT_URI", "http://subscriber.iancheung.dev/callback")
    
    token_response = await get_tokens(code, redirect_uri)
    
    if "error" in token_response:
        return HTMLResponse(render_page("Authentication Error", f"Error authenticating: {token_response.get('error_description', 'Unknown error')}"))
        
    access_token = token_response.get("access_token")
    refresh_token = token_response.get("refresh_token")
    
    user_id = await get_user_id(guild_id, discord_id)
    
    if not refresh_token:
        pool = await get_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow("SELECT refresh_token FROM users WHERE id = $1", user_id)
            if row and row['refresh_token']:
                refresh_token = row['refresh_token']
            else:
                return HTMLResponse(render_page("Access Denied", "Could not retrieve a refresh token. Please re-authenticate and make sure to allow offline access."))
    else:
        await update_user_refresh_token(user_id, refresh_token)
        
    creds = Credentials(token=access_token, refresh_token=refresh_token, token_uri="https://oauth2.googleapis.com/token", client_id=os.environ["GOOGLE_CLIENT_ID"], client_secret=os.environ["GOOGLE_CLIENT_SECRET"])
    
    is_subscribed = await asyncio.to_thread(check_youtube_subscription_sync, creds, yt_channel_id)
    
    await update_subscription_status(user_id, server_id, yt_channel_id, is_subscribed)
    
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
    
    yt_channel_url = f"https://www.youtube.com/channel/{yt_channel_id}"
        
    if is_subscribed:
        try:
            await member.add_roles(role)
        except discord.errors.Forbidden:
            try:
                await log_action(guild_id, f"{CROSS} Verification succeeded for <@{discord_id}> for {role.mention} on [{channel_name}]({yt_channel_url}), but bot lacks permission to assign role.", discord.Color.orange(), server_id=server_id)
            except:
                pass
            return HTMLResponse(render_page("Permission Error", "Bot lacks permission to assign this role. Please explicitly ensure the bot's role is higher in the hierarchy than the Subscriber role."))
        except Exception as e:
            return HTMLResponse(render_page("Unexpected Error", f"An unexpected error occurred while assigning the role: {e}"))
        
        if server_config.get('verification_dm_content'):
            try:
                dm_embed = discord.Embed(description=server_config['verification_dm_content'], color=0xAF4875)
                dm_embed.set_footer(text=f"Sent from {guild.name}")
                await member.send(embed=dm_embed)
            except Exception as e:
                print(f"Error sending verification DM to {discord_id}: {e}")
        
        try:
            await log_action(guild_id, f"{CHECK} Verified <@{discord_id}> and added {role.mention} for [{channel_name}]({yt_channel_url}).", discord.Color.green(), server_id=server_id)
        except Exception as e:
            return HTMLResponse(render_page("Success", f"Success! However, the bot failed to send a log message to the log channel. Please check the log channel permissions. Error: {e}"))
        return HTMLResponse(render_page("Verification Successful", "Success! Your subscription has been verified and you have been granted the role on Discord. You may now close this window."))
    else:
        try:
            await log_action(guild_id, f"{NEUTRAL} <@{discord_id}> attempted to verify for {role.mention} on [{channel_name}]({yt_channel_url}), but is not subscribed.", discord.Color.red(), server_id=server_id)
        except Exception as e:
            pass
        return HTMLResponse(render_page("Verification Failed", "Verification failed: You are not subscribed to the required channel. Please subscribe and try again."))

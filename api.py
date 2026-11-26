import asyncio
import datetime
import hashlib
import hmac
import html
import logging
import os
import pathlib
import re
import time

import aiohttp
import discord
import markdown
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from bot import bot, log_action
from database import (
    add_quota_usage,
    clear_user_refresh_token,
    get_account_holder,
    get_server_config_by_id,
    get_tiers,
    get_user_id,
    get_user_refresh_token,
    hash_account,
    set_account_hash,
    update_subscription_status,
    update_user_refresh_token,
)
from sync import get_premium_guild_ids, sync_tier_roles
from utils import CHECK, CROSS, NEUTRAL, get_youtube_channel_name

app = FastAPI()


def client_address(request: Request) -> str:
    return request.headers.get("x-real-ip") or get_remote_address(request)


limiter = Limiter(key_func=client_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ["CORS_ORIGIN"]],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["Content-Type"],
    max_age=600,
)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=[os.environ["ALLOWED_HOST"]],
)

BOT_AVATAR = "https://iancheung.dev/assets/img/subscriber-role.png"
PAGES = pathlib.Path(__file__).parent / "pages"
RUN_VERIFY = "Please run the <b>/verify</b> command again in Discord."
LINK_LIFETIME_SECONDS = 3600
INVALID_LINK = f"This verification link is invalid or has expired. {RUN_VERIFY}"


def page(name: str) -> str:
    template = (PAGES / f"{name}.html").read_text()
    return template.format(
        date=datetime.datetime.now().strftime("%B %d, %Y"),
        retention_days=os.environ["TOKEN_RETENTION_DAYS"],
    )


def generate_page(
    title: str, description: str, url: str, body_html: str, centered: bool = False
) -> str:
    align = " text-align: center;" if centered else ""
    styles = f"body {{ font-family: sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; line-height: 1.6;{align} }} a {{ color: #af4875; border: 2px solid #d8c3cd; padding: 8px 12px; border-radius: 8px; text-decoration: none; display: inline-block; margin: 2px; transition: all 0.3s ease; }} a:hover {{ opacity: 0.85; transform: translateY(-2px); box-shadow: 0 2px 8px rgba(0,0,0,0.15); }} a:active {{ transform: translateY(0); }} aside {{ border: 2px solid #d8c3cd; border-radius: 8px; padding: 0 12px; color: #af4875; }} aside p {{ margin: 8px 0; }} aside a {{ border: 0; padding: 0; margin: 0; text-decoration: underline; display: inline; box-shadow: none; }} footer {{ text-align: center; margin-top: 40px; padding-top: 20px; border-top: 1px solid #ccc; font-size: 0.9em; color: #666; }}"
    footer_html = (
        "<footer><p>Developed by Ian Cheung • All rights reserved.</p></footer>"
    )
    notice = os.environ.get("SITE_NOTICE")
    notice_html = f"<aside>{markdown.markdown(notice)}</aside>" if notice else ""
    full_body = f"{notice_html}\n        {body_html}\n        {footer_html}"
    return f'<!DOCTYPE html> <html lang="en"> <head> <meta charset="UTF-8"> <meta name="viewport" content="width=device-width, initial-scale=1.0"> <meta name="description" content="{description}"> <meta name="theme-color" content="#af4875"> <meta property="og:title" content="{title}"> <meta property="og:description" content="{description}"> <meta property="og:image" content="{BOT_AVATAR}?size=256"> <meta property="og:url" content="{url}"> <meta property="og:type" content="website"> <meta name="twitter:card" content="summary_large_image"> <meta name="twitter:title" content="{title}"> <meta name="twitter:description" content="{description}"> <meta name="twitter:image" content="{BOT_AVATAR}?size=256"> <title>{title}</title> <link rel="icon" href="{BOT_AVATAR}?size=32" type="image/png"> <style>{styles}</style> </head> <body> {full_body} </body> </html>'


def listed(name: str, user_agent: str) -> bool:
    return any(
        entry and entry in user_agent for entry in os.getenv(name, "").split(",")
    )


@app.middleware("http")
async def validate_request_size_and_user_agent(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > 1000000:
        return HTMLResponse(
            render_response("Request Too Large", "This request is too large."),
            status_code=413,
        )
    user_agent = request.headers.get("user-agent", "").lower()
    if not listed("ALLOWED_CRAWLERS", user_agent) and listed(
        "BLOCKED_USER_AGENTS", user_agent
    ):
        return HTMLResponse(
            render_response(
                "Access Denied", "Your browser is not allowed to open this page."
            ),
            status_code=403,
        )
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains"
    )
    return response


@app.get("/", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def home_page(request: Request):
    return generate_page(
        "Subscriber Role - Discord Bot",
        "Verify YouTube channel subscriptions and automatically assign Discord roles with Subscriber Role bot.",
        "https://subscriber.iancheung.dev/",
        page("home"),
    )


@app.get("/privacy", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def privacy_policy(request: Request):
    return generate_page(
        "Subscriber Role - Privacy Policy",
        "Privacy policy for Subscriber Role Discord bot. Learn how we handle your data.",
        "https://subscriber.iancheung.dev/privacy",
        page("privacy"),
    )


@app.get("/terms", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def terms_of_service(request: Request):
    return generate_page(
        "Subscriber Role - Terms of Service",
        "Terms of service for Subscriber Role Discord bot. Read our usage policies and terms.",
        "https://subscriber.iancheung.dev/terms",
        page("terms"),
    )


def check_subscriptions(credentials, channel_id: str):
    try:
        youtube = build("youtube", "v3", credentials=credentials)
        request = youtube.subscriptions().list(
            part="snippet", mine=True, forChannelId=channel_id
        )
        response = request.execute()
        items = response.get("items", [])
        return items[0]["snippet"] if items else False
    except Exception as e:
        logging.error(f"Error checking sub status: {e}")
        return None


async def get_tokens(code: str, redirect_uri: str):
    async with aiohttp.ClientSession() as session:
        data = {
            "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
        async with session.post(
            "https://oauth2.googleapis.com/token", data=data
        ) as response:
            return await response.json()


def verify_signature(state: str, state_secret: str) -> tuple:
    try:
        if "." not in state:
            return None
        state_data, signature = state.rsplit(".", 1)
        expected_signature = hmac.new(
            state_secret.encode(), state_data.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            return None
        parts = state_data.split("_")
        if len(parts) != 4:
            return None
        guild_id, discord_id, server_id, created = [int(part) for part in parts]
        if time.time() - created > LINK_LIFETIME_SECONDS:
            return None
        return (guild_id, discord_id, server_id)
    except (ValueError, IndexError, AttributeError):
        return None


def render_response(title: str, content: str) -> str:
    return generate_page(
        f"Subscriber Role - {title}",
        re.sub("<[^>]+>", "", content)[:160],
        "https://subscriber.iancheung.dev/callback",
        f"""<h1>{title}</h1> <p>{content}</p> <p><a href="/">Return to Home</a></p>""",
        centered=True,
    )


@app.get("/callback")
@limiter.limit("10/minute")
async def callback(request: Request):
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if request.query_params.get("error"):
        return HTMLResponse(
            render_response(
                "Sign-In Cancelled",
                f"You cancelled the Google sign-in. {RUN_VERIFY}",
            )
        )
    if not code or not state:
        return HTMLResponse(render_response("Invalid Link", INVALID_LINK))
    state_secret = os.environ.get("STATE_SECRET")
    if not state_secret:
        return HTMLResponse(
            render_response(
                "Internal Server Error",
                "The bot is not configured correctly. Please try again later.",
            )
        )
    parsed_state = verify_signature(state, state_secret)
    if not parsed_state:
        return HTMLResponse(render_response("Invalid Link", INVALID_LINK))
    guild_id, discord_id, server_id = parsed_state
    server_config = await get_server_config_by_id(server_id)
    if not server_config:
        return HTMLResponse(
            render_response(
                "Server Not Set Up",
                "This server has not been set up yet. Ask a server admin to run the <b>/setup</b> command.",
            )
        )
    yt_channel_id = server_config["yt_channel_id"]
    channel_name = await get_youtube_channel_name(yt_channel_id)
    role_id = server_config["role_id"]
    redirect_uri = os.environ["OAUTH_REDIRECT_URI"]
    token_response = await get_tokens(code, redirect_uri)
    if "error" in token_response:
        logging.error(f"Error exchanging the Google code: {token_response}")
        return HTMLResponse(
            render_response(
                "Sign-In Failed",
                f"The bot could not sign you in with Google. {RUN_VERIFY}",
            )
        )
    access_token = token_response.get("access_token")
    user_id = await get_user_id(guild_id, discord_id)
    previous_token = await get_user_refresh_token(user_id)
    refresh_token = token_response.get("refresh_token") or previous_token
    if not refresh_token:
        return HTMLResponse(
            render_response(
                "Sign-In Failed",
                f"Google did not give the bot access to your YouTube account. {RUN_VERIFY}",
            )
        )
    await update_user_refresh_token(user_id, refresh_token)
    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
    )
    await add_quota_usage()
    snippet = await asyncio.to_thread(check_subscriptions, creds, yt_channel_id)
    if snippet is None:
        return HTMLResponse(
            render_response(
                "Try Again Later",
                "The bot could not check your subscription right now. Please try again later.",
            )
        )
    is_subscribed = bool(snippet)
    guild = bot.get_guild(guild_id)
    if not guild:
        return HTMLResponse(
            render_response(
                "Internal Server Error",
                "The bot cannot find the Discord server. Ask a server admin to make sure the bot is in the server.",
            )
        )
    if is_subscribed and snippet.get("channelId"):
        account_hash = hash_account(snippet["channelId"])
        holder = await get_account_holder(guild_id, account_hash, user_id)
        if holder:
            try:
                await guild.fetch_member(holder["discord_id"])
                if previous_token:
                    await update_user_refresh_token(user_id, previous_token)
                else:
                    await clear_user_refresh_token(user_id)
                try:
                    await log_action(
                        guild_id,
                        f"{NEUTRAL} <@{discord_id}> attempted to verify for [{channel_name}](https://www.youtube.com/channel/{yt_channel_id}), but their YouTube account is already linked to <@{holder['discord_id']}>.",
                        discord.Color.red(),
                        server_id=server_id,
                    )
                except Exception:
                    pass
                return HTMLResponse(
                    render_response(
                        "Account Already Linked",
                        "This YouTube account is already linked to another member of this server. Please use a different YouTube account to verify.",
                    )
                )
            except discord.errors.NotFound:
                await set_account_hash(holder["id"])
        await set_account_hash(user_id, account_hash)
    await update_subscription_status(user_id, server_id, yt_channel_id, is_subscribed)
    try:
        member = await guild.fetch_member(discord_id)
    except discord.errors.NotFound:
        return HTMLResponse(
            render_response(
                "Member Not Found",
                f"The bot cannot find you in the Discord server. Please join the server first. {RUN_VERIFY}",
            )
        )
    except discord.errors.Forbidden:
        return HTMLResponse(
            render_response(
                "Permission Error",
                "The bot lacks permission to find you in the Discord server. Ask a server admin to make sure the bot is in the server.",
            )
        )
    except Exception as e:
        logging.error(f"Error fetching the Discord profile: {e}")
        return HTMLResponse(
            render_response(
                "Try Again Later",
                "The bot could not load your Discord profile. Please try again later.",
            )
        )
    role = guild.get_role(role_id)
    if not role:
        return HTMLResponse(
            render_response(
                "Role Not Found",
                "The bot cannot find the subscriber role. Ask a server admin to check the role with the <b>/setup</b> command.",
            )
        )
    yt_channel_url = f"https://www.youtube.com/channel/{yt_channel_id}"
    if is_subscribed:
        try:
            await member.add_roles(role)
        except discord.errors.Forbidden:
            try:
                await log_action(
                    guild_id,
                    f"{CROSS} Verification succeeded for <@{discord_id}> for {role.mention} on [{channel_name}]({yt_channel_url}), but bot lacks permission to assign role.",
                    discord.Color.orange(),
                    server_id=server_id,
                )
            except:
                pass
            return HTMLResponse(
                render_response(
                    "Permission Error",
                    "The bot lacks permission to give you the role. Ask a server admin to move the bot's role above the subscriber role.",
                )
            )
        except Exception as e:
            logging.error(f"Error assigning the role: {e}")
            return HTMLResponse(
                render_response(
                    "Try Again Later",
                    "The bot could not give you the role. Please try again later.",
                )
            )
        tiers = await get_tiers(server_id)
        message = server_config.get("verification_dm_content")
        premium = (tiers or message) and guild_id in await get_premium_guild_ids()
        if tiers and premium:
            await sync_tier_roles(
                member, guild, server_config, tiers, channel_name, snippet
            )
        if message and premium:
            try:
                dm_embed = discord.Embed(description=message, color=0xAF4875)
                dm_embed.set_footer(text=f"Sent from {guild.name}")
                await member.send(embed=dm_embed)
            except Exception as e:
                logging.error(f"Error sending verification DM to {discord_id}: {e}")
        try:
            await log_action(
                guild_id,
                f"{CHECK} Verified <@{discord_id}> and added {role.mention} for [{channel_name}]({yt_channel_url}).",
                discord.Color.green(),
                server_id=server_id,
            )
        except Exception as e:
            logging.error(f"Error sending verification log: {e}")
            return HTMLResponse(
                render_response(
                    "Verification Successful",
                    "Your subscription has been verified and you have been given the role on Discord. However, the bot could not post to the log channel. If you are a server admin, please check the log channel permissions.",
                )
            )
        return HTMLResponse(
            render_response(
                "Verification Successful",
                "Your subscription has been verified and you have been given the role on Discord. You may now close this window.",
            )
        )
    else:
        try:
            await log_action(
                guild_id,
                f"{NEUTRAL} <@{discord_id}> attempted to verify for {role.mention} on [{channel_name}]({yt_channel_url}), but is not subscribed.",
                discord.Color.red(),
                server_id=server_id,
            )
        except Exception as e:
            pass
        return HTMLResponse(
            render_response(
                "Not Subscribed",
                f'You are not subscribed to the required channel. Please subscribe to <a href="{yt_channel_url}" target="_blank">{html.escape(channel_name)}</a> and try again.',
            )
        )

import asyncio
import logging
import os

import discord
from discord.ext import commands

from database import (
    delete_server_config,
    get_pool,
    get_server_config_by_id,
    get_server_configs_for_guild,
    get_user_id,
    set_server_config,
)
from utils import (
    ADD,
    CHECK,
    COG,
    COLOR,
    CROSS,
    LOG,
    PREMIUM,
    PREMIUM_PERKS,
    ROLE,
    SKU_ID,
    WARN,
    YT,
    get_youtube_channel_name,
    is_guild_premium,
)
from views import SetupMainView, VerifyChannelSelectView, send_error

intents = discord.Intents.default()


class Bot(commands.Bot):
    async def status_task(self):
        timeout = 5
        while True:
            await asyncio.sleep(timeout)
            await self.change_presence(
                status=discord.Status.dnd,
                activity=discord.Activity(
                    type=discord.ActivityType.watching, name="YouTube"
                ),
            )
            await asyncio.sleep(timeout)
            await self.change_presence(
                status=discord.Status.online,
                activity=discord.Activity(
                    type=discord.ActivityType.listening, name="Subscribers"
                ),
            )
            await asyncio.sleep(timeout)
            await self.change_presence(
                status=discord.Status.dnd,
                activity=discord.Activity(
                    type=discord.ActivityType.listening,
                    name=f"{len(self.guilds)} guilds",
                ),
            )
            await asyncio.sleep(timeout)


bot = Bot(command_prefix=commands.when_mentioned, intents=intents)


async def owner_log(env_var: str, message: str, color=COLOR):
    channel_id = os.environ.get(env_var)
    if not channel_id:
        return
    try:
        channel = bot.get_channel(int(channel_id)) or await bot.fetch_channel(
            int(channel_id)
        )
        await channel.send(embed=discord.Embed(description=message, color=color))
    except Exception as e:
        logging.error(f"Error sending owner log to {env_var}: {e}")


def describe_guild(guild: discord.Guild) -> str:
    return f"{discord.utils.escape_markdown(guild.name)} (`{guild.id}`, {guild.member_count or 0} members)"


async def describe_entitlement(entitlement: discord.Entitlement) -> str:
    guild = bot.get_guild(entitlement.guild_id) if entitlement.guild_id else None
    where = describe_guild(guild) if guild else f"guild `{entitlement.guild_id}`"
    return f"{where} by <@{entitlement.user_id}> (`{entitlement.user_id}`)"


@bot.event
async def on_guild_join(guild: discord.Guild):
    await owner_log(
        "GUILD_LOG_CHANNEL_ID",
        f"{CHECK} Joined {describe_guild(guild)}. Now in {len(bot.guilds)} servers.",
        discord.Color.green(),
    )
    try:
        await asyncio.sleep(3)
        owner = await bot.fetch_user(guild.owner_id)
        await owner.send(
            embed=discord.Embed(
                title=f"{COG} Getting Started",
                description=f"{bot.user.mention} was just added to **{discord.utils.escape_markdown(guild.name)}**!\n\n"
                f"1. Run `/setup` to set your YouTube channel and subscriber role {YT}\n"
                f"2. Ask your members to run `/verify` to get the role {CHECK}",
                color=COLOR,
            ).set_footer(
                text="Tip: Require the subscriber role in your giveaway bot for subscriber-only giveaways."
            )
        )
    except Exception as e:
        logging.info(f"Error sending setup DM to owner {guild.owner_id}: {e}")


@bot.event
async def on_guild_remove(guild: discord.Guild):
    await owner_log(
        "GUILD_LOG_CHANNEL_ID",
        f"{CROSS} Left {describe_guild(guild)}. Now in {len(bot.guilds)} servers.",
        discord.Color.red(),
    )


@bot.event
async def on_message(message: discord.Message):
    mention = bot.user.mention
    if message.author.bot or message.content.lower().split() not in (
        [mention],
        [mention, "help"],
    ):
        return
    try:
        await message.reply(
            embed=discord.Embed(
                title=f"{COG} Commands",
                description="\n".join(
                    f"`/{command.name}` {command.description}"
                    for command in bot.tree.get_commands()
                ),
                color=COLOR,
            )
        )
    except Exception as e:
        logging.info(f"Error sending help reply in {message.channel.id}: {e}")


@bot.event
async def on_app_command_completion(
    interaction: discord.Interaction, command: discord.app_commands.Command
):
    where = describe_guild(interaction.guild) if interaction.guild else "a DM"
    await owner_log(
        "COMMAND_LOG_CHANNEL_ID",
        f"{ADD} **Command:** `/{command.qualified_name}`\n{ROLE} **User:** <@{interaction.user.id}>\n{LOG} **Server:** {where}.",
    )


@bot.tree.command(
    name="setup", description="Configure the bot for your server. (Admin only)"
)
@discord.app_commands.guild_only()
async def setup(interaction: discord.Interaction):
    if not (
        interaction.permissions.administrator
        or str(interaction.user.id) in os.environ.get("OWNER_IDS", "").split(",")
    ):
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"{CROSS} You need administrator permissions to run this command.",
                color=COLOR,
            ),
            ephemeral=True,
        )
        return
    embed = discord.Embed(
        title=f"{COG} Server Configuration",
        description="Choose an action below to manage your server's YouTube subscriber role settings!",
        color=COLOR,
    )
    view = SetupMainView(interaction.guild_id)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


@bot.tree.command(name="premium", description="Enable premium for this server.")
@discord.app_commands.guild_only()
async def premium(interaction: discord.Interaction):
    has_premium = await is_guild_premium(interaction)
    store_link = (
        f"https://discord.com/discovery/applications/{bot.user.id}/store/{SKU_ID}"
    )
    if has_premium:
        embed = discord.Embed(
            title=f"{PREMIUM} Subscriber Role Premium",
            description=f"Thank you for supporting Subscriber Role! Your server already has premium unlocked and can enjoy:\n\n{PREMIUM_PERKS}",
            color=COLOR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        embed = discord.Embed(
            title=f"{PREMIUM} Subscriber Role Premium",
            description=f"Premium unlocks advanced features to supercharge your YouTube community!\n\n{PREMIUM_PERKS}",
            color=COLOR,
        )
        await interaction.response.send_message(
            content=store_link, embed=embed, ephemeral=True
        )


@bot.tree.command(
    name="verify", description="Link your YouTube account to verify your subscription."
)
@discord.app_commands.guild_only()
async def verify(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    configs = await get_server_configs_for_guild(interaction.guild_id)
    if not configs:
        await interaction.followup.send(
            embed=discord.Embed(
                description=f"{CROSS} This server hasn't been configured yet. Please ask an admin to run `/setup`.",
                color=COLOR,
            ),
            ephemeral=True,
        )
        return
    if len(configs) == 1:
        user_subscription = None
        try:
            user_id = await get_user_id(interaction.guild_id, interaction.user.id)
            pool = await get_pool()
            async with pool.acquire() as connection:
                user_subscription = await connection.fetchrow(
                    "SELECT is_subscribed, last_checked FROM subscriptions WHERE user_id = $1 AND server_id = $2",
                    user_id,
                    configs[0]["id"],
                )
        except Exception as e:
            logging.error(f"Error checking user subscription: {e}")
        await VerifyChannelSelectView.send_verification_link(
            interaction, configs[0], user_subscription
        )
    else:
        channel_names = {}
        for config in configs:
            channel_names[config["yt_channel_id"]] = await get_youtube_channel_name(
                config["yt_channel_id"]
            )
        view = VerifyChannelSelectView(configs, channel_names)
        await interaction.followup.send(
            embed=discord.Embed(
                description=f"{YT} Select which YouTube channel you have subscribed to:",
                color=COLOR,
            ),
            view=view,
            ephemeral=True,
        )


@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        logging.info(f"Loaded {len(synced)} Discord commands")
    except Exception as e:
        logging.error(f"Failed to sync commands: {e}")
    if not any(task.get_name() == "status_task" for task in asyncio.all_tasks()):
        bot.loop.create_task(bot.status_task(), name="status_task")


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: discord.app_commands.AppCommandError
):
    logging.error(error, exc_info=error)
    await send_error(interaction)


@bot.event
async def on_entitlement_create(entitlement: discord.Entitlement):
    try:
        guild_id = entitlement.guild_id
        if not guild_id:
            return
        guild = bot.get_guild(guild_id)
        if guild:
            try:
                configs = await get_server_configs_for_guild(guild_id)
                embed = discord.Embed(
                    title=f"{PREMIUM} Premium Activated",
                    description=f"Thank you for upgrading to premium in {guild.name}! You can now:\n\n{PREMIUM_PERKS}",
                    color=discord.Color.pink(),
                )
                if configs and configs[0].get("log_channel_id"):
                    channel = bot.get_channel(configs[0]["log_channel_id"])
                    if channel:
                        await channel.send(embed=embed)
                try:
                    user = await bot.fetch_user(entitlement.user_id)
                    await user.send(embed=embed)
                except Exception as e:
                    logging.info(
                        f"Error sending premium DM to user {entitlement.user_id}: {e}"
                    )
            except Exception as e:
                logging.error(f"Error sending premium thank you message: {e}")
        await owner_log(
            "PREMIUM_LOG_CHANNEL_ID",
            f"{PREMIUM} Premium added for {await describe_entitlement(entitlement)}.",
            discord.Color.pink(),
        )
        logging.info(f"Premium entitlement created for guild {guild_id}")
    except Exception as e:
        logging.error(f"Error in on_entitlement_create: {e}")
        logging.exception(e)


@bot.event
async def on_entitlement_update(entitlement: discord.Entitlement):
    if not entitlement.guild_id:
        return
    if entitlement.ends_at:
        status = f"renewed or cancelled, current period ends {discord.utils.format_dt(entitlement.ends_at, 'R')}"
    else:
        status = "updated"
    await owner_log(
        "PREMIUM_LOG_CHANNEL_ID",
        f"{PREMIUM} Premium {status} for {await describe_entitlement(entitlement)}.",
    )


@bot.event
async def on_entitlement_delete(entitlement: discord.Entitlement):
    try:
        guild_id = entitlement.guild_id
        if not guild_id:
            return
        configs = await get_server_configs_for_guild(guild_id)
        if configs:
            if len(configs) > 1:
                for config in configs[1:]:
                    await delete_server_config(config["id"])
            first_config = configs[0]
            await set_server_config(
                guild_id,
                first_config["yt_channel_id"],
                first_config["role_id"],
                first_config["log_channel_id"],
                server_id=first_config["id"],
                verification_dm_content=None,
                unsubscribe_dm_content=None,
            )
        guild = bot.get_guild(guild_id)
        if guild:
            try:
                configs = await get_server_configs_for_guild(guild_id)
                embed = discord.Embed(
                    title=f"{WARN} Premium Expired",
                    description=f"Your premium subscription for {guild.name} has expired or been cancelled. Premium features are no longer available.",
                    color=discord.Color.light_gray(),
                )
                if configs and configs[0].get("log_channel_id"):
                    channel = bot.get_channel(configs[0]["log_channel_id"])
                    if channel:
                        await channel.send(embed=embed)
                try:
                    user = await bot.fetch_user(entitlement.user_id)
                    await user.send(embed=embed)
                except Exception as e:
                    logging.info(
                        f"Error sending premium expiration DM to user {entitlement.user_id}: {e}"
                    )
            except Exception as e:
                logging.error(f"Error sending premium expiration message: {e}")

        await owner_log(
            "PREMIUM_LOG_CHANNEL_ID",
            f"{WARN} Premium removed for {await describe_entitlement(entitlement)}.",
            discord.Color.light_gray(),
        )
        logging.info(f"Premium entitlement deleted for guild {guild_id}")
    except Exception as e:
        logging.error(f"Error in on_entitlement_delete: {e}")
        logging.exception(e)


async def log_action(guild_id: int, message: str, color=COLOR, server_id: int = None):
    server_config = await get_server_config_by_id(server_id)
    if server_config and server_config["log_channel_id"]:
        channel = bot.get_channel(server_config["log_channel_id"])
        if channel:
            embed = discord.Embed(description=message, color=color)
            await channel.send(embed=embed)

import asyncio
import datetime
import hashlib
import hmac
import os
import traceback
import urllib.parse

import discord
from discord.ext import commands, tasks
from discord.ui import Button, ChannelSelect, Modal, RoleSelect, Select, TextInput, View
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from database import (
    claim_account_hash,
    decrypt_token,
    delete_server_config,
    get_all_server_configs,
    get_guild_stats,
    get_pool,
    get_server_config_by_id,
    get_server_configs_for_guild,
    get_tiers,
    get_user_id,
    hash_account,
    set_server_config,
    set_stack_tiers,
    set_tier,
    update_subscription_status,
)
from utils import (
    ADD,
    BIN,
    CHECK,
    COG,
    COLOR,
    CROSS,
    EDIT,
    FLAG,
    HELP,
    HOME,
    INFO,
    LOG,
    MAIL,
    NEUTRAL,
    PREMIUM,
    PREMIUM_PERKS,
    RED_BIN,
    REPLY,
    ROLE,
    SKU_ID,
    TIER_DURATIONS,
    WARN,
    YT,
    get_youtube_channel_name,
    is_guild_premium,
)

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


bot = Bot(command_prefix="!", intents=intents)


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
        print(f"Error sending owner log to {env_var}: {e}")


def describe_guild(guild: discord.Guild) -> str:
    return f"**{discord.utils.escape_markdown(guild.name)}** (`{guild.id}`, {guild.member_count or 0} members)"


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


@bot.event
async def on_guild_remove(guild: discord.Guild):
    await owner_log(
        "GUILD_LOG_CHANNEL_ID",
        f"{CROSS} Left {describe_guild(guild)}. Now in {len(bot.guilds)} servers.",
        discord.Color.red(),
    )


@bot.event
async def on_app_command_completion(
    interaction: discord.Interaction, command: discord.app_commands.Command
):
    where = describe_guild(interaction.guild) if interaction.guild else "a DM"
    await owner_log(
        "COMMAND_LOG_CHANNEL_ID",
        f"{ADD} `/{command.qualified_name}`\n{ROLE} <@{interaction.user.id}>\n{LOG} {where}.",
    )


class YouTubeChannelModal(Modal, title="Set YouTube Channel"):
    def __init__(self, parent_view: "ConfigurationEditView", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.parent_view = parent_view
        self.channel_id = TextInput(
            label="YouTube Channel ID",
            placeholder="e.g., UCxxxxxxxxxxxxxxxxxxxxxx",
            required=True,
            min_length=1,
            max_length=24,
            default=parent_view.yt_channel_id,
        )
        self.add_item(self.channel_id)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer()
            channel_id = self.channel_id.value.strip()
            if not channel_id.startswith("UC"):
                await interaction.followup.send(
                    embed=discord.Embed(
                        description=f"{CROSS} Invalid YouTube channel ID. It must start with 'UC'.\n{REPLY} *[How to find my Channel ID?](https://support.google.com/youtube/answer/3250431)* {INFO}",
                        color=COLOR,
                    ),
                    ephemeral=True,
                )
                return
            if len(channel_id) != 24:
                await interaction.followup.send(
                    embed=discord.Embed(
                        description=f"{CROSS} Invalid YouTube channel ID. It must be `24` characters long.\n{REPLY} *[How to find my Channel ID?](https://support.google.com/youtube/answer/3250431)* {INFO}",
                        color=COLOR,
                    ),
                    ephemeral=True,
                )
                return
            self.parent_view.yt_channel_id = channel_id
            self.parent_view.last_interaction = interaction
            if self.parent_view.yt_channel_id and self.parent_view.role_id:
                self.parent_view.server_id = await set_server_config(
                    self.parent_view.guild_id,
                    self.parent_view.yt_channel_id,
                    self.parent_view.role_id,
                    self.parent_view.channel_id,
                    server_id=self.parent_view.server_id,
                )
            await self.parent_view.update_config_display()
        except Exception as e:
            print(f"Error in YouTubeChannelModal.on_submit: {e}")
            import traceback

            traceback.print_exc()


class VerificationDMModal(Modal, title="Set Verification Message"):
    def __init__(self, parent_view: "ConfigurationEditView", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.parent_view = parent_view
        self.message_content = TextInput(
            label="Verification DM Content",
            placeholder="Leave blank to disable. This will be the embed description.",
            required=False,
            min_length=0,
            max_length=500,
            default=parent_view.verification_dm_content or "",
        )
        self.add_item(self.message_content)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer()
            content = (
                self.message_content.value.strip()
                if self.message_content.value
                else None
            )
            self.parent_view.verification_dm_content = content
            self.parent_view.last_interaction = interaction
            if self.parent_view.yt_channel_id and self.parent_view.role_id:
                self.parent_view.server_id = await set_server_config(
                    self.parent_view.guild_id,
                    self.parent_view.yt_channel_id,
                    self.parent_view.role_id,
                    self.parent_view.channel_id,
                    server_id=self.parent_view.server_id,
                    verification_dm_content=self.parent_view.verification_dm_content,
                    unsubscribe_dm_content=self.parent_view.unsubscribe_dm_content,
                )
            await self.parent_view.update_config_display()
        except Exception as e:
            print(f"Error in VerificationDMModal.on_submit: {e}")
            traceback.print_exc()


class UnsubscribeDMModal(Modal, title="Set Unsubscribe Notification"):
    def __init__(self, parent_view: "ConfigurationEditView", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.parent_view = parent_view
        self.message_content = TextInput(
            label="Unsubscribe DM Content",
            placeholder="Leave blank to disable. This will be the embed description.",
            required=False,
            min_length=0,
            max_length=500,
            default=parent_view.unsubscribe_dm_content or "",
        )
        self.add_item(self.message_content)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer()
            content = (
                self.message_content.value.strip()
                if self.message_content.value
                else None
            )
            self.parent_view.unsubscribe_dm_content = content
            self.parent_view.last_interaction = interaction
            if self.parent_view.yt_channel_id and self.parent_view.role_id:
                self.parent_view.server_id = await set_server_config(
                    self.parent_view.guild_id,
                    self.parent_view.yt_channel_id,
                    self.parent_view.role_id,
                    self.parent_view.channel_id,
                    server_id=self.parent_view.server_id,
                    verification_dm_content=self.parent_view.verification_dm_content,
                    unsubscribe_dm_content=self.parent_view.unsubscribe_dm_content,
                )
            await self.parent_view.update_config_display()
        except Exception as e:
            print(f"Error in UnsubscribeDMModal.on_submit: {e}")
            traceback.print_exc()


class ConfigurationEditView(View):
    def __init__(
        self, guild_id: int, server_id: int = None, initial_config: dict = None
    ):
        super().__init__()
        self.guild_id = guild_id
        self.server_id = server_id
        self.role_id = initial_config.get("role_id") if initial_config else None
        self.channel_id = (
            initial_config.get("log_channel_id") if initial_config else None
        )
        self.yt_channel_id = (
            initial_config.get("yt_channel_id") if initial_config else None
        )
        self.verification_dm_content = (
            initial_config.get("verification_dm_content") if initial_config else None
        )
        self.unsubscribe_dm_content = (
            initial_config.get("unsubscribe_dm_content") if initial_config else None
        )
        self.current_modal = None
        self.last_interaction = None

    async def get_status_embed(self) -> discord.Embed:
        title = (
            f"{EDIT} Edit Existing Configuration"
            if self.server_id
            else f"{ADD} Add New Configuration"
        )
        embed = discord.Embed(title=title, color=COLOR)
        if self.yt_channel_id:
            yt_url = f"https://www.youtube.com/channel/{self.yt_channel_id}"
            channel_name = await get_youtube_channel_name(self.yt_channel_id)
            yt_status = f"{CHECK} [{channel_name}]({yt_url})"
        else:
            yt_status = f"{CROSS} Not set. [How to find my Channel ID?](https://support.google.com/youtube/answer/3250431)."
        embed.add_field(name=f"YouTube Channel {YT}", value=yt_status, inline=False)
        role_status = (
            f"{CHECK} <@&{self.role_id}>" if self.role_id else f"{CROSS} Not set"
        )
        embed.add_field(name=f"Subscriber Role {ROLE}", value=role_status, inline=False)
        channel_status = (
            f"{CHECK} <#{self.channel_id}>" if self.channel_id else f"{CROSS} Not set"
        )
        embed.add_field(name=f"Log Channel {LOG}", value=channel_status, inline=False)
        verification_status = (
            f"{self.verification_dm_content}"
            if self.verification_dm_content
            else f"{CROSS} Disabled"
        )
        embed.add_field(
            name=f"Success Message {MAIL} {PREMIUM}",
            value=verification_status,
            inline=False,
        )
        unsubscribe_status = (
            f"{self.unsubscribe_dm_content}"
            if self.unsubscribe_dm_content
            else f"{CROSS} Disabled"
        )
        embed.add_field(
            name=f"Unsubscribe Notification {FLAG} {PREMIUM}",
            value=unsubscribe_status,
            inline=False,
        )
        tiers = await get_tiers(self.server_id) if self.server_id else []
        embed.add_field(
            name=f"Tier Roles {ROLE} {PREMIUM}",
            value=(
                " ".join(f"<@&{tier['role_id']}>" for tier in tiers)
                if tiers
                else f"{CROSS} Disabled"
            ),
            inline=False,
        )
        return embed

    async def update_config_display(self):
        if not self.last_interaction:
            return
        embed = await self.get_status_embed()
        try:
            await self.last_interaction.edit_original_response(embed=embed, view=self)
        except Exception as e:
            print(f"Error updating config display: {e}")

    @discord.ui.select(cls=RoleSelect, placeholder="Pick a subscriber role")
    async def select_role(self, interaction: discord.Interaction, select: Select):
        try:
            selected_role = select.values[0]
            bot_member = await interaction.guild.fetch_member(
                interaction.client.user.id
            )
            bot_top_role = bot_member.top_role
            if not interaction.guild.me.guild_permissions.manage_roles:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        description=f"{CROSS} The bot does not have the 'Manage Roles' permission in this server.",
                        color=COLOR,
                    ),
                    ephemeral=True,
                )
                return
            if selected_role.position >= bot_top_role.position:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        description=f"{CROSS} The bot cannot manage this role. Please move the bot's role above this role first.",
                        color=COLOR,
                    ),
                    ephemeral=True,
                )
                return
            self.role_id = selected_role.id
            self.last_interaction = interaction
            await interaction.response.defer()
            if self.yt_channel_id and self.role_id:
                self.server_id = await set_server_config(
                    self.guild_id,
                    self.yt_channel_id,
                    self.role_id,
                    self.channel_id,
                    server_id=self.server_id,
                    verification_dm_content=self.verification_dm_content,
                    unsubscribe_dm_content=self.unsubscribe_dm_content,
                )
            await self.update_config_display()
        except Exception as e:
            print(f"Error in select_role: {e}")

    @discord.ui.select(
        cls=ChannelSelect, placeholder="Pick a log channel", min_values=1, max_values=1
    )
    async def select_channel(self, interaction: discord.Interaction, select: Select):
        try:
            channel = select.values[0]
            actual_channel = interaction.guild.get_channel(channel.id)
            bot_perms = actual_channel.permissions_for(interaction.guild.me)
            if not bot_perms.send_messages or not bot_perms.embed_links:
                missing_perms = []
                if not bot_perms.send_messages:
                    missing_perms.append("Send Messages")
                if not bot_perms.embed_links:
                    missing_perms.append("Embed Links")
                await interaction.response.send_message(
                    embed=discord.Embed(
                        description=f"{CROSS} Bot is missing permissions in {channel.mention}: {', '.join(missing_perms)}",
                        color=COLOR,
                    ),
                    ephemeral=True,
                )
                return
            self.channel_id = channel.id
            self.last_interaction = interaction
            await interaction.response.defer()
            if self.yt_channel_id and self.role_id:
                self.server_id = await set_server_config(
                    self.guild_id,
                    self.yt_channel_id,
                    self.role_id,
                    self.channel_id,
                    server_id=self.server_id,
                    verification_dm_content=self.verification_dm_content,
                    unsubscribe_dm_content=self.unsubscribe_dm_content,
                )
            await self.update_config_display()
        except Exception as e:
            print(f"Error in select_channel: {e}")

    @discord.ui.button(
        label="Set YouTube Channel", emoji=YT, style=discord.ButtonStyle.grey, row=2
    )
    async def set_channel(self, interaction: discord.Interaction, button: Button):
        try:
            modal = YouTubeChannelModal(self, title="Configure YouTube Channel")
            self.last_interaction = interaction
            await interaction.response.send_modal(modal)
        except Exception as e:
            print(f"Error in set_channel: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=discord.Embed(description=f"{CROSS} Error: {e}", color=COLOR),
                    ephemeral=True,
                )

    @discord.ui.button(
        label="Set Success Message", emoji=MAIL, style=discord.ButtonStyle.grey, row=2
    )
    async def set_verification_dm(
        self, interaction: discord.Interaction, button: Button
    ):
        try:
            has_premium = await is_guild_premium(interaction)
            if not has_premium:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        description=f"{PREMIUM} This feature is for Premium servers only.",
                        color=COLOR,
                    ),
                    ephemeral=True,
                )
                return
            modal = VerificationDMModal(self, title="Set Verification Message")
            self.last_interaction = interaction
            await interaction.response.send_modal(modal)
        except Exception as e:
            print(f"Error in set_verification_dm: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=discord.Embed(description=f"{CROSS} Error: {e}", color=COLOR),
                    ephemeral=True,
                )

    @discord.ui.button(
        label="Set Unsubscribe Notification",
        emoji=FLAG,
        style=discord.ButtonStyle.grey,
        row=2,
    )
    async def set_unsubscribe_dm(
        self, interaction: discord.Interaction, button: Button
    ):
        try:
            has_premium = await is_guild_premium(interaction)
            if not has_premium:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        description=f"{PREMIUM} This feature is for Premium servers only.",
                        color=COLOR,
                    ),
                    ephemeral=True,
                )
                return
            modal = UnsubscribeDMModal(self, title="Set Unsubscribe Notification")
            self.last_interaction = interaction
            await interaction.response.send_modal(modal)
        except Exception as e:
            print(f"Error in set_unsubscribe_dm: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=discord.Embed(description=f"{CROSS} Error: {e}", color=COLOR),
                    ephemeral=True,
                )

    @discord.ui.button(
        label="Set Tier Roles", emoji=ROLE, style=discord.ButtonStyle.grey, row=2
    )
    async def set_tier_roles(self, interaction: discord.Interaction, button: Button):
        try:
            has_premium = await is_guild_premium(interaction)
            if not has_premium:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        description=f"{PREMIUM} This feature is for Premium servers only.",
                        color=COLOR,
                    ),
                    ephemeral=True,
                )
                return
            if not self.server_id:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        description=f"{CROSS} Set the YouTube channel and subscriber role first.",
                        color=COLOR,
                    ),
                    ephemeral=True,
                )
                return
            config = await get_server_config_by_id(self.server_id)
            view = TierRolesView(
                self, await get_tiers(self.server_id), config["stack_tiers"]
            )
            await interaction.response.edit_message(embed=view.get_embed(), view=view)
        except Exception as e:
            print(f"Error in set_tier_roles: {e}")

    @discord.ui.button(label="Back", emoji=HOME, style=discord.ButtonStyle.grey, row=2)
    async def back_button(self, interaction: discord.Interaction, button: Button):
        try:
            embed = discord.Embed(
                title=f"{COG} Server Configuration",
                description="Choose an action to manage your server's YouTube subscriber role settings",
                color=COLOR,
            )
            view = SetupMainView(self.guild_id)
            await interaction.response.edit_message(embed=embed, view=view)
        except Exception as e:
            print(f"Error in back_button: {e}")


class TierRolesView(View):
    def __init__(self, parent: ConfigurationEditView, tiers, stack: bool):
        super().__init__()
        self.parent = parent
        self.tiers = {tier["days"]: tier["role_id"] for tier in tiers}
        self.stack = stack
        self.days = None
        self.select_duration.options = [
            discord.SelectOption(label=label, value=str(days))
            for days, label in TIER_DURATIONS.items()
        ]

    def get_embed(self) -> discord.Embed:
        lines = [f"`Just now` <@&{self.parent.role_id}>"]
        for days, label in TIER_DURATIONS.items():
            role_status = (
                f"<@&{self.tiers[days]}>" if days in self.tiers else f"{CROSS} Not set"
            )
            lines.append(f"> `{label}` - {role_status}")
        embed = discord.Embed(
            title=f"{ROLE} Tier Roles",
            description="Reward members for how long they have been subscribed. Select a duration, then select the role to give.\n\n"
            + "\n".join(lines),
            color=COLOR,
        )
        embed.add_field(
            name=f"Stack Roles {EDIT}",
            value=(
                f"{CHECK} Members keep every tier role they have reached"
                if self.stack
                else f"{CROSS} Members only keep their highest tier role"
            ),
            inline=False,
        )
        return embed

    @discord.ui.select(placeholder="Select a duration", row=0)
    async def select_duration(self, interaction: discord.Interaction, select: Select):
        self.days = int(select.values[0])
        for option in select.options:
            option.default = option.value == select.values[0]
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.select(
        cls=RoleSelect, placeholder="Select a role for that duration", row=1
    )
    async def select_role(self, interaction: discord.Interaction, select: Select):
        try:
            role = select.values[0]
            if self.days is None:
                message = "Select a duration first."
            elif role.is_default() or role.managed:
                message = "This role cannot be assigned to members."
            elif role.position >= interaction.guild.me.top_role.position:
                message = "The bot cannot manage this role. Please move the bot's role above this role first."
            else:
                await set_tier(self.parent.server_id, self.days, role.id)
                self.tiers[self.days] = role.id
                await interaction.response.edit_message(
                    embed=self.get_embed(), view=self
                )
                return
            await interaction.response.send_message(
                embed=discord.Embed(description=f"{CROSS} {message}", color=COLOR),
                ephemeral=True,
            )
        except Exception as e:
            print(f"Error in select_role: {e}")

    @discord.ui.button(
        label="Remove Tier", emoji=BIN, style=discord.ButtonStyle.grey, row=2
    )
    async def remove_tier(self, interaction: discord.Interaction, button: Button):
        if self.days in self.tiers:
            await set_tier(self.parent.server_id, self.days)
            del self.tiers[self.days]
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(
        label="Stack Roles", emoji=EDIT, style=discord.ButtonStyle.grey, row=2
    )
    async def toggle_stack(self, interaction: discord.Interaction, button: Button):
        self.stack = not self.stack
        await set_stack_tiers(self.parent.server_id, self.stack)
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="Back", emoji=HOME, style=discord.ButtonStyle.grey, row=2)
    async def back_button(self, interaction: discord.Interaction, button: Button):
        self.parent.last_interaction = interaction
        embed = await self.parent.get_status_embed()
        await interaction.response.edit_message(embed=embed, view=self.parent)


class ConfigSelectView(View):
    def __init__(self, configs, callback, guild_id: int, channel_names: dict = None):
        super().__init__()
        self.configs = configs
        self.callback = callback
        self.guild_id = guild_id
        self.channel_names = channel_names or {}
        options = []
        for i, config in enumerate(configs):
            channel_name = self.channel_names.get(
                config["yt_channel_id"], config["yt_channel_id"]
            )
            options.append(
                discord.SelectOption(
                    label=f"{channel_name}",
                    value=str(config["id"]),
                    description=f"{config['yt_channel_id']}",
                )
            )
        select = Select(placeholder="Select a configuration", options=options)
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        server_id = int(interaction.data["values"][0])
        await self.callback(interaction, server_id)

    @discord.ui.button(label="Back", emoji=HOME, style=discord.ButtonStyle.grey, row=1)
    async def back_button(self, interaction: discord.Interaction, button: Button):
        try:
            embed = discord.Embed(
                title=f"{COG} Server Configuration",
                description="Choose an action to manage your server's YouTube subscriber role settings",
                color=COLOR,
            )
            view = SetupMainView(self.guild_id)
            await interaction.response.edit_message(
                embed=embed, view=view, content=None
            )
        except Exception as e:
            print(f"Error in back_button: {e}")


class ConfirmDeleteView(View):
    def __init__(self, guild_id: int, server_id: int):
        super().__init__()
        self.guild_id = guild_id
        self.server_id = server_id

    @discord.ui.button(
        label="Yes, Delete", emoji=RED_BIN, style=discord.ButtonStyle.grey
    )
    async def yes_delete(self, interaction: discord.Interaction, button: Button):
        await delete_server_config(self.server_id)
        await interaction.response.edit_message(
            content=None,
            embed=discord.Embed(
                description=f"{BIN} Configuration successfully deleted!", color=COLOR
            ),
            view=None,
        )
        self.stop()

    @discord.ui.button(label="Back", emoji=HOME, style=discord.ButtonStyle.grey)
    async def back_button(self, interaction: discord.Interaction, button: Button):
        try:
            embed = discord.Embed(
                title=f"{COG} Server Configuration",
                description="Choose an action to manage your server's YouTube subscriber role settings",
                color=COLOR,
            )
            view = SetupMainView(self.guild_id)
            await interaction.response.edit_message(embed=embed, view=view)
        except Exception as e:
            print(f"Error in back_button: {e}")


class SetupMainView(View):
    def __init__(self, guild_id: int):
        super().__init__()
        self.guild_id = guild_id

    @discord.ui.button(label="Add New", emoji=ADD, style=discord.ButtonStyle.grey)
    async def add_config(self, interaction: discord.Interaction, button: Button):
        try:
            configs = await get_server_configs_for_guild(self.guild_id)
            has_premium = await is_guild_premium(interaction)
            max_configs = 5 if has_premium else 1
            if len(configs) >= max_configs:
                if not has_premium:
                    await interaction.response.send_message(
                        embed=discord.Embed(
                            description=f"{CROSS} You have reached the maximum number of configurations ({max_configs}). Upgrade to {PREMIUM} premium for a total of {max_configs * 5} configurations.",
                            color=COLOR,
                        ),
                        ephemeral=True,
                    )
                else:
                    await interaction.response.send_message(
                        embed=discord.Embed(
                            description=f"{CROSS} You have reached the maximum number of configurations ({max_configs}). Remove some configurations to add more.",
                            color=COLOR,
                        ),
                        ephemeral=True,
                    )
                return
            view = ConfigurationEditView(self.guild_id)
            embed = await view.get_status_embed()
            await interaction.response.edit_message(embed=embed, view=view)
        except Exception as e:
            print(f"Error in add_config: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=discord.Embed(
                        description=f"{CROSS} An error occurred: {e}", color=COLOR
                    ),
                    ephemeral=True,
                )

    @discord.ui.button(
        label="Edit Existing", emoji=EDIT, style=discord.ButtonStyle.grey
    )
    async def edit_config(self, interaction: discord.Interaction, button: Button):
        try:
            configs = await get_server_configs_for_guild(self.guild_id)
            if not configs:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        description=f"{CROSS} No configurations found.", color=COLOR
                    ),
                    ephemeral=True,
                )
                return
            if len(configs) == 1:
                await self.show_edit_page(interaction, configs[0]["id"])
            else:
                channel_names = {}
                for config in configs:
                    channel_names[config["yt_channel_id"]] = (
                        await get_youtube_channel_name(config["yt_channel_id"])
                    )
                select_view = ConfigSelectView(
                    configs,
                    self.on_config_selected_for_edit,
                    self.guild_id,
                    channel_names,
                )
                await interaction.response.edit_message(
                    content=None,
                    embed=discord.Embed(
                        title=f"{EDIT} Select Configuration",
                        description=f"Choose from the `{len(configs)}` existing configuration{'s' if len(configs) > 1 else ''} to edit.",
                        color=COLOR,
                    ),
                    view=select_view,
                )
        except Exception as e:
            print(f"Error in edit_config: {e}")

    async def on_config_selected_for_edit(
        self, interaction: discord.Interaction, server_id: int
    ):
        await self.show_edit_page(interaction, server_id)

    async def show_edit_page(self, interaction: discord.Interaction, server_id: int):
        try:
            config = await get_server_config_by_id(server_id)
            view = ConfigurationEditView(
                interaction.guild_id, server_id, initial_config=config
            )
            embed = await view.get_status_embed()
            if interaction.response.is_done():
                await interaction.edit_original_response(
                    content=None, embed=embed, view=view
                )
            else:
                await interaction.response.edit_message(
                    content=None, embed=embed, view=view
                )
        except Exception as e:
            print(f"Error in show_edit_page: {e}")

    @discord.ui.button(
        label="Delete Existing", emoji=BIN, style=discord.ButtonStyle.grey
    )
    async def delete_config(self, interaction: discord.Interaction, button: Button):
        try:
            configs = await get_server_configs_for_guild(self.guild_id)
            if not configs:
                await interaction.response.send_message(
                    embed=discord.Embed(
                        description=f"{CROSS} No configurations found.", color=COLOR
                    ),
                    ephemeral=True,
                )
                return
            if len(configs) == 1:
                confirm_view = ConfirmDeleteView(self.guild_id, configs[0]["id"])
                channel_name = await get_youtube_channel_name(
                    configs[0]["yt_channel_id"]
                )
                embed = discord.Embed(
                    title=f"{WARN} Confirm Deletion",
                    description=f"Are you sure you want to delete this configuration?",
                    color=COLOR,
                )
                embed.add_field(
                    name=f"YouTube Channel {YT}",
                    value=f"[{channel_name}](https://www.youtube.com/channel/{configs[0]['yt_channel_id']})",
                    inline=False,
                )
                embed.add_field(
                    name=f"Subscriber Role {ROLE}",
                    value=f"<@&{configs[0]['role_id']}>",
                    inline=False,
                )
                embed.add_field(
                    name=f"Log Channel {LOG}",
                    value=f"<#{configs[0]['log_channel_id']}>",
                    inline=False,
                )
                verification_status = (
                    f"{configs[0]['verification_dm_content']}"
                    if configs[0].get("verification_dm_content")
                    else f"{CROSS} Disabled"
                )
                embed.add_field(
                    name=f"Success Message {MAIL} {PREMIUM}",
                    value=verification_status,
                    inline=False,
                )
                unsubscribe_status = (
                    f"{configs[0]['unsubscribe_dm_content']}"
                    if configs[0].get("unsubscribe_dm_content")
                    else f"{CROSS} Disabled"
                )
                embed.add_field(
                    name=f"Unsubscribe Notification {FLAG} {PREMIUM}",
                    value=unsubscribe_status,
                    inline=False,
                )
                await interaction.response.edit_message(embed=embed, view=confirm_view)
            else:
                channel_names = {}
                for config in configs:
                    channel_names[config["yt_channel_id"]] = (
                        await get_youtube_channel_name(config["yt_channel_id"])
                    )
                select_view = ConfigSelectView(
                    configs,
                    self.on_config_selected_for_delete,
                    self.guild_id,
                    channel_names,
                )
                await interaction.response.edit_message(
                    content=None,
                    embed=discord.Embed(
                        title=f"{BIN} Select Configuration",
                        description=f"Choose from the `{len(configs)}` existing configuration{'s' if len(configs) > 1 else ''} to delete.",
                        color=COLOR,
                    ),
                    view=select_view,
                )
        except Exception as e:
            print(f"Error in delete_config: {e}")

    async def on_config_selected_for_delete(
        self, interaction: discord.Interaction, server_id: int
    ):
        try:
            config = await get_server_config_by_id(server_id)
            channel_name = await get_youtube_channel_name(config["yt_channel_id"])
            confirm_view = ConfirmDeleteView(interaction.guild_id, server_id)
            embed = discord.Embed(
                title=f"{WARN} Confirm Deletion",
                description=f"Are you sure you want to delete this configuration?",
                color=COLOR,
            )
            embed.add_field(
                name=f"YouTube Channel {YT}",
                value=f"[{channel_name}](https://www.youtube.com/channel/{config['yt_channel_id']})",
                inline=False,
            )
            embed.add_field(
                name=f"Subscriber Role {ROLE}",
                value=f"<@&{config['role_id']}>",
                inline=False,
            )
            embed.add_field(
                name=f"Log Channel {LOG}",
                value=f"<#{config['log_channel_id']}>",
                inline=False,
            )
            verification_status = (
                f"{config['verification_dm_content']}"
                if config.get("verification_dm_content")
                else f"{CROSS} Disabled"
            )
            embed.add_field(
                name=f"Success Message {MAIL} {PREMIUM}",
                value=verification_status,
                inline=False,
            )
            unsubscribe_status = (
                f"{config['unsubscribe_dm_content']}"
                if config.get("unsubscribe_dm_content")
                else f"{CROSS} Disabled"
            )
            embed.add_field(
                name=f"Unsubscribe Notification {FLAG} {PREMIUM}",
                value=unsubscribe_status,
                inline=False,
            )
            await interaction.response.edit_message(
                content=None, embed=embed, view=confirm_view
            )
        except Exception as e:
            print(f"Error in on_config_selected_for_delete: {e}")

    @discord.ui.button(label="Statistics", emoji=INFO, style=discord.ButtonStyle.grey)
    async def statistics(self, interaction: discord.Interaction, button: Button):
        rows = await get_guild_stats(self.guild_id)
        if not rows:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"{CROSS} No configurations found.", color=COLOR
                ),
                ephemeral=True,
            )
            return
        embed = discord.Embed(title=f"{INFO} Statistics", color=COLOR)
        for row in rows:
            channel_name = await get_youtube_channel_name(row["yt_channel_id"])
            last_checked = (
                f"<t:{int(row['last_checked'].timestamp())}:R>"
                if row["last_checked"]
                else "Never"
            )
            embed.add_field(
                name=f"{channel_name} {YT}",
                value=f"{CHECK} `{row['verified']:,}` verified, `{row['subscribed']:,}` subscribed now\n{ADD} `{row['new_week']:,}` new in 7 days, `{row['new_month']:,}` in 30 days\n{NEUTRAL} `{row['lost_month']:,}` unsubscribed in 30 days\n{FLAG} Last checked {last_checked}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(
    name="setup", description="Configure the bot for your server. (Admin only)"
)
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


class VerifyChannelSelectView(View):
    def __init__(self, configs, channel_names: dict = None):
        super().__init__()
        self.configs = configs
        self.channel_names = channel_names or {}
        options = []
        for i, config in enumerate(configs):
            channel_name = self.channel_names.get(
                config["yt_channel_id"], config["yt_channel_id"]
            )
            options.append(
                discord.SelectOption(
                    label=f"{channel_name}",
                    value=str(config["id"]),
                    description=f"{config['yt_channel_id']}",
                )
            )
        select = Select(
            placeholder="Select YouTube channel to get role for", options=options
        )
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        server_id = int(interaction.data["values"][0])
        config = next(c for c in self.configs if c["id"] == server_id)
        user_subscription = None
        try:
            user_id = await get_user_id(interaction.guild_id, interaction.user.id)
            pool = await get_pool()
            async with pool.acquire() as connection:
                user_subscription = await connection.fetchrow(
                    "SELECT is_subscribed, last_checked FROM subscriptions WHERE user_id = $1 AND server_id = $2",
                    user_id,
                    server_id,
                )
        except Exception as e:
            print(f"Error checking user subscription: {e}")
        await self.send_verification_link(interaction, config, user_subscription)

    @staticmethod
    async def send_verification_link(
        interaction: discord.Interaction, config, user_subscription=None
    ):
        guild_id = interaction.guild_id
        client_id = os.environ.get("GOOGLE_CLIENT_ID")
        redirect_uri = os.environ.get(
            "OAUTH_REDIRECT_URI", "http://subscriber.iancheung.dev/callback"
        )
        state_secret = os.environ.get("STATE_SECRET")
        if not state_secret:
            await interaction.followup.send(
                embed=discord.Embed(
                    description=f"{CROSS} Server configuration error. Please try again later.",
                    color=COLOR,
                ),
                ephemeral=True,
            )
            return
        state_data = f"{guild_id}_{interaction.user.id}_{config['id']}"
        signature = hmac.new(
            state_secret.encode(), state_data.encode(), hashlib.sha256
        ).hexdigest()
        state = f"{state_data}.{signature}"
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "https://www.googleapis.com/auth/youtube.readonly",
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(
            params
        )
        yt_channel_id = config["yt_channel_id"]
        yt_channel_url = f"https://www.youtube.com/channel/{yt_channel_id}"
        channel_name = await get_youtube_channel_name(yt_channel_id)
        embed = discord.Embed(
            title=f"YouTube Account Verification {HELP}",
            description=f"1. Make sure you are **subscribed** to [{channel_name}]({yt_channel_url}) first!\n2. Click **[HERE]({url})** to link your YouTube account and get your subscriber role.\n3. *You will be redirected to Google to authorize access.*",
            color=COLOR,
        )
        embeds = [embed]
        if user_subscription:
            status_emoji = (
                f"{CHECK}" if user_subscription["is_subscribed"] else f"{CROSS}"
            )
            last_checked = (
                f"{FLAG} <t:{int(user_subscription['last_checked'].timestamp())}>"
                if user_subscription["last_checked"]
                else f"{FLAG} Never"
            )
            status_embed = discord.Embed(
                title=f"Your Verification Status {INFO}",
                color=(
                    discord.Color.green()
                    if user_subscription["is_subscribed"]
                    else discord.Color.red()
                ),
            )
            status_embed.add_field(
                name=f"Status",
                value=f"{status_emoji} {'Subscribed' if user_subscription['is_subscribed'] else 'Not Subscribed'}",
                inline=False,
            )
            status_embed.add_field(
                name=f"Last Checked", value=last_checked, inline=False
            )
            embeds.append(status_embed)
        await interaction.response.send_message(embeds=embeds, ephemeral=True)


@bot.tree.command(
    name="verify", description="Link your YouTube account to verify your subscription."
)
async def verify(interaction: discord.Interaction):
    configs = await get_server_configs_for_guild(interaction.guild_id)
    if not configs:
        await interaction.response.send_message(
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
            print(f"Error checking user subscription: {e}")
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
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"{YT} Select which YouTube channel you have subscribed to:",
                color=COLOR,
            ),
            view=view,
            ephemeral=True,
        )


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"Loaded {len(synced)} Discord commands")
    except Exception as e:
        print(f"Failed to sync commands: {e}")
    if not sync_roles.is_running():
        sync_roles.start()
    if not any(task.get_name() == "status_task" for task in asyncio.all_tasks()):
        bot.loop.create_task(bot.status_task())


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: discord.app_commands.AppCommandError
):
    traceback.print_exception(type(error), error, error.__traceback__)
    if not interaction.response.is_done():
        await interaction.response.send_message(
            f"An error occurred: {error}", ephemeral=True
        )


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
                    print(
                        f"Error sending premium DM to user {entitlement.user_id}: {e}"
                    )
            except Exception as e:
                print(f"Error sending premium thank you message: {e}")
        await owner_log(
            "PREMIUM_LOG_CHANNEL_ID",
            f"{PREMIUM} Premium added for {await describe_entitlement(entitlement)}.",
            discord.Color.pink(),
        )
        print(f"Premium entitlement created for guild {guild_id}")
    except Exception as e:
        print(f"Error in on_entitlement_create: {e}")
        traceback.print_exc()


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
                    print(
                        f"Error sending premium expiration DM to user {entitlement.user_id}: {e}"
                    )
            except Exception as e:
                print(f"Error sending premium expiration message: {e}")

        await owner_log(
            "PREMIUM_LOG_CHANNEL_ID",
            f"{WARN} Premium removed for {await describe_entitlement(entitlement)}.",
            discord.Color.light_gray(),
        )
        print(f"Premium entitlement deleted for guild {guild_id}")
    except Exception as e:
        print(f"Error in on_entitlement_delete: {e}")
        traceback.print_exc()


async def log_action(guild_id: int, message: str, color=COLOR, server_id: int = None):
    server_config = await get_server_config_by_id(server_id)
    if server_config and server_config["log_channel_id"]:
        channel = bot.get_channel(server_config["log_channel_id"])
        if channel:
            embed = discord.Embed(description=message, color=color)
            await channel.send(embed=embed)


SYNC_DAILY_LIMIT = int(os.environ.get("SYNC_DAILY_LIMIT") or 9000)
SYNC_BATCH_SIZE = 5
SYNC_RECHECK_HOURS = 20
PREMIUM_RECHECK_HOURS = 10
QUOTA_REASONS = ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded")


class QuotaExhausted(Exception):
    pass


def check_subscription(refresh_token: str, yt_channel_id: str, discord_id: int):
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
    )
    try:
        youtube = build("youtube", "v3", credentials=creds)
        req = youtube.subscriptions().list(
            part="snippet", mine=True, forChannelId=yt_channel_id
        )
        res = req.execute()
        items = res.get("items", [])
        return items[0]["snippet"] if items else False
    except RefreshError as e:
        if "invalid_grant" in str(e):
            return False
        print(f"Could not refresh token for {discord_id}: {e}")
        return None
    except HttpError as e:
        if any(reason in str(e) for reason in QUOTA_REASONS):
            raise QuotaExhausted(str(e))
        print(f"Error for {discord_id}: {e}")
        return None
    except Exception as e:
        print(f"Error for {discord_id}: {e}")
        return None


async def sync_tier_roles(member, guild, config, tiers, channel_name, snippet):
    roles = [
        (tier["days"], guild.get_role(tier["role_id"]))
        for tier in tiers
        if guild.get_role(tier["role_id"])
    ]
    earned = []
    if snippet and snippet.get("publishedAt"):
        since = datetime.datetime.fromisoformat(
            snippet["publishedAt"].replace("Z", "+00:00")
        )
        age = (datetime.datetime.now(datetime.timezone.utc) - since).days
        earned = [role for days, role in roles if age >= days]
    wanted = earned if config["stack_tiers"] else earned[-1:]
    added = [role for role in wanted if role not in member.roles]
    removed = [role for _, role in roles if role in member.roles and role not in wanted]
    try:
        if added:
            await member.add_roles(*added)
            await log_action(
                config["guild_id"],
                f"{CHECK} Added {' '.join(role.mention for role in added)} to <@{member.id}> for how long they have been subscribed to [{channel_name}](https://www.youtube.com/channel/{config['yt_channel_id']}).",
                discord.Color.green(),
                server_id=config["id"],
            )
        if removed:
            await member.remove_roles(*removed)
    except Exception as e:
        print(f"Error syncing tier roles for {member.id}: {e}")


async def sync_member(row, target: dict, stats: dict):
    config = target["config"]
    guild = target["guild"]
    role = target["role"]
    channel_name = target["channel_name"]
    server_id = config["id"]
    guild_id = config["guild_id"]
    yt_channel_id = config["yt_channel_id"]
    yt_channel_url = f"https://www.youtube.com/channel/{yt_channel_id}"
    user_id = row["user_id"]
    discord_id = row["discord_id"]
    refresh_token = decrypt_token(row["refresh_token"])
    if not refresh_token:
        return
    snippet = await asyncio.to_thread(
        check_subscription, refresh_token, yt_channel_id, discord_id
    )
    if snippet is None:
        stats["failed"] += 1
        return
    is_subscribed = bool(snippet)
    if is_subscribed and not row["yt_account_hash"] and snippet.get("channelId"):
        await claim_account_hash(user_id, guild_id, hash_account(snippet["channelId"]))
    try:
        member = await guild.fetch_member(discord_id)
    except discord.errors.NotFound:
        member = None
    if member:
        has_role = role in member.roles
        if not is_subscribed and has_role:
            try:
                await member.remove_roles(role)
                stats["removed"] += 1
                if config.get("unsubscribe_dm_content"):
                    try:
                        dm_embed = discord.Embed(
                            description=config["unsubscribe_dm_content"],
                            color=0xAF4875,
                        )
                        dm_embed.set_footer(text=f"Sent from {guild.name}")
                        await member.send(embed=dm_embed)
                    except Exception as e:
                        print(f"Error sending unsubscribe DM to {discord_id}: {e}")
                try:
                    await log_action(
                        guild_id,
                        f"{NEUTRAL} Removed {role.mention} from <@{discord_id}> because they are no longer subscribed to [{channel_name}]({yt_channel_url}).",
                        discord.Color.red(),
                        server_id=server_id,
                    )
                except Exception as e:
                    print(f"Role removed but failed to log: {e}")
            except discord.errors.Forbidden:
                print(f"Failed to remove role from {discord_id}: Bot lacks permission.")
                try:
                    await log_action(
                        guild_id,
                        f"{CROSS} Attempted to remove {role.mention} from <@{discord_id}> for [{channel_name}]({yt_channel_url}) but bot lacks permission in role hierarchy.",
                        discord.Color.orange(),
                        server_id=server_id,
                    )
                except Exception:
                    pass
        if is_subscribed and not has_role:
            try:
                await member.add_roles(role)
                stats["added"] += 1
                try:
                    await log_action(
                        guild_id,
                        f"{CHECK} Added {role.mention} to <@{discord_id}> because they subscribed to [{channel_name}]({yt_channel_url}).",
                        discord.Color.green(),
                        server_id=server_id,
                    )
                except Exception as e:
                    print(f"Role added but failed to log: {e}")
            except discord.errors.Forbidden:
                print(f"Failed to add role to {discord_id}: Bot lacks permission.")
                try:
                    await log_action(
                        guild_id,
                        f"{CROSS} Attempted to add {role.mention} to <@{discord_id}> for [{channel_name}]({yt_channel_url}) but bot lacks permission in role hierarchy.",
                        discord.Color.orange(),
                        server_id=server_id,
                    )
                except Exception:
                    pass
        if target["tiers"]:
            await sync_tier_roles(
                member, guild, config, target["tiers"], channel_name, snippet
            )
    await update_subscription_status(user_id, server_id, yt_channel_id, is_subscribed)
    stats["checked"] += 1


async def get_premium_guild_ids() -> set:
    if not SKU_ID:
        return set()
    try:
        return {
            entitlement.guild_id
            async for entitlement in bot.entitlements(limit=None, exclude_ended=True)
            if entitlement.sku_id == SKU_ID and entitlement.guild_id
        }
    except Exception as e:
        print(f"Error fetching premium guilds: {e}")
        return set()


async def run_sync() -> dict:
    stats = {
        "checked": 0,
        "removed": 0,
        "added": 0,
        "failed": 0,
        "remaining": 0,
        "quota_hit": False,
    }
    targets = {}
    for config in await get_all_server_configs():
        guild = bot.get_guild(config["guild_id"])
        if not guild:
            print(f"Guild {config['guild_id']} not found, skipping...")
            continue
        role = guild.get_role(config["role_id"])
        if not role:
            print(
                f"Role {config['role_id']} not found in guild {config['guild_id']}, skipping..."
            )
            continue
        targets[config["id"]] = {"config": config, "guild": guild, "role": role}
    premium_guilds = await get_premium_guild_ids()
    tiers = await get_tiers()
    for server_id, target in targets.items():
        target["tiers"] = [
            tier
            for tier in tiers
            if tier["server_id"] == server_id
            and target["config"]["guild_id"] in premium_guilds
        ]
    now = datetime.datetime.now()
    pool = await get_pool()
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            "SELECT s.id AS server_id, s.guild_id, u.id AS user_id, u.discord_id, u.refresh_token, u.yt_account_hash, sub.last_checked FROM servers s JOIN users u ON u.guild_id = s.guild_id LEFT JOIN subscriptions sub ON sub.user_id = u.id AND sub.server_id = s.id WHERE u.refresh_token IS NOT NULL AND (sub.last_checked IS NULL OR sub.last_checked < $1) ORDER BY sub.last_checked ASC NULLS FIRST, u.id",
            now - datetime.timedelta(hours=PREMIUM_RECHECK_HOURS),
        )
    stale = now - datetime.timedelta(hours=SYNC_RECHECK_HOURS)
    rows = [
        row
        for row in rows
        if row["server_id"] in targets
        and (
            row["guild_id"] in premium_guilds
            or not row["last_checked"]
            or row["last_checked"] < stale
        )
    ]
    rows.sort(key=lambda row: row["guild_id"] not in premium_guilds)
    stats["remaining"] = len(rows)
    limit = SYNC_DAILY_LIMIT // 2
    for start in range(0, min(len(rows), limit), SYNC_BATCH_SIZE):
        batch = rows[start : min(start + SYNC_BATCH_SIZE, limit)]
        for row in batch:
            target = targets[row["server_id"]]
            if "channel_name" not in target:
                target["channel_name"] = await get_youtube_channel_name(
                    target["config"]["yt_channel_id"]
                )
        results = await asyncio.gather(
            *[sync_member(row, targets[row["server_id"]], stats) for row in batch],
            return_exceptions=True,
        )
        stats["remaining"] -= len(batch)
        for row, result in zip(batch, results):
            if isinstance(result, QuotaExhausted):
                stats["quota_hit"] = True
                stats["remaining"] += 1
            elif isinstance(result, Exception):
                stats["failed"] += 1
                print(f"Error syncing {row['discord_id']}: {result}")
        if stats["quota_hit"]:
            print("YouTube quota exhausted, stopping sync until the next run.")
            break
        await asyncio.sleep(1)
    return stats


@tasks.loop(hours=12)
async def sync_roles():
    print("Running background sync task...")
    try:
        stats = await run_sync()
    except Exception as e:
        traceback.print_exc()
        await owner_log(
            "SYNC_LOG_CHANNEL_ID",
            f"{CROSS} Sync failed: {e}",
            discord.Color.red(),
        )
        return
    summary = f"Checked {stats['checked']:,} members, removed {stats['removed']:,} roles, added {stats['added']:,} roles, {stats['failed']:,} checks failed, {stats['remaining']:,} left for the next run."
    if stats["quota_hit"]:
        await owner_log(
            "SYNC_LOG_CHANNEL_ID",
            f"{WARN} Sync stopped because the YouTube quota ran out. {summary}",
            discord.Color.orange(),
        )
    else:
        await owner_log("SYNC_LOG_CHANNEL_ID", f"{CHECK} Sync completed. {summary}")
    print(f"Background sync task completed. {summary}")

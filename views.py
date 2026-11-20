import hashlib
import hmac
import logging
import os
import urllib.parse

import discord
from discord.ui import Button, ChannelSelect, Modal, RoleSelect, Select, TextInput, View

from database import (
    delete_server_config,
    get_guild_stats,
    get_pool,
    get_server_config_by_id,
    get_server_configs_for_guild,
    get_tiers,
    get_user_id,
    set_server_config,
    set_stack_tiers,
    set_tier,
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
    RED_BIN,
    REPLY,
    ROLE,
    TIER_DURATIONS,
    WARN,
    YT,
    get_youtube_channel_name,
    is_guild_premium,
)


async def send_error(interaction: discord.Interaction):
    if not interaction.response.is_done():
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"{CROSS} Something went wrong. Please try again.",
                color=COLOR,
            ),
            ephemeral=True,
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
            logging.error(f"Error in YouTubeChannelModal.on_submit: {e}")
            logging.exception(e)


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
            logging.error(f"Error in VerificationDMModal.on_submit: {e}")
            logging.exception(e)


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
            logging.error(f"Error in UnsubscribeDMModal.on_submit: {e}")
            logging.exception(e)


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
            yt_status = f"{CROSS} Not set. [How to find my Channel ID?](https://support.google.com/youtube/answer/3250431)"
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
            logging.error(f"Error updating config display: {e}")

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
            logging.error(f"Error in select_role: {e}")

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
            logging.error(f"Error in select_channel: {e}")

    @discord.ui.button(
        label="Set YouTube Channel", emoji=YT, style=discord.ButtonStyle.grey, row=2
    )
    async def set_channel(self, interaction: discord.Interaction, button: Button):
        try:
            modal = YouTubeChannelModal(self, title="Configure YouTube Channel")
            self.last_interaction = interaction
            await interaction.response.send_modal(modal)
        except Exception as e:
            logging.error(f"Error in set_channel: {e}")
            await send_error(interaction)

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
            logging.error(f"Error in set_verification_dm: {e}")
            await send_error(interaction)

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
            logging.error(f"Error in set_unsubscribe_dm: {e}")
            await send_error(interaction)

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
            logging.error(f"Error in set_tier_roles: {e}")

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
            logging.error(f"Error in back_button: {e}")


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
            logging.error(f"Error in select_role: {e}")

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
            logging.error(f"Error in back_button: {e}")


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
            logging.error(f"Error in back_button: {e}")


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
            logging.error(f"Error in add_config: {e}")
            await send_error(interaction)

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
            logging.error(f"Error in edit_config: {e}")

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
            logging.error(f"Error in show_edit_page: {e}")

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
            logging.error(f"Error in delete_config: {e}")

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
            logging.error(f"Error in on_config_selected_for_delete: {e}")

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
            logging.error(f"Error checking user subscription: {e}")
        await self.send_verification_link(interaction, config, user_subscription)

    @staticmethod
    async def send_verification_link(
        interaction: discord.Interaction, config, user_subscription=None
    ):
        guild_id = interaction.guild_id
        client_id = os.environ.get("GOOGLE_CLIENT_ID")
        redirect_uri = os.environ["OAUTH_REDIRECT_URI"]
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
        notice = os.environ.get("SITE_NOTICE")
        if notice:
            embeds.insert(0, discord.Embed(description=f"{WARN} {notice}", color=COLOR))
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

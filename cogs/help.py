import math
from typing import Dict, List, Optional

import discord
from discord.ext import commands


# ==============================================================================
# PAGINATED HELP VIEW WITH DROPDOWNS AND BUTTONS
# ==============================================================================
class HelpDropdown(discord.ui.Select):
    """Dropdown component for selecting a Cog category."""

    def __init__(self, parent_view: "DynamicHelpView", cogs: Dict[str, commands.Cog]):
        self.parent_view = parent_view
        options = [
            discord.SelectOption(
                label="Overview / Home",
                description="View general bot stats and category overview",
                emoji="🏠",
                value="home",
            )
        ]

        for cog_name, cog in sorted(cogs.items()):
            # Filter out cogs that have no visible commands for the user
            cmd_count = len([c for c in cog.get_commands() if not c.hidden])
            if cmd_count == 0:
                continue

            doc_summary = (cog.description or "No category description.").split("\n")[0]
            if len(doc_summary) > 80:
                doc_summary = doc_summary[:77] + "..."

            options.append(
                discord.SelectOption(
                    label=cog_name,
                    description=f"{cmd_count} commands — {doc_summary}",
                    emoji="📁",
                    value=cog_name,
                )
            )

        # Handle un-categorized commands if any exist
        no_category_cmds = [
            c for c in parent_view.bot.commands if c.cog is None and not c.hidden
        ]
        if no_category_cmds:
            options.append(
                discord.SelectOption(
                    label="Uncategorized",
                    description=f"{len(no_category_cmds)} standalone commands",
                    emoji="📌",
                    value="uncategorized",
                )
            )

        super().__init__(
            placeholder="Select a category to view commands...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.parent_view.author_id:
            await interaction.response.send_message(
                "❌ You cannot control this help menu. Run `!help` to open your own.",
                ephemeral=True,
            )
            return

        selected_value = self.values[0]
        self.parent_view.current_category = selected_value
        self.parent_view.current_page = 0
        await self.parent_view.update_message(interaction)


class DynamicHelpView(discord.ui.View):
    """View container handling pagination buttons and dropdown selection state."""

    def __init__(
        self,
        bot: commands.Bot,
        context: commands.Context,
        per_page: int = 5,
        timeout: float = 120.0,
    ):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.ctx = context
        self.author_id = context.author.id
        self.per_page = per_page
        self.current_category = "home"
        self.current_page = 0
        self.message: Optional[discord.Message] = None

        # Add the dropdown menu dynamically
        self.dropdown = HelpDropdown(self, bot.cogs)
        self.add_item(self.dropdown)

    # --------------------------------------------------------------------------
    # BUTTON CONTROLS
    # --------------------------------------------------------------------------
    @discord.ui.button(label="⏮️ First", style=discord.ButtonStyle.secondary, row=1)
    async def first_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self._handle_pagination(interaction, page=0)

    @discord.ui.button(label="◀️ Prev", style=discord.ButtonStyle.primary, row=1)
    async def prev_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self._handle_pagination(interaction, page=self.current_page - 1)

    @discord.ui.button(label="▶️ Next", style=discord.ButtonStyle.primary, row=1)
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await self._handle_pagination(interaction, page=self.current_page + 1)

    @discord.ui.button(label="⏭️ Last", style=discord.ButtonStyle.secondary, row=1)
    async def last_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        total_pages = self._get_total_pages()
        await self._handle_pagination(interaction, page=total_pages - 1)

    @discord.ui.button(label="❌ Close", style=discord.ButtonStyle.danger, row=1)
    async def close_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ You cannot control this help menu.", ephemeral=True
            )
            return
        await interaction.message.delete()
        self.stop()

    # --------------------------------------------------------------------------
    # PAGINATION HELPERS & EMBED GENERATION
    # --------------------------------------------------------------------------
    async def _handle_pagination(self, interaction: discord.Interaction, page: int):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ You cannot control this help menu.", ephemeral=True
            )
            return

        self.current_page = page
        await self.update_message(interaction)

    def _get_category_commands(self) -> List[commands.Command]:
        """Fetches non-hidden commands available to the user for the current category."""
        if self.current_category == "home":
            return []
        elif self.current_category == "uncategorized":
            return [c for c in self.bot.commands if c.cog is None and not c.hidden]
        else:
            cog = self.bot.get_cog(self.current_category)
            if not cog:
                return []
            return [c for c in cog.get_commands() if not c.hidden]

    def _get_total_pages(self) -> int:
        cmds = self._get_category_commands()
        if not cmds:
            return 1
        return math.ceil(len(cmds) / self.per_page)

    def _build_embed(self) -> discord.Embed:
        prefix = self.ctx.clean_prefix

        # --- HOME OVERVIEW EMBED ---
        if self.current_category == "home":
            embed = discord.Embed(
                title=f"📖 {self.bot.user.name} Help Center",
                description=(
                    f"Welcome to the command directory!\n\n"
                    f"• **Command Prefix:** `{prefix}`\n"
                    f"• **Total Commands:** `{len([c for c in self.bot.commands if not c.hidden])}`\n"
                    f"• **Total Categories:** `{len(self.bot.cogs)}`\n\n"
                    f"**How to Navigate:**\n"
                    f"Use the **dropdown menu** below to select a specific category.\n"
                    f"For detailed help on a specific command, run `{prefix}help <command>`."
                ),
                color=discord.Color.blurple(),
            )

            for name, cog in sorted(self.bot.cogs.items()):
                valid_cmds = [c for c in cog.get_commands() if not c.hidden]
                if not valid_cmds:
                    continue
                summary = cog.description.split("\n")[0] if cog.description else "No description"
                embed.add_field(
                    name=f"📁 {name} ({len(valid_cmds)})",
                    value=f"*{summary}*",
                    inline=False,
                )

            embed.set_footer(text=f"Requested by {self.ctx.author.display_name}", icon_url=self.ctx.author.display_avatar.url)
            return embed

        # --- CATEGORY PAGE EMBED ---
        cmds = sorted(self._get_category_commands(), key=lambda c: c.name)
        total_pages = self._get_total_pages()
        self.current_page = max(0, min(self.current_page, total_pages - 1))

        start_idx = self.current_page * self.per_page
        page_cmds = cmds[start_idx : start_idx + self.per_page]

        cog = self.bot.get_cog(self.current_category)
        cog_desc = cog.description if cog and cog.description else "No category description."

        embed = discord.Embed(
            title=f"📁 {self.current_category} Commands",
            description=f"*{cog_desc}*\n\nUse `{prefix}help <command_name>` for detailed parameter usage.",
            color=discord.Color.blue(),
        )

        for cmd in page_cmds:
            aliases = f" (Aliases: {', '.join(cmd.aliases)})" if cmd.aliases else ""
            doc = cmd.short_doc or "No description provided."
            usage = f"`{prefix}{cmd.qualified_name} {cmd.signature}`".strip()

            embed.add_field(
                name=f"🔹 {cmd.qualified_name}{aliases}",
                value=f"**Usage:** {usage}\n{doc}",
                inline=False,
            )

        embed.set_footer(
            text=f"Page {self.current_page + 1} of {total_pages} | Total Commands: {len(cmds)}"
        )
        return embed

    def _update_button_states(self):
        """Enables/disables buttons depending on pagination state."""
        if self.current_category == "home":
            for child in self.children:
                if isinstance(child, discord.ui.Button) and child.label != "❌ Close":
                    child.disabled = True
            return

        total_pages = self._get_total_pages()
        has_multiple_pages = total_pages > 1

        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.label == "❌ Close":
                    child.disabled = False
                elif child.label in ["⏮️ First", "◀️ Prev"]:
                    child.disabled = not (has_multiple_pages and self.current_page > 0)
                elif child.label in ["▶️ Next", "⏭️ Last"]:
                    child.disabled = not (
                        has_multiple_pages and self.current_page < total_pages - 1
                    )

    async def update_message(self, interaction: discord.Interaction):
        self._update_button_states()
        embed = self._build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        """Disables all UI elements when the view times out."""
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


# ==============================================================================
# CUSTOM HELP COMMAND IMPLEMENTATION
# ==============================================================================
class DynamicHelpCommand(commands.HelpCommand):
    """Custom HelpCommand class hooking into discord.ext.commands engine."""

    def __init__(self):
        super().__init__(
            command_attrs={
                "help": "Shows interactive help menu or specific command details.",
                "aliases": ["h"],
            }
        )

    async def send_bot_help(self, mapping):
        """Triggered when user types `!help` without arguments."""
        view = DynamicHelpView(self.context.bot, self.context)
        view._update_button_states()
        embed = view._build_embed()
        view.message = await self.context.send(embed=embed, view=view)

    async def send_cog_help(self, cog: commands.Cog):
        """Triggered when user types `!help <CogName>`."""
        view = DynamicHelpView(self.context.bot, self.context)
        if cog.qualified_name in self.context.bot.cogs:
            view.current_category = cog.qualified_name
        view._update_button_states()
        embed = view._build_embed()
        view.message = await self.context.send(embed=embed, view=view)

    async def send_group_help(self, group: commands.Group):
        """Triggered when user types `!help <GroupCommand>`."""
        ctx = self.context
        prefix = ctx.clean_prefix

        embed = discord.Embed(
            title=f"📑 Command Group: {prefix}{group.qualified_name}",
            description=group.help or "No description provided.",
            color=discord.Color.teal(),
        )

        aliases = ", ".join(group.aliases) if group.aliases else "None"
        embed.add_field(name="Usage", value=f"`{prefix}{group.qualified_name} {group.signature}`".strip(), inline=True)
        embed.add_field(name="Aliases", value=aliases, inline=True)

        subcommands = [c for c in group.commands if not c.hidden]
        if subcommands:
            sub_text = []
            for sub in subcommands:
                sub_text.append(f"• `{prefix}{sub.qualified_name} {sub.signature}` — {sub.short_doc or 'No doc'}")
            embed.add_field(name="Subcommands", value="\n".join(sub_text), inline=False)

        await ctx.send(embed=embed)

    async def send_command_help(self, command: commands.Command):
        """Triggered when user types `!help <command>`."""
        ctx = self.context
        prefix = ctx.clean_prefix

        embed = discord.Embed(
            title=f"🔍 Command: {prefix}{command.qualified_name}",
            description=command.help or command.short_doc or "No detailed description available.",
            color=discord.Color.teal(),
        )

        usage = f"`{prefix}{command.qualified_name} {command.signature}`".strip()
        embed.add_field(name="Usage Syntax", value=usage, inline=False)

        aliases = ", ".join([f"`{a}`" for a in command.aliases]) if command.aliases else "None"
        embed.add_field(name="Aliases", value=aliases, inline=True)

        cog_name = command.cog.qualified_name if command.cog else "Uncategorized"
        embed.add_field(name="Category", value=cog_name, inline=True)

        if command.clean_params:
            param_text = []
            for name, param in command.clean_params.items():
                default = f" (default: {param.default})" if param.default != param.empty else ""
                param_text.append(f"• `{name}`{default}")
            embed.add_field(name="Parameters", value="\n".join(param_text), inline=False)

        await ctx.send(embed=embed)

    async def send_error_message(self, error: str):
        """Handles non-existent commands gracefully."""
        embed = discord.Embed(
            title="❌ Help Search Failed",
            description=error,
            color=discord.Color.red(),
        )
        await self.context.send(embed=embed)


# ==============================================================================
# HELP COG ENTRYPOINT
# ==============================================================================
class Help(commands.Cog):
    """Dynamic Interactive Help Cog."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._original_help_command = bot.help_command
        bot.help_command = DynamicHelpCommand()
        bot.help_command.cog = self

    def cog_unload(self):
        """Restores default help command if this cog unloads."""
        self.bot.help_command = self._original_help_command


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
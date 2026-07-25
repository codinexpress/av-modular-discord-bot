import logging
import discord
from discord.ext import commands


class ErrorHandler(commands.Cog):
    """Global Command Error Handler Cog for centralized user feedback and logging."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ):
        """Global listener for handling command errors."""
        # Unroll CommandInvokeError to get the original root exception
        if isinstance(error, commands.CommandInvokeError):
            error = error.original

        # Ignore non-existent command invocations
        if isinstance(error, commands.CommandNotFound):
            return

        # Cooldown handling
        if isinstance(error, commands.CommandOnCooldown):
            seconds = int(error.retry_after)
            hours, remainder = divmod(seconds, 3600)
            minutes, secs = divmod(remainder, 60)

            time_parts = []
            if hours > 0:
                time_parts.append(f"{hours}h")
            if minutes > 0:
                time_parts.append(f"{minutes}m")
            if secs > 0 or not time_parts:
                time_parts.append(f"{secs}s")

            time_str = " ".join(time_parts)
            embed = discord.Embed(
                title="⏳ Cooldown Active",
                description=f"You can use `!{ctx.command.name}` again in **{time_str}**.",
                color=discord.Color.gold(),
            )
            await ctx.send(embed=embed, delete_after=10)
            return

        # Missing required arguments
        if isinstance(error, commands.MissingRequiredArgument):
            cmd_signature = f"!{ctx.command.qualified_name} {ctx.command.signature}"
            embed = discord.Embed(
                title="❌ Missing Parameter",
                description=f"Missing required parameter: `{error.param.name}`\n\n**Correct Usage:** `{cmd_signature}`",
                color=discord.Color.red(),
            )
            await ctx.send(embed=embed)
            return

        # Invalid arguments
        if isinstance(error, (commands.BadArgument, commands.ArgumentParsingError)):
            cmd_signature = f"!{ctx.command.qualified_name} {ctx.command.signature}"
            embed = discord.Embed(
                title="❌ Invalid Input",
                description=f"One or more provided arguments are invalid.\n\n**Correct Usage:** `{cmd_signature}`",
                color=discord.Color.red(),
            )
            await ctx.send(embed=embed)
            return

        # User missing permissions
        if isinstance(error, commands.MissingPermissions):
            perms = ", ".join(
                [f"`{p.replace('_', ' ').title()}`" for p in error.missing_permissions]
            )
            embed = discord.Embed(
                title="⛔ Access Denied",
                description=f"You lack the required permission(s): {perms}",
                color=discord.Color.red(),
            )
            await ctx.send(embed=embed)
            return

        # Bot missing permissions
        if isinstance(error, commands.BotMissingPermissions):
            perms = ", ".join(
                [f"`{p.replace('_', ' ').title()}`" for p in error.missing_permissions]
            )
            embed = discord.Embed(
                title="🤖 Bot Missing Permissions",
                description=f"The bot requires the following permission(s) to run this command: {perms}",
                color=discord.Color.red(),
            )
            await ctx.send(embed=embed)
            return

        # Private message restriction
        if isinstance(error, commands.NoPrivateMessage):
            embed = discord.Embed(
                title="🚫 Guild Only Command",
                description="This command cannot be used in Direct Messages. Please run it inside a server channel.",
                color=discord.Color.red(),
            )
            await ctx.send(embed=embed)
            return

        # Check failures
        if isinstance(error, commands.CheckFailure):
            embed = discord.Embed(
                title="❌ Command Restricted",
                description="You do not meet the requirements to run this command.",
                color=discord.Color.red(),
            )
            await ctx.send(embed=embed)
            return

        # Fallback for unhandled exceptions
        logging.error(
            f"Unhandled error in command '{ctx.command}': {error}", exc_info=error
        )
        embed = discord.Embed(
            title="⚠️ Internal Error",
            description="An unexpected error occurred while processing your command. Please try again later.",
            color=discord.Color.dark_red(),
        )
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(ErrorHandler(bot))

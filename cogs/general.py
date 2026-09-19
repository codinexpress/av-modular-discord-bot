import logging
import discord
from discord.ext import commands


class General(commands.Cog):
    """General utility commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        logging.info(f"Cog '{self.__class__.__name__}' loaded successfully.")

    @commands.command(name="ping", help="Responds with the bot's latency.")
    async def ping(self, ctx: commands.Context):
        """Responds with the bot's current websocket latency."""
        latency_ms = round(self.bot.latency * 1000)
        await ctx.send(f"Pong! Latency: {latency_ms}ms")

    @commands.command(name="echo", help="Repeats the provided message.")
    async def echo(self, ctx: commands.Context, *, message: str):
        """Echoes the user's message and attempts to delete the original message."""
        try:
            await ctx.message.delete()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            pass  # Ignore if bot lacks Manage Messages permission or if in DM
        await ctx.send(message)


async def setup(bot: commands.Bot):
    await bot.add_cog(General(bot))

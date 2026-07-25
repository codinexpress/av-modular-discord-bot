import discord
from discord.ext import commands

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"Cog '{self.__class__.__name__}' loaded successfully.")

    @commands.command(name="ping", help="Responds with the bot's latency.")
    async def ping(self, ctx):
        latency_ms = round(self.bot.latency * 1000)
        await ctx.send(f"Pong! Latency: {latency_ms}ms")

    @commands.command(name="echo", help="Repeats the provided message.")
    async def echo(self, ctx, *, message: str):
        await ctx.message.delete()  # Delete original invocation
        await ctx.send(message)

async def setup(bot):
    await bot.add_cog(General(bot))

import asyncio
import os
import logging
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Setup bot intents
intents = discord.Intents.default()
intents.message_content = True  # Required for message content in v2+

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logging.info("Bot is ready and online.")

async def load_extensions():
    """Dynamically loads all cogs found in the cogs directory."""
    for filename in os.listdir("./cogs"):
        if filename.endswith(".py") and filename != "__init__.py":
            extension_name = f"cogs.{filename[:-3]}"
            try:
                await bot.load_extension(extension_name)
                logging.info(f"Loaded extension: {extension_name}")
            except Exception as e:
                logging.error(f"Failed to load extension {extension_name}: {e}")

async def main():
    async with bot:
        await load_extensions()
        if not TOKEN:
            logging.error("DISCORD_TOKEN is missing from environment variables.")
            return
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())

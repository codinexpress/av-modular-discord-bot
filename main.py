import asyncio
import logging
import os
import sys
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
    cogs_dir = os.path.join(os.path.dirname(__file__), "cogs")
    if not os.path.exists(cogs_dir):
        logging.error("Cogs directory not found.")
        return

    for filename in os.listdir(cogs_dir):
        if filename.endswith(".py") and filename != "__init__.py":
            extension_name = f"cogs.{filename[:-3]}"
            try:
                await bot.load_extension(extension_name)
                logging.info(f"Loaded extension: {extension_name}")
            except Exception as e:
                logging.error(f"Failed to load extension {extension_name}: {e}")


async def main():
    if not TOKEN:
        logging.critical("DISCORD_TOKEN is missing from environment variables (.env). Bot cannot start.")
        sys.exit(1)

    async with bot:
        await load_extensions()
        try:
            await bot.start(TOKEN)
        except (KeyboardInterrupt, asyncio.CancelledError):
            logging.info("Shutting down bot gracefully...")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot process terminated.")

import asyncio
import datetime
import math
import random
import re
import sqlite3
from typing import Dict, Optional, Tuple, Union

import discord
from discord.ext import commands

MAX_AMOUNT_CAP = 100_000_000_000  # $100 Billion max cap for transactions


# ==============================================================================
# DATABASE MANAGER
# ==============================================================================
class EconomyDB:
    """Handles SQLite database interactions using asyncio thread delegation and atomic transactions."""

    def __init__(self, db_path: str = "economy.db"):
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def setup_database(self) -> None:
        """Creates required database tables if they do not exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Accounts table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    user_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    wallet INTEGER DEFAULT 100,
                    bank INTEGER DEFAULT 0,
                    bank_max INTEGER DEFAULT 5000,
                    PRIMARY KEY (user_id, guild_id)
                )
            """
            )
            # Inventory table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS inventory (
                    user_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    item_id TEXT NOT NULL,
                    quantity INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, guild_id, item_id)
                )
            """
            )
            conn.commit()

    async def get_account(self, user_id: int, guild_id: int) -> Dict[str, int]:
        """Fetches user account or initializes it if missing."""

        def _fetch():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT wallet, bank, bank_max FROM accounts WHERE user_id = ? AND guild_id = ?",
                    (user_id, guild_id),
                )
                row = cursor.fetchone()
                if not row:
                    cursor.execute(
                        "INSERT INTO accounts (user_id, guild_id, wallet, bank, bank_max) VALUES (?, ?, 100, 0, 5000)",
                        (user_id, guild_id),
                    )
                    conn.commit()
                    return {"wallet": 100, "bank": 0, "bank_max": 5000}
                return dict(row)

        return await asyncio.to_thread(_fetch)

    async def update_balances(
        self,
        user_id: int,
        guild_id: int,
        wallet_change: int = 0,
        bank_change: int = 0,
        bank_max_change: int = 0,
    ) -> Dict[str, int]:
        """Atomically modifies account balances."""

        def _update():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO accounts (user_id, guild_id, wallet, bank, bank_max)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, guild_id) DO UPDATE SET
                        wallet = MAX(0, wallet + ?),
                        bank = MAX(0, bank + ?),
                        bank_max = MAX(1000, bank_max + ?)
                    RETURNING wallet, bank, bank_max
                """,
                    (
                        user_id,
                        guild_id,
                        max(0, 100 + wallet_change),
                        max(0, 0 + bank_change),
                        max(1000, 5000 + bank_max_change),
                        wallet_change,
                        bank_change,
                        bank_max_change,
                    ),
                )
                row = cursor.fetchone()
                conn.commit()
                return dict(row)

        return await asyncio.to_thread(_update)

    async def transfer_funds(
        self, from_user_id: int, to_user_id: int, guild_id: int, amount: int
    ) -> Tuple[bool, str]:
        """Atomically transfers money between users inside an immediate SQLite transaction."""

        def _transfer():
            with self._get_connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT wallet FROM accounts WHERE user_id = ? AND guild_id = ?",
                    (from_user_id, guild_id),
                )
                row = cursor.fetchone()
                if not row:
                    cursor.execute(
                        "INSERT INTO accounts (user_id, guild_id, wallet, bank, bank_max) VALUES (?, ?, 100, 0, 5000)",
                        (from_user_id, guild_id),
                    )
                    from_wallet = 100
                else:
                    from_wallet = row["wallet"]

                if from_wallet < amount:
                    conn.rollback()
                    return False, "Insufficient wallet balance."

                cursor.execute(
                    "SELECT wallet FROM accounts WHERE user_id = ? AND guild_id = ?",
                    (to_user_id, guild_id),
                )
                if not cursor.fetchone():
                    cursor.execute(
                        "INSERT INTO accounts (user_id, guild_id, wallet, bank, bank_max) VALUES (?, ?, 100, 0, 5000)",
                        (to_user_id, guild_id),
                    )

                cursor.execute(
                    "UPDATE accounts SET wallet = wallet - ? WHERE user_id = ? AND guild_id = ?",
                    (amount, from_user_id, guild_id),
                )
                cursor.execute(
                    "UPDATE accounts SET wallet = wallet + ? WHERE user_id = ? AND guild_id = ?",
                    (amount, to_user_id, guild_id),
                )
                conn.commit()
                return True, "Success"

        return await asyncio.to_thread(_transfer)

    async def deposit_funds(
        self, user_id: int, guild_id: int, amount: int
    ) -> Tuple[bool, str]:
        """Atomically transfers money from wallet to bank."""

        def _deposit():
            with self._get_connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT wallet, bank, bank_max FROM accounts WHERE user_id = ? AND guild_id = ?",
                    (user_id, guild_id),
                )
                row = cursor.fetchone()
                if not row:
                    cursor.execute(
                        "INSERT INTO accounts (user_id, guild_id, wallet, bank, bank_max) VALUES (?, ?, 100, 0, 5000)",
                        (user_id, guild_id),
                    )
                    wallet, bank, bank_max = 100, 0, 5000
                else:
                    wallet, bank, bank_max = row["wallet"], row["bank"], row["bank_max"]

                if wallet < amount:
                    conn.rollback()
                    return False, "Insufficient wallet balance."
                if bank + amount > bank_max:
                    conn.rollback()
                    return False, "Bank space exceeded."

                cursor.execute(
                    "UPDATE accounts SET wallet = wallet - ?, bank = bank + ? WHERE user_id = ? AND guild_id = ?",
                    (amount, amount, user_id, guild_id),
                )
                conn.commit()
                return True, "Success"

        return await asyncio.to_thread(_deposit)

    async def withdraw_funds(
        self, user_id: int, guild_id: int, amount: int
    ) -> Tuple[bool, str]:
        """Atomically transfers money from bank to wallet."""

        def _withdraw():
            with self._get_connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT bank FROM accounts WHERE user_id = ? AND guild_id = ?",
                    (user_id, guild_id),
                )
                row = cursor.fetchone()
                if not row:
                    cursor.execute(
                        "INSERT INTO accounts (user_id, guild_id, wallet, bank, bank_max) VALUES (?, ?, 100, 0, 5000)",
                        (user_id, guild_id),
                    )
                    bank = 0
                else:
                    bank = row["bank"]

                if bank < amount:
                    conn.rollback()
                    return False, "Insufficient bank balance."

                cursor.execute(
                    "UPDATE accounts SET bank = bank - ?, wallet = wallet + ? WHERE user_id = ? AND guild_id = ?",
                    (amount, amount, user_id, guild_id),
                )
                conn.commit()
                return True, "Success"

        return await asyncio.to_thread(_withdraw)

    async def process_wager(
        self, user_id: int, guild_id: int, wager: int, net_payout: int
    ) -> Tuple[bool, Dict[str, int]]:
        """Atomically checks wallet balance and applies net win/loss payout."""

        def _wager():
            with self._get_connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT wallet FROM accounts WHERE user_id = ? AND guild_id = ?",
                    (user_id, guild_id),
                )
                row = cursor.fetchone()
                if not row:
                    cursor.execute(
                        "INSERT INTO accounts (user_id, guild_id, wallet, bank, bank_max) VALUES (?, ?, 100, 0, 5000)",
                        (user_id, guild_id),
                    )
                    wallet = 100
                else:
                    wallet = row["wallet"]

                if wallet < wager:
                    conn.rollback()
                    return False, {}

                cursor.execute(
                    "UPDATE accounts SET wallet = MAX(0, wallet + ?) WHERE user_id = ? AND guild_id = ? RETURNING wallet, bank, bank_max",
                    (net_payout, user_id, guild_id),
                )
                updated_row = cursor.fetchone()
                conn.commit()
                return True, dict(updated_row)

        return await asyncio.to_thread(_wager)

    async def get_leaderboard(self, guild_id: int, limit: int = 10):
        """Fetches top accounts by total wealth in a guild."""

        def _fetch():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT user_id, wallet, bank, (wallet + bank) as total
                    FROM accounts
                    WHERE guild_id = ?
                    ORDER BY total DESC
                    LIMIT ?
                """,
                    (guild_id, limit),
                )
                return [dict(row) for row in cursor.fetchall()]

        return await asyncio.to_thread(_fetch)

    async def get_item_count(self, user_id: int, guild_id: int, item_id: str) -> int:
        """Gets count of a specific item in user inventory."""

        def _fetch():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT quantity FROM inventory WHERE user_id = ? AND guild_id = ? AND item_id = ?",
                    (user_id, guild_id, item_id),
                )
                row = cursor.fetchone()
                return row["quantity"] if row else 0

        return await asyncio.to_thread(_fetch)

    async def update_item_count(
        self, user_id: int, guild_id: int, item_id: str, amount: int
    ) -> int:
        """Adds or removes items from inventory."""

        def _update():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO inventory (user_id, guild_id, item_id, quantity)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id, guild_id, item_id) DO UPDATE SET
                        quantity = MAX(0, quantity + ?)
                    RETURNING quantity
                """,
                    (user_id, guild_id, item_id, max(0, amount), amount),
                )
                row = cursor.fetchone()
                conn.commit()
                return row["quantity"]

        return await asyncio.to_thread(_update)

    async def get_user_inventory(self, user_id: int, guild_id: int) -> Dict[str, int]:
        """Fetches non-zero inventory items."""

        def _fetch():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT item_id, quantity FROM inventory WHERE user_id = ? AND guild_id = ? AND quantity > 0",
                    (user_id, guild_id),
                )
                return {row["item_id"]: row["quantity"] for row in cursor.fetchall()}

        return await asyncio.to_thread(_fetch)


# ==============================================================================
# SHOP REGISTRY & CONFIGURATION
# ==============================================================================
ITEMS = {
    "shield": {
        "name": "🛡️ Rob Shield",
        "price": 1500,
        "description": "Protects you from 1 rob attempt automatically.",
    },
    "pickaxe": {
        "name": "⛏️ Diamond Pickaxe",
        "price": 2500,
        "description": "Increases payout yield from `!mine`.",
    },
    "rod": {
        "name": "🎣 Super Rod",
        "price": 2000,
        "description": "Increases rare catch chance from `!fish`.",
    },
    "vault": {
        "name": "🏦 Bank Vault Expansion",
        "price": 5000,
        "description": "Permanently increases bank capacity by +$10,000.",
    },
}


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================
def parse_amount(
    amount_str: str, current_val: int, max_limit: Optional[int] = None
) -> Optional[int]:
    """Parses numbers, 'all', 'max', 'half', and shorthand like '1.5k', '2m' safely."""
    amount_str = amount_str.lower().strip()

    if amount_str in ("all", "max"):
        target = current_val
        if max_limit is not None:
            target = min(target, max_limit)
        return target if 0 < target <= MAX_AMOUNT_CAP else None

    if amount_str == "half":
        target = current_val // 2
        if max_limit is not None:
            target = min(target, max_limit)
        return target if 0 < target <= MAX_AMOUNT_CAP else None

    # Handle standard numbers with optional suffixes
    match = re.match(r"^(\d+(?:\.\d+)?)([kmb])?$", amount_str)
    if not match:
        return None

    val, multiplier = match.groups()
    try:
        num = float(val)
        if multiplier == "k":
            num *= 1_000
        elif multiplier == "m":
            num *= 1_000_000
        elif multiplier == "b":
            num *= 1_000_000_000

        if math.isnan(num) or math.isinf(num):
            return None

        result = int(num)
        if 0 < result <= MAX_AMOUNT_CAP:
            if max_limit is not None:
                result = min(result, max_limit)
            return result
        return None
    except (ValueError, OverflowError):
        return None


def format_curr(amount: int) -> str:
    """Formats integers into standard money representations ($1,234)."""
    return f"${amount:,}"


# ==============================================================================
# ECONOMY COG
# ==============================================================================
class Economy(commands.Cog):
    """Full-featured Discord Bot Economy Cog."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = EconomyDB()
        self.db.setup_database()

    # --------------------------------------------------------------------------
    # BANKING & ACCOUNT COMMANDS
    # --------------------------------------------------------------------------
    @commands.command(name="balance", aliases=["bal", "money"])
    @commands.guild_only()
    async def balance(
        self, ctx: commands.Context, member: Optional[discord.Member] = None
    ):
        """Displays wallet, bank, and total net worth."""
        target = member or ctx.author
        if target.bot:
            await ctx.send("Bots do not have bank accounts.")
            return

        acc = await self.db.get_account(target.id, ctx.guild.id)
        total = acc["wallet"] + acc["bank"]

        embed = discord.Embed(
            title=f"💳 Financial Profile — {target.display_name}",
            color=discord.Color.blue(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="👛 Wallet", value=format_curr(acc["wallet"]), inline=True)
        embed.add_field(
            name="🏦 Bank",
            value=f"{format_curr(acc['bank'])} / {format_curr(acc['bank_max'])}",
            inline=True,
        )
        embed.add_field(name="💰 Net Worth", value=format_curr(total), inline=False)

        await ctx.send(embed=embed)

    @commands.command(name="deposit", aliases=["dep"])
    @commands.guild_only()
    async def deposit(self, ctx: commands.Context, amount: str):
        """Deposits cash from wallet into bank storage."""
        acc = await self.db.get_account(ctx.author.id, ctx.guild.id)
        space_available = max(0, acc["bank_max"] - acc["bank"])

        if space_available <= 0:
            await ctx.send(
                "❌ Your bank account is full! Buy a Bank Vault to store more."
            )
            return

        parsed = parse_amount(amount, acc["wallet"], space_available)
        if parsed is None or parsed <= 0:
            await ctx.send("❌ Invalid deposit amount specified.")
            return

        success, err_msg = await self.db.deposit_funds(
            ctx.author.id, ctx.guild.id, parsed
        )
        if success:
            await ctx.send(f"✅ Deposited **{format_curr(parsed)}** into your bank.")
        else:
            await ctx.send(f"❌ Deposit failed: {err_msg}")

    @commands.command(name="withdraw", aliases=["with"])
    @commands.guild_only()
    async def withdraw(self, ctx: commands.Context, amount: str):
        """Withdraws cash from bank to wallet."""
        acc = await self.db.get_account(ctx.author.id, ctx.guild.id)
        parsed = parse_amount(amount, acc["bank"])

        if parsed is None or parsed <= 0:
            await ctx.send("❌ Invalid withdrawal amount specified.")
            return

        success, err_msg = await self.db.withdraw_funds(
            ctx.author.id, ctx.guild.id, parsed
        )
        if success:
            await ctx.send(f"✅ Withdrew **{format_curr(parsed)}** from your bank.")
        else:
            await ctx.send(f"❌ Withdrawal failed: {err_msg}")

    @commands.command(name="pay", aliases=["give", "transfer"])
    @commands.guild_only()
    async def pay(self, ctx: commands.Context, member: discord.Member, amount: str):
        """Transfers money directly to another member's wallet."""
        if member.id == ctx.author.id:
            await ctx.send("❌ You cannot send money to yourself.")
            return
        if member.bot:
            await ctx.send("❌ You cannot send money to bots.")
            return

        sender_acc = await self.db.get_account(ctx.author.id, ctx.guild.id)
        parsed = parse_amount(amount, sender_acc["wallet"])

        if parsed is None or parsed <= 0:
            await ctx.send("❌ Invalid transfer amount specified.")
            return

        success, err_msg = await self.db.transfer_funds(
            ctx.author.id, member.id, ctx.guild.id, parsed
        )
        if success:
            await ctx.send(
                f"💸 Successfully paid **{format_curr(parsed)}** to {member.mention}."
            )
        else:
            await ctx.send(f"❌ Transfer failed: {err_msg}")

    @commands.command(name="leaderboard", aliases=["lb", "richest"])
    @commands.guild_only()
    async def leaderboard(self, ctx: commands.Context):
        """Shows top 10 richest members in the server."""
        records = await self.db.get_leaderboard(ctx.guild.id, limit=10)
        if not records:
            await ctx.send("No economy profiles registered yet.")
            return

        embed = discord.Embed(
            title=f"🏆 Wealth Leaderboard — {ctx.guild.name}",
            color=discord.Color.gold(),
        )

        description = []
        for index, row in enumerate(records, start=1):
            member = ctx.guild.get_member(row["user_id"])
            name = member.display_name if member else f"User ID: {row['user_id']}"
            description.append(f"**{index}. {name}** — {format_curr(row['total'])}")

        embed.description = "\n".join(description)
        await ctx.send(embed=embed)

    # --------------------------------------------------------------------------
    # EARNING & WORK COMMANDS
    # --------------------------------------------------------------------------
    @commands.command(name="work")
    @commands.guild_only()
    @commands.cooldown(1, 3600, commands.BucketType.user)
    async def work(self, ctx: commands.Context):
        """Work a shift to earn money."""
        jobs = [
            ("software developer", random.randint(300, 700)),
            ("barista", random.randint(150, 350)),
            ("chef", random.randint(250, 500)),
            ("delivery driver", random.randint(200, 400)),
            ("freelancer", random.randint(200, 600)),
        ]
        job, salary = random.choice(jobs)

        await self.db.update_balances(
            ctx.author.id, ctx.guild.id, wallet_change=salary
        )
        await ctx.send(
            f"💼 You worked as a **{job}** and earned **{format_curr(salary)}**!"
        )

    @commands.command(name="beg")
    @commands.guild_only()
    @commands.cooldown(1, 60, commands.BucketType.user)
    async def beg(self, ctx: commands.Context):
        """Beg strangers for spare change."""
        if random.random() < 0.35:
            responses = [
                "Elon Musk walked past and ignored you.",
                "A stranger told you to get a job.",
                "Someone threw a empty coffee cup at you.",
            ]
            await ctx.send(f"💔 {random.choice(responses)}")
            return

        gain = random.randint(15, 120)
        await self.db.update_balances(ctx.author.id, ctx.guild.id, wallet_change=gain)

        donors = [
            "a kind stranger",
            "a sympathetic pedestrian",
            "a local business owner",
            "your neighbor",
        ]
        await ctx.send(
            f"🪙 {random.choice(donors).capitalize()} gave you **{format_curr(gain)}**!"
        )

    @commands.command(name="daily")
    @commands.guild_only()
    @commands.cooldown(1, 86400, commands.BucketType.user)
    async def daily(self, ctx: commands.Context):
        """Claims daily cash stipend."""
        reward = 1000
        await self.db.update_balances(
            ctx.author.id, ctx.guild.id, wallet_change=reward
        )
        await ctx.send(
            f"☀️ You claimed your daily reward of **{format_curr(reward)}**!"
        )

    @commands.command(name="weekly")
    @commands.guild_only()
    @commands.cooldown(1, 604800, commands.BucketType.user)
    async def weekly(self, ctx: commands.Context):
        """Claims weekly bonus payment."""
        reward = 7500
        await self.db.update_balances(
            ctx.author.id, ctx.guild.id, wallet_change=reward
        )
        await ctx.send(
            f"🗓️ You claimed your weekly reward of **{format_curr(reward)}**!"
        )

    @commands.command(name="crime")
    @commands.guild_only()
    @commands.cooldown(1, 1800, commands.BucketType.user)
    async def crime(self, ctx: commands.Context):
        """Perform high-risk criminal activity."""
        success = random.random() > 0.45

        if success:
            gain = random.randint(500, 1500)
            await self.db.update_balances(
                ctx.author.id, ctx.guild.id, wallet_change=gain
            )
            crimes = [
                "robbed an ATM",
                "hacked an office server",
                "ran an illegal street gamble",
            ]
            await ctx.send(
                f"🥷 You successfully {random.choice(crimes)} and looted **{format_curr(gain)}**!"
            )
        else:
            fine = random.randint(250, 800)
            await self.db.update_balances(
                ctx.author.id, ctx.guild.id, wallet_change=-fine
            )
            await ctx.send(
                f"🚨 You were caught by law enforcement and fined **{format_curr(fine)}**!"
            )

    @commands.command(name="fish")
    @commands.guild_only()
    @commands.cooldown(1, 120, commands.BucketType.user)
    async def fish(self, ctx: commands.Context):
        """Go fishing for valuable catches."""
        has_rod = (
            await self.db.get_item_count(ctx.author.id, ctx.guild.id, "rod") > 0
        )
        bonus = 1.5 if has_rod else 1.0

        outcomes = [
            ("👢 an old boot", 0),
            ("🐟 a small minnow", int(50 * bonus)),
            ("🐠 a tropical fish", int(180 * bonus)),
            ("🦀 a giant crab", int(320 * bonus)),
            ("💎 a sunken treasure chest", int(1200 * bonus)),
        ]
        weights = [25, 40, 20, 10, 5]

        item_name, value = random.choices(outcomes, weights=weights)[0]
        if value > 0:
            await self.db.update_balances(
                ctx.author.id, ctx.guild.id, wallet_change=value
            )
            extra = " (Rod bonus applied!)" if has_rod else ""
            await ctx.send(
                f"🎣 You caught {item_name} worth **{format_curr(value)}**!{extra}"
            )
        else:
            await ctx.send(f"🎣 You pulled up {item_name}. Worthless!")

    @commands.command(name="mine")
    @commands.guild_only()
    @commands.cooldown(1, 300, commands.BucketType.user)
    async def mine(self, ctx: commands.Context):
        """Mine minerals and ores."""
        has_pick = (
            await self.db.get_item_count(ctx.author.id, ctx.guild.id, "pickaxe") > 0
        )
        multiplier = 2.0 if has_pick else 1.0

        ores = [
            ("🪨 Coal", int(100 * multiplier)),
            ("🪙 Iron Ore", int(250 * multiplier)),
            ("🥇 Gold Nugget", int(600 * multiplier)),
            ("💎 Rough Diamond", int(1500 * multiplier)),
        ]
        weights = [50, 30, 15, 5]

        name, val = random.choices(ores, weights=weights)[0]
        await self.db.update_balances(ctx.author.id, ctx.guild.id, wallet_change=val)
        extra = " (Pickaxe bonus applied!)" if has_pick else ""
        await ctx.send(
            f"⛏️ You mined **{name}** and sold it for **{format_curr(val)}**!{extra}"
        )

    # --------------------------------------------------------------------------
    # PVP STEALING & INTERACTION COMMANDS
    # --------------------------------------------------------------------------
    @commands.command(name="rob", aliases=["steal"])
    @commands.guild_only()
    @commands.cooldown(1, 3600, commands.BucketType.user)
    async def rob(self, ctx: commands.Context, target: discord.Member):
        """Steal cash from another member's wallet."""
        if target.id == ctx.author.id:
            await ctx.send("❌ You cannot rob yourself.")
            return
        if target.bot:
            await ctx.send("❌ You cannot rob bots.")
            return

        robber_acc = await self.db.get_account(ctx.author.id, ctx.guild.id)
        victim_acc = await self.db.get_account(target.id, ctx.guild.id)

        if robber_acc["wallet"] < 250:
            await ctx.send(
                "❌ You need at least **$250** in your wallet to cover court fees if caught."
            )
            return
        if victim_acc["wallet"] < 200:
            await ctx.send(
                "❌ This member has less than **$200** in their wallet. Not worth it!"
            )
            return

        # Check shield item defense
        shields = await self.db.get_item_count(target.id, ctx.guild.id, "shield")
        if shields > 0:
            await self.db.update_item_count(target.id, ctx.guild.id, "shield", -1)
            await ctx.send(
                f"🛡️ **Robbery Prevented!** {target.mention}'s Shield blocked your attempt! (Shield was consumed)."
            )
            return

        # Success check (45% chance)
        if random.random() <= 0.45:
            stolen_percentage = random.uniform(0.20, 0.60)
            stolen = int(victim_acc["wallet"] * stolen_percentage)

            success, _ = await self.db.transfer_funds(
                target.id, ctx.author.id, ctx.guild.id, stolen
            )
            if success:
                await ctx.send(
                    f"🥷 Successful heist! You robbed **{format_curr(stolen)}** from {target.mention}!"
                )
            else:
                await ctx.send("❌ The heist failed unexpectedly.")
        else:
            penalty = int(robber_acc["wallet"] * 0.30)
            await self.db.transfer_funds(
                ctx.author.id, target.id, ctx.guild.id, penalty
            )
            await ctx.send(
                f"🚨 You got caught! You paid **{format_curr(penalty)}** in compensation to {target.mention}."
            )

    # --------------------------------------------------------------------------
    # GAMBLING & MINI GAMES
    # --------------------------------------------------------------------------
    @commands.command(name="coinflip", aliases=["cf"])
    @commands.guild_only()
    async def coinflip(self, ctx: commands.Context, choice: str, bet: str):
        """Wager cash on a coinflip (heads or tails)."""
        choice = choice.lower()
        if choice not in ["heads", "tails", "h", "t"]:
            await ctx.send("❌ Choose either `heads` or `tails`.")
            return

        choice = "heads" if choice in ["heads", "h"] else "tails"

        acc = await self.db.get_account(ctx.author.id, ctx.guild.id)
        wager = parse_amount(bet, acc["wallet"])

        if wager is None or wager <= 0 or wager > acc["wallet"]:
            await ctx.send("❌ Invalid wager amount.")
            return

        outcome = random.choice(["heads", "tails"])
        is_win = choice == outcome
        net_payout = wager if is_win else -wager

        success, _ = await self.db.process_wager(
            ctx.author.id, ctx.guild.id, wager, net_payout
        )
        if not success:
            await ctx.send(
                "❌ Transaction failed. Insufficient funds in wallet."
            )
            return

        if is_win:
            await ctx.send(
                f"🪙 Coin landed on **{outcome}**! You won **{format_curr(wager)}**!"
            )
        else:
            await ctx.send(
                f"🪙 Coin landed on **{outcome}**! You lost **{format_curr(wager)}**."
            )

    @commands.command(name="slots")
    @commands.guild_only()
    async def slots(self, ctx: commands.Context, bet: str):
        """Play the slot machine."""
        acc = await self.db.get_account(ctx.author.id, ctx.guild.id)
        wager = parse_amount(bet, acc["wallet"])

        if wager is None or wager <= 0 or wager > acc["wallet"]:
            await ctx.send("❌ Invalid wager amount.")
            return

        emojis = ["🍒", "🍋", "🔔", "💎", "7️⃣"]
        reel1, reel2, reel3 = (
            random.choice(emojis),
            random.choice(emojis),
            random.choice(emojis),
        )
        display = f"🎰 **[ {reel1} | {reel2} | {reel3} ]** 🎰\n"

        if reel1 == reel2 == reel3:
            multiplier = 5 if reel1 == "7️⃣" else 3
            net_payout = wager * multiplier
            result_str = f"{display}🎉 **JACKPOT!** You won **{format_curr(net_payout)}** ({multiplier}x)!"
        elif reel1 == reel2 or reel2 == reel3 or reel1 == reel3:
            net_payout = int(wager * 1.5)
            result_str = f"{display}✨ Two of a kind! You won **{format_curr(net_payout)}**!"
        else:
            net_payout = -wager
            result_str = f"{display}❌ No match. You lost **{format_curr(wager)}**."

        success, _ = await self.db.process_wager(
            ctx.author.id, ctx.guild.id, wager, net_payout
        )
        if not success:
            await ctx.send("❌ Wager failed. Insufficient funds in wallet.")
            return

        await ctx.send(result_str)

    @commands.command(name="dice")
    @commands.guild_only()
    async def dice(self, ctx: commands.Context, bet: str):
        """Roll dice against the bot."""
        acc = await self.db.get_account(ctx.author.id, ctx.guild.id)
        wager = parse_amount(bet, acc["wallet"])

        if wager is None or wager <= 0 or wager > acc["wallet"]:
            await ctx.send("❌ Invalid wager amount.")
            return

        user_roll = random.randint(1, 6) + random.randint(1, 6)
        bot_roll = random.randint(1, 6) + random.randint(1, 6)
        msg = f"🎲 You rolled **{user_roll}** | Bot rolled **{bot_roll}**\n"

        if user_roll > bot_roll:
            net_payout = wager
            result_str = f"{msg}🎉 You won **{format_curr(wager)}**!"
        elif bot_roll > user_roll:
            net_payout = -wager
            result_str = f"{msg}❌ You lost **{format_curr(wager)}**."
        else:
            await ctx.send(f"{msg}🤝 It's a draw! Wager refunded.")
            return

        success, _ = await self.db.process_wager(
            ctx.author.id, ctx.guild.id, wager, net_payout
        )
        if not success:
            await ctx.send("❌ Wager failed. Insufficient funds in wallet.")
            return

        await ctx.send(result_str)

    # --------------------------------------------------------------------------
    # SHOP & INVENTORY COMMANDS
    # --------------------------------------------------------------------------
    @commands.command(name="shop")
    @commands.guild_only()
    async def shop(self, ctx: commands.Context):
        """Displays available items in the server shop."""
        embed = discord.Embed(
            title="🛒 Server Economy Shop",
            description="Use `!buy <item_id>` to purchase items.",
            color=discord.Color.green(),
        )

        for item_id, data in ITEMS.items():
            embed.add_field(
                name=f"{data['name']} (`{item_id}`)",
                value=f"**Price:** {format_curr(data['price'])}\n{data['description']}",
                inline=False,
            )

        await ctx.send(embed=embed)

    @commands.command(name="buy")
    @commands.guild_only()
    async def buy(self, ctx: commands.Context, item_id: str, amount: int = 1):
        """Purchase an item from shop."""
        item_id = item_id.lower()
        if item_id not in ITEMS:
            await ctx.send("❌ Invalid item ID. Check `!shop` for valid items.")
            return
        if amount <= 0 or amount > 1000:
            await ctx.send("❌ Amount must be between 1 and 1000.")
            return

        item = ITEMS[item_id]
        total_cost = item["price"] * amount

        # Deduct wallet atomically using process_wager (-total_cost)
        success, _ = await self.db.process_wager(
            ctx.author.id, ctx.guild.id, total_cost, -total_cost
        )
        if not success:
            await ctx.send(
                f"❌ You need **{format_curr(total_cost)}** in wallet to buy this."
            )
            return

        if item_id == "vault":
            # Vault increases bank max directly
            capacity_increase = 10000 * amount
            await self.db.update_balances(
                ctx.author.id, ctx.guild.id, bank_max_change=capacity_increase
            )
            await ctx.send(
                f"✅ Purchased **{amount}x {item['name']}**! Your bank limit expanded by +{format_curr(capacity_increase)}."
            )
        else:
            # Store in inventory
            await self.db.update_item_count(
                ctx.author.id, ctx.guild.id, item_id, amount
            )
            await ctx.send(
                f"✅ Purchased **{amount}x {item['name']}** for **{format_curr(total_cost)}**!"
            )

    @commands.command(name="inventory", aliases=["inv"])
    @commands.guild_only()
    async def inventory(
        self, ctx: commands.Context, member: Optional[discord.Member] = None
    ):
        """Displays owned items."""
        target = member or ctx.author
        items = await self.db.get_user_inventory(target.id, ctx.guild.id)

        embed = discord.Embed(
            title=f"🎒 Inventory — {target.display_name}",
            color=discord.Color.purple(),
        )

        if not items:
            embed.description = "Inventory is currently empty."
        else:
            lines = []
            for item_id, qty in items.items():
                name = ITEMS.get(item_id, {}).get("name", item_id.capitalize())
                lines.append(f"• **{name}**: `{qty}`")
            embed.description = "\n".join(lines)

        await ctx.send(embed=embed)

    # --------------------------------------------------------------------------
    # ADMIN / MODERATION COMMANDS
    # --------------------------------------------------------------------------
    @commands.command(name="addmoney")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def add_money(
        self, ctx: commands.Context, member: discord.Member, amount: int
    ):
        """Admin command to grant funds to a user."""
        if amount <= 0 or amount > MAX_AMOUNT_CAP:
            await ctx.send("❌ Specify a positive number up to 100 Billion.")
            return

        await self.db.update_balances(member.id, ctx.guild.id, wallet_change=amount)
        await ctx.send(
            f"✅ Added **{format_curr(amount)}** to {member.mention}'s wallet."
        )

    @commands.command(name="removemoney")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def remove_money(
        self, ctx: commands.Context, member: discord.Member, amount: int
    ):
        """Admin command to remove wallet funds from a user."""
        if amount <= 0 or amount > MAX_AMOUNT_CAP:
            await ctx.send("❌ Specify a positive number up to 100 Billion.")
            return

        await self.db.update_balances(member.id, ctx.guild.id, wallet_change=-amount)
        await ctx.send(
            f"✅ Removed **{format_curr(amount)}** from {member.mention}'s wallet."
        )


# Setup extension hook for main.py dynamic loading
async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
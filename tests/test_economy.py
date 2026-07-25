import asyncio
import os
import pytest
from cogs.economy import EconomyDB, parse_amount, MAX_AMOUNT_CAP


@pytest.fixture
def test_db(tmp_path):
    """Fixture providing a temporary SQLite database for testing."""
    db_file = tmp_path / "test_economy.db"
    db = EconomyDB(str(db_file))
    db.setup_database()
    yield db


# ==============================================================================
# PARSE AMOUNT TESTS
# ==============================================================================
def test_parse_amount_standard():
    assert parse_amount("100", 1000) == 100
    assert parse_amount("1.5k", 5000) == 1500
    assert parse_amount("2m", 10000) == 2_000_000
    assert parse_amount("1b", 10000) == 1_000_000_000


def test_parse_amount_keywords():
    assert parse_amount("all", 500) == 500
    assert parse_amount("max", 500, max_limit=300) == 300
    assert parse_amount("half", 1000) == 500


def test_parse_amount_invalid():
    assert parse_amount("-50", 1000) is None
    assert parse_amount("abc", 1000) is None
    assert parse_amount("0", 1000) is None
    assert parse_amount("1e100", 1000) is None
    assert parse_amount("999999999999999999999999999k", 1000) is None


# ==============================================================================
# DATABASE ATOMICITY & CONCURRENCY TESTS
# ==============================================================================
@pytest.mark.asyncio
async def test_get_and_initialize_account(test_db):
    acc = await test_db.get_account(user_id=1, guild_id=100)
    assert acc["wallet"] == 100
    assert acc["bank"] == 0
    assert acc["bank_max"] == 5000


@pytest.mark.asyncio
async def test_atomic_transfer_funds(test_db):
    # Setup sender (User 1) with $500
    await test_db.update_balances(user_id=1, guild_id=100, wallet_change=400)
    # Setup receiver (User 2) with initial account
    await test_db.get_account(user_id=2, guild_id=100)

    success, msg = await test_db.transfer_funds(
        from_user_id=1, to_user_id=2, guild_id=100, amount=200
    )
    assert success is True

    user1 = await test_db.get_account(user_id=1, guild_id=100)
    user2 = await test_db.get_account(user_id=2, guild_id=100)
    assert user1["wallet"] == 300
    assert user2["wallet"] == 300


@pytest.mark.asyncio
async def test_prevent_double_spending_concurrency(test_db):
    # Initialize User 1 with $100
    await test_db.get_account(user_id=1, guild_id=100)
    # Initialize User 2
    await test_db.get_account(user_id=2, guild_id=100)

    # Attempt two concurrent transfers of $100 when wallet only has $100
    results = await asyncio.gather(
        test_db.transfer_funds(from_user_id=1, to_user_id=2, guild_id=100, amount=100),
        test_db.transfer_funds(from_user_id=1, to_user_id=2, guild_id=100, amount=100),
    )

    successes = [r[0] for r in results]
    assert successes.count(True) == 1
    assert successes.count(False) == 1

    user1 = await test_db.get_account(user_id=1, guild_id=100)
    user2 = await test_db.get_account(user_id=2, guild_id=100)
    assert user1["wallet"] == 0
    assert user2["wallet"] == 200  # Initial $100 + $100 transferred once


@pytest.mark.asyncio
async def test_deposit_and_withdraw_funds(test_db):
    await test_db.update_balances(user_id=1, guild_id=100, wallet_change=900)
    
    # Deposit $500 into bank
    dep_success, _ = await test_db.deposit_funds(user_id=1, guild_id=100, amount=500)
    assert dep_success is True

    acc = await test_db.get_account(user_id=1, guild_id=100)
    assert acc["wallet"] == 500
    assert acc["bank"] == 500

    # Withdraw $200 from bank
    with_success, _ = await test_db.withdraw_funds(user_id=1, guild_id=100, amount=200)
    assert with_success is True

    acc = await test_db.get_account(user_id=1, guild_id=100)
    assert acc["wallet"] == 700
    assert acc["bank"] == 300


@pytest.mark.asyncio
async def test_inventory_updates(test_db):
    qty = await test_db.update_item_count(user_id=1, guild_id=100, item_id="shield", amount=2)
    assert qty == 2

    count = await test_db.get_item_count(user_id=1, guild_id=100, item_id="shield")
    assert count == 2

    inv = await test_db.get_user_inventory(user_id=1, guild_id=100)
    assert inv == {"shield": 2}

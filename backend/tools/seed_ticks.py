# seed_ticks.py - CLI tool to seed historical ticks in AlphaSync
import asyncio
import sys
import os
import random
from datetime import datetime, timezone, timedelta
from decimal import Decimal

# Add parent directory to path so we can import backend modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.connection import init_db, async_session_factory
from models.historical_ticks import HistoricalTick

SYMBOLS = {
    "^NSEI": {"price": 22000.0, "volatility": 0.0001, "exchange": "NSE"},
    "^NSEBANK": {"price": 47000.0, "volatility": 0.00015, "exchange": "NSE"},
    "RELIANCE.NS": {"price": 2500.0, "volatility": 0.0003, "exchange": "NSE"},
    "TCS.NS": {"price": 3800.0, "volatility": 0.00025, "exchange": "NSE"},
    "HDFCBANK.NS": {"price": 1450.0, "volatility": 0.00035, "exchange": "NSE"},
    "GOLD": {"price": 65000.0, "volatility": 0.0002, "exchange": "MCX"},
    "SILVER": {"price": 72000.0, "volatility": 0.00025, "exchange": "MCX"},
}


async def seed_historical_ticks(days_ago: int = 1, duration_minutes: int = 60):
    print("Initializing database...")
    await init_db()

    target_date = datetime.now(timezone.utc) - timedelta(days=days_ago)
    # Start at 9:15 AM
    start_time = datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        9,
        15,
        0,
        tzinfo=timezone.utc,
    )
    end_time = start_time + timedelta(minutes=duration_minutes)

    print(
        f"Generating simulated historical tick-by-tick data for {start_time.date()}..."
    )
    print(f"Time Window: {start_time.strftime('%H:%M:%S')} to {end_time.strftime('%H:%M:%S')}")
    print(f"Symbols: {list(SYMBOLS.keys())}")

    # Initialize state
    states = {}
    for sym, config in SYMBOLS.items():
        states[sym] = {
            "price": config["price"],
            "volume": 0,
            "high": config["price"],
            "low": config["price"],
            "open": config["price"],
        }

    ticks_to_insert = []
    current_time = start_time
    total_ticks = 0

    # Generate ticks chronologically across all symbols
    # A tick occurs every 100ms to 500ms on average
    market_drift = 0.0

    while current_time < end_time:
        # Step forward by a random sub-second interval (e.g. 50ms to 250ms)
        step_ms = random.randint(50, 250)
        current_time += timedelta(milliseconds=step_ms)

        # Update market-wide drift
        market_drift += random.normalvariate(0, 0.0001)
        market_drift = max(-0.01, min(0.01, market_drift))

        # Select 1 to 3 random symbols to tick in this step
        ticking_symbols = random.sample(
            list(SYMBOLS.keys()), random.randint(1, 3)
        )

        for symbol in ticking_symbols:
            config = SYMBOLS[symbol]
            state = states[symbol]

            # Random walk
            vol = config["volatility"]
            correlation = 0.5 if not symbol.startswith("^") else 0.8
            drift = (market_drift * correlation) + random.normalvariate(0, vol)

            old_price = state["price"]
            new_price = round(old_price * (1.0 + drift), 2)
            if new_price <= 0.05:
                new_price = 0.05

            state["price"] = new_price
            state["high"] = max(state["high"], new_price)
            state["low"] = min(state["low"], new_price)

            # Bid/Ask
            spread_pct = 0.0005 if not symbol.startswith("^") else 0.0001
            spread = max(0.05, round(new_price * spread_pct, 2))
            half_spread = round(spread / 2.0, 2)
            if half_spread <= 0:
                half_spread = 0.05
            bid = round(new_price - half_spread, 2)
            ask = round(new_price + half_spread, 2)

            bid_qty = random.randint(100, 3000)
            ask_qty = random.randint(100, 3000)

            # Volume
            vol_inc = random.randint(10, 300) if not symbol.startswith("^") else 0
            state["volume"] += vol_inc

            # Create tick record
            tick = HistoricalTick(
                symbol=symbol,
                timestamp=current_time,
                price=Decimal(str(new_price)),
                volume=state["volume"],
                oi=0,
                bid_price=Decimal(str(bid)),
                ask_price=Decimal(str(ask)),
                bid_qty=bid_qty,
                ask_qty=ask_qty,
                exchange=config["exchange"],
            )
            ticks_to_insert.append(tick)
            total_ticks += 1

    print(f"Generated {total_ticks} ticks. Inserting into database...")

    # Batch insert in chunks of 5000
    chunk_size = 5000
    async with async_session_factory() as db:
        try:
            # First, clear existing ticks for this date to avoid duplicates
            await db.execute(
                text(
                    "DELETE FROM historical_ticks WHERE DATE(timestamp) = :d"
                ),
                {"d": start_time.date()},
            )
            await db.commit()

            for i in range(0, len(ticks_to_insert), chunk_size):
                chunk = ticks_to_insert[i : i + chunk_size]
                db.add_all(chunk)
                await db.commit()
                print(
                    f"Inserted {i + len(chunk)} / {len(ticks_to_insert)} ticks..."
                )

            print("Database seeding completed successfully!")
        except Exception as e:
            await db.rollback()
            print(f"Seeding failed: {e}")


if __name__ == "__main__":
    days = 1
    if len(sys.argv) > 1:
        try:
            days = int(sys.argv[1])
        except ValueError:
            pass

    asyncio.run(seed_historical_ticks(days_ago=days, duration_minutes=30))

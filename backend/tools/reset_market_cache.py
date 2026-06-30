"""
Clear market-data cache entries so fresh Zebu data can repopulate Redis.

Usage:
  python tools/reset_market_cache.py
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cache.redis_client import clear_market_cache


async def main() -> int:
    result = await clear_market_cache()
    deleted = int(result.get("deleted", 0))
    print(f"Deleted {deleted} market cache keys")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

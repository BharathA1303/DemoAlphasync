import asyncio
import csv
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Optional
from sqlalchemy import select, insert, text

from database.connection import async_session_factory
from models.data_feed_config import DataFeedConfig
from models.symbol_master import SymbolMaster
from models.raw_ticks import RawTick
from models.bulk_file_index import BulkFileIndex
from providers.zebu_oauth_client import ZebuLiveFeed, ZEBU_WS_PROD_URL

logger = logging.getLogger(__name__)

DEFAULT_BULK_DIR = Path("/data/bulk")


class LiveFeedIngestionWorker:
    """Single-process worker that ingests live Zebu WebSocket ticks.
    - Equity/Index ticks -> postgres `raw_ticks` table (batched inserts)
    - F&O/Commodity ticks -> rotating CSV bulk files + `bulk_file_index`
    """

    def __init__(self, bulk_dir: Optional[Path] = None):
        self.bulk_dir = bulk_dir or DEFAULT_BULK_DIR
        self._is_running = False
        self._ws_feed: Optional[ZebuLiveFeed] = None
        self._tick_queue: asyncio.Queue = asyncio.Queue(maxsize=10000)
        self._flush_task: Optional[asyncio.Task] = None

        # Metrics
        self.ticks_ingested_today = 0
        self.last_tick_timestamp: Optional[datetime] = None
        self.last_error: Optional[str] = None
        self.subscribed_count = 0

        # CSV writers cache
        self._csv_files: Dict[str, dict] = {}

    async def start(self):
        """Initialize and start live ingestion worker."""
        if self._is_running:
            return
        self._is_running = True
        self.bulk_dir.mkdir(parents=True, exist_ok=True)

        self._flush_task = asyncio.create_task(self._flush_loop())

        async with async_session_factory() as session:
            stmt = select(DataFeedConfig).limit(1)
            res = await session.execute(stmt)
            config = res.scalar_one_or_none()

            if not config or config.oauth_connection_status != "connected":
                logger.info("Zebu OAuth not connected. LiveIngestionWorker standing by.")
                return

            client_code = config.oauth_client_id
            access_token = config.get_oauth_access_token()

            if not client_code or not access_token:
                logger.warning("Missing OAuth credentials for Zebu WS. Ingestion worker dormant.")
                return

            ws_url = getattr(config, "base_url", None) or ZEBU_WS_PROD_URL

            self._ws_feed = ZebuLiveFeed(
                ws_url=ws_url,
                client_code=client_code,
                access_token=access_token,
                on_tick_callback=self._handle_tick,
                on_error_callback=self._handle_error,
            )

            # Load subscriptions from symbol_master
            sm_stmt = (
                select(SymbolMaster.exchange, SymbolMaster.token)
                .where(SymbolMaster.is_active.is_(True))
                .limit(2000)
            )
            sm_res = await session.execute(sm_stmt)
            scrip_pairs = sm_res.fetchall()
            scrips = [f"{ex}|{tk}" for ex, tk in scrip_pairs]
            self.subscribed_count = len(scrips)

            await self._ws_feed.start()
            if scrips:
                await self._ws_feed.subscribe(scrips)
                logger.info(f"Subscribed ZebuLiveFeed to {len(scrips)} scrips")

    async def stop(self):
        """Stop ingestion worker and flush remaining buffers."""
        self._is_running = False
        if self._ws_feed:
            await self._ws_feed.stop()
        if self._flush_task:
            self._flush_task.cancel()
        await self._close_csv_files()

    async def _handle_tick(self, data: dict):
        """Enqueue tick for asynchronous batch processing."""
        if self._tick_queue.full():
            try:
                self._tick_queue.get_nowait()  # Drop oldest tick under backpressure
            except asyncio.QueueEmpty:
                pass

        await self._tick_queue.put(data)

    async def _handle_error(self, err_msg: str):
        self.last_error = err_msg
        logger.error(f"LiveIngestionWorker error: {err_msg}")

    async def _flush_loop(self):
        """Periodically flush queued ticks to Postgres and CSV files."""
        db_buffer: List[Dict] = []
        last_flush_time = asyncio.get_event_loop().time()

        while self._is_running:
            try:
                try:
                    tick = await asyncio.wait_for(self._tick_queue.get(), timeout=0.25)
                    parsed = self._parse_tick(tick)
                    if parsed:
                        ex = parsed["exchange"]
                        instr = parsed.get("instrument_type", "EQ")

                        if ex in ("NSE", "BSE") and instr in ("EQ", "INDEX"):
                            db_buffer.append(parsed)
                        else:
                            await self._write_csv_tick(parsed)

                        self.ticks_ingested_today += 1
                        self.last_tick_timestamp = parsed["real_timestamp"]
                except asyncio.TimeoutError:
                    pass

                now_time = asyncio.get_event_loop().time()
                if db_buffer and (len(db_buffer) >= 200 or (now_time - last_flush_time) >= 0.25):
                    await self._flush_db_buffer(db_buffer)
                    db_buffer.clear()
                    last_flush_time = now_time

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in LiveIngestionWorker flush loop: {e}")
                await asyncio.sleep(0.5)

        if db_buffer:
            await self._flush_db_buffer(db_buffer)

    def _parse_tick(self, data: dict) -> Optional[Dict]:
        """Normalize raw Zebu WS tick into standardized dictionary."""
        try:
            ex = data.get("e") or "NSE"
            token = data.get("tk") or ""
            symbol = data.get("ts") or data.get("s") or token
            ltp = float(data.get("lp") or data.get("c") or 0.0)

            if ltp <= 0.0:
                return None

            now_time = datetime.now(timezone.utc)
            ft_str = data.get("ft")
            if ft_str:
                try:
                    real_ts = datetime.fromtimestamp(int(ft_str), tz=timezone.utc)
                except (ValueError, TypeError):
                    real_ts = now_time
            else:
                real_ts = now_time

            return {
                "exchange": ex.upper(),
                "token": token,
                "symbol": symbol.upper(),
                "instrument_type": "EQ",
                "ltp": ltp,
                "open": float(data.get("o")) if data.get("o") else None,
                "high": float(data.get("h")) if data.get("h") else None,
                "low": float(data.get("l")) if data.get("l") else None,
                "close": float(data.get("c")) if data.get("c") else None,
                "volume": int(data.get("v") or 0),
                "best_bid": float(data.get("bp1")) if data.get("bp1") else None,
                "best_ask": float(data.get("sp1")) if data.get("sp1") else None,
                "real_timestamp": real_ts,
            }
        except Exception:
            return None

    async def _flush_db_buffer(self, buffer: List[Dict]):
        """Batch insert ticks into raw_ticks table."""
        if not buffer:
            return
        async with async_session_factory() as session:
            try:
                stmt = insert(RawTick).values(buffer)
                await session.execute(stmt)
                await session.commit()
            except Exception as e:
                logger.error(f"Failed to batch insert {len(buffer)} ticks to Postgres: {e}")

    async def _write_csv_tick(self, tick: Dict):
        """Append F&O tick to rotating CSV file."""
        ex = tick["exchange"]
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        file_dir = self.bulk_dir / ex / today_str
        file_dir.mkdir(parents=True, exist_ok=True)

        file_path = file_dir / f"{ex}_ticks_{today_str}.csv"
        file_key = str(file_path)

        if file_key not in self._csv_files:
            file_exists = file_path.exists()
            f_handle = open(file_path, "a", newline="", encoding="utf-8")
            writer = csv.writer(f_handle)
            if not file_exists:
                writer.writerow([
                    "real_timestamp", "exchange", "token", "symbol",
                    "ltp", "open", "high", "low", "close", "volume", "bid", "ask"
                ])
            self._csv_files[file_key] = {"handle": f_handle, "writer": writer, "rows": 0}

        entry = self._csv_files[file_key]
        entry["writer"].writerow([
            tick["real_timestamp"].isoformat(),
            tick["exchange"],
            tick["token"],
            tick["symbol"],
            tick["ltp"],
            tick["open"] or "",
            tick["high"] or "",
            tick["low"] or "",
            tick["close"] or "",
            tick["volume"],
            tick["best_bid"] or "",
            tick["best_ask"] or "",
        ])
        entry["rows"] += 1

        if entry["rows"] % 100 == 0:
            entry["handle"].flush()

    async def _close_csv_files(self):
        for key, entry in list(self._csv_files.items()):
            try:
                entry["handle"].flush()
                entry["handle"].close()
            except Exception:
                pass
        self._csv_files.clear()

    def get_status(self) -> dict:
        return {
            "is_running": self._is_running,
            "subscribed_count": self.subscribed_count,
            "ticks_ingested_today": self.ticks_ingested_today,
            "last_tick_timestamp": self.last_tick_timestamp.isoformat() if self.last_tick_timestamp else None,
            "last_error": self.last_error,
            "queue_size": self._tick_queue.qsize(),
        }


# Global singleton worker instance
live_ingestion_worker = LiveFeedIngestionWorker()

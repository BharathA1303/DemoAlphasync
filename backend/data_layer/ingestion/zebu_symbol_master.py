import csv
import io
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.symbol_master import SymbolMaster

logger = logging.getLogger(__name__)


def parse_date(date_str: str) -> Optional[datetime.date]:
    if not date_str or date_str in ("-", "XX", "0"):
        return None
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            pass
    return None


def parse_float(val: str, default: float = 0.0) -> float:
    if not val or val == "-":
        return default
    try:
        return float(val.strip())
    except ValueError:
        return default


def parse_int(val: str, default: int = 1) -> int:
    if not val or val == "-":
        return default
    try:
        return int(float(val.strip()))
    except ValueError:
        return default


class ZebuSymbolMasterService:
    """Ingestion & normalization service for Zebu symbol master files across exchanges."""

    @staticmethod
    def parse_symbol_content(exchange: str, content: str) -> List[Dict]:
        """Parse raw text content of exchange symbol master CSV into normalized symbol dicts."""
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        if not lines:
            return []

        reader = csv.reader(lines)
        raw_header = next(reader, None)
        if not raw_header:
            return []

        header = [h.strip() for h in raw_header if h.strip()]
        col_map = {name: i for i, name in enumerate(header)}

        parsed_rows = []
        now_utc = datetime.now(timezone.utc)

        for row in reader:
            if not row or len(row) < 3:
                continue

            try:
                ex = row[col_map.get("Exchange", 0)].strip() if "Exchange" in col_map else exchange.upper()
                token = row[col_map.get("Token", 1)].strip()
                symbol = row[col_map.get("Symbol", 3)].strip() if "Symbol" in col_map else ""
                trading_symbol = row[col_map.get("TradingSymbol", 4)].strip() if "TradingSymbol" in col_map else symbol
                instrument = row[col_map.get("Instrument", 5)].strip() if "Instrument" in col_map else "EQ"
                lot_size = parse_int(row[col_map["LotSize"]]) if "LotSize" in col_map else 1
                tick_size = parse_float(row[col_map["TickSize"]], 0.05) if "TickSize" in col_map else 0.05

                expiry_str = row[col_map["Expiry"]].strip() if "Expiry" in col_map and col_map["Expiry"] < len(row) else None
                expiry = parse_date(expiry_str) if expiry_str else None

                strike_col = "StrikePrice" if "StrikePrice" in col_map else ("Strike" if "Strike" in col_map else None)
                strike = parse_float(row[col_map[strike_col]]) if strike_col and col_map[strike_col] < len(row) else None

                opt_type = row[col_map["OptionType"]].strip() if "OptionType" in col_map and col_map["OptionType"] < len(row) else None
                if opt_type in ("-", "XX", ""):
                    opt_type = None

                # Filtering rules to filter out unusable junk symbols
                if ex == "BSE" and instrument == "F" and symbol and symbol[0].isdigit():
                    continue  # Skip numeric-prefixed BSE fixed income rows

                parsed_rows.append({
                    "exchange": ex,
                    "token": token,
                    "symbol": symbol,
                    "trading_symbol": trading_symbol,
                    "instrument_type": instrument,
                    "lot_size": lot_size,
                    "tick_size": tick_size,
                    "expiry": expiry,
                    "strike": strike if (strike and strike > 0) else None,
                    "option_type": opt_type,
                    "is_active": True,
                    "synced_at": now_utc,
                })
            except Exception as e:
                logger.debug(f"Skipping unparseable symbol row in {exchange}: {row} ({e})")
                continue

        return parsed_rows

    @classmethod
    async def sync_from_local_folder(cls, session: AsyncSession, folder_path: Path) -> dict:
        """Sync symbol master table directly from a local folder containing symbol text files."""
        summary = {}
        if not folder_path.exists():
            raise FileNotFoundError(f"Symbol folder not found: {folder_path}")

        files_map = {
            "NSE": ["NSE_symbols.txt"],
            "BSE": ["BSE_symbols.txt"],
            "NFO": ["NFO_symbols.txt"],
            "BFO": ["BFO_symbols.txt"],
            "MCX": ["MCX_symbols.txt"],
        }

        for exchange, filenames in files_map.items():
            matched_file = None
            for fn in filenames:
                fp = folder_path / fn
                if fp.exists():
                    matched_file = fp
                    break

            if not matched_file:
                logger.warning(f"No file found for exchange {exchange} under {folder_path}")
                continue

            content = matched_file.read_text(encoding="utf-8", errors="ignore")
            parsed = cls.parse_symbol_content(exchange, content)
            inserted_count = await cls._upsert_symbols(session, exchange, parsed)
            summary[exchange] = inserted_count

        return summary

    @classmethod
    async def _upsert_symbols(cls, session: AsyncSession, exchange: str, rows: List[Dict]) -> int:
        """Upsert parsed symbol rows into symbol_master table efficiently."""
        if not rows:
            return 0

        # Mark missing symbols inactive for this exchange
        sync_time = datetime.now(timezone.utc)
        
        for batch in [rows[i : i + 1000] for i in range(0, len(rows), 1000)]:
            for item in batch:
                stmt = select(SymbolMaster).where(
                    SymbolMaster.exchange == item["exchange"],
                    SymbolMaster.token == item["token"]
                )
                res = await session.execute(stmt)
                existing = res.scalar_one_or_none()

                if existing:
                    existing.symbol = item["symbol"]
                    existing.trading_symbol = item["trading_symbol"]
                    existing.instrument_type = item["instrument_type"]
                    existing.lot_size = item["lot_size"]
                    existing.tick_size = item["tick_size"]
                    existing.expiry = item["expiry"]
                    existing.strike = item["strike"]
                    existing.option_type = item["option_type"]
                    existing.is_active = True
                    existing.synced_at = sync_time
                else:
                    new_sym = SymbolMaster(**item)
                    session.add(new_sym)

        await session.commit()
        return len(rows)

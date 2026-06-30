"""
AI Mentor routes — Grok-powered chat endpoint.

Flow:
    1. Frontend sends user message to POST /api/mentor
    2. Backend verifies user authentication
    3. Backend calls provider API with system prompt
    4. Backend returns AI response
    5. Frontend displays the response
"""

import logging
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.grok_config import grok_config
from database.connection import get_db
from engines.market_session import market_session
from models.algo import AlgoStrategy
from models.futures_order import FuturesOrder, FuturesPosition
from models.order import Order
from models.portfolio import Holding, Portfolio
from models.user import User
from routes.auth import get_current_user
from strategies.zeroloss.manager import zeroloss_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mentor", tags=["AI Mentor"])

DISCLAIMER = "Educational only — not SEBI investment advice."
WELCOME_MESSAGE = (
    "Hi, I'm Sarah — your AlphaSync mentor. I can help with product navigation, "
    "F&O basics, position risk checks, and safe trade steps. Tell me your question "
    "or paste your position details."
)
OUT_OF_SCOPE_REFUSAL = (
    "I can only help with AlphaSync feature usage and Indian stock market learning. "
    "I can’t assist with that request. Ask me about watchlists, portfolio, orders, "
    "strategies, or risk management instead."
)
SENSITIVE_REFUSAL = (
    "I can only help with AlphaSync feature usage and Indian stock market learning. "
    "I can’t share source code, internal systems, secrets, or private user data. "
    "I can guide you with exact in-app routes for features you want to use."
)
FINAL_INSTRUCTION_PREFIX = "=== INSTRUCTION ==="


_LEGACY_PREFIXES = [
    "reply in very simple words for a beginner trader in india. focus only on indian markets and alphasync usage.",
]

_OUT_OF_SCOPE_TERMS = {
    "weather",
    "movie",
    "cinema",
    "cricket",
    "football",
    "politics",
    "election",
    "medical",
    "doctor",
    "diagnosis",
    "legal advice",
    "court",
    "religion",
    "horoscope",
    "astrology",
    "recipe",
    "coding",
    "python code",
    "javascript",
    "us stock",
    "nasdaq",
    "nyse",
    "s&p 500",
    "dow jones",
    "bitcoin",
    "ethereum",
    "forex",
    "claude",
    "anthropic",
}

_SENSITIVE_ALPHA_TERMS = {
    "source code",
    "backend code",
    "frontend code",
    "internal code",
    "database schema",
    "db schema",
    "api key",
    "secret key",
    "access token",
    "password",
    "credentials",
    "server config",
    "production config",
    "internal architecture",
    "private endpoint",
    "provider key",
    "llm key",
    "model key",
    "claude",
    "anthropic",
    "user email",
    "user phone",
    "personal info",
    "personal information",
    "kyc details",
    "account number",
}


def _normalize_user_message(message: str) -> str:
    """Normalize user text and strip known legacy instruction prefixes."""
    raw = (message or "").strip()
    if not raw:
        return ""

    lowered = raw.lower()
    for prefix in _LEGACY_PREFIXES:
        if lowered.startswith(prefix):
            cleaned = raw[len(prefix) :].lstrip("\n\r\t :-")
            return cleaned or raw

    return raw


def _extract_ai_reply(payload: dict) -> str:
    """Extract assistant text from chat-completions payload variants."""
    if not isinstance(payload, dict):
        return ""

    choices = payload.get("choices") or []
    if not choices:
        return ""

    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        chunks = [part.get("text", "") for part in content if isinstance(part, dict)]
        return "".join(chunks).strip()

    return ""


def _build_warm_scope_redirect() -> str:
    return (
        "I can only help with AlphaSync usage and Indian stock market learning. "
        "I can’t help with that topic, but I can guide you on AlphaSync features, "
        "NSE/BSE basics, orders, portfolio, risk control, and in-app navigation steps."
    )


def _build_sensitive_refusal() -> str:
    return (
        "I can only help with AlphaSync feature usage and Indian stock market learning. "
        "I can’t share AlphaSync code, internal systems, secrets, or personal user information. "
        "I can guide you with exact in-app routes for features you want to use."
    )


def _build_warm_scope_redirect() -> str:
    return _ensure_disclaimer(OUT_OF_SCOPE_REFUSAL)


def _build_sensitive_refusal() -> str:
    return _ensure_disclaimer(SENSITIVE_REFUSAL)


def _is_out_of_scope_query(message: str) -> bool:
    text = (message or "").strip().lower()
    if not text:
        return False
    return any(term in text for term in _OUT_OF_SCOPE_TERMS)


def _is_sensitive_alpha_query(message: str) -> bool:
    text = (message or "").strip().lower()
    if not text:
        return False
    return any(term in text for term in _SENSITIVE_ALPHA_TERMS)


def _money(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _first_name(user: User) -> str:
    name = (user.full_name or user.username or "").strip()
    return (name.split()[0] if name else "Trader")[:40]


def _ensure_disclaimer(reply: str) -> str:
    text = (reply or "").strip()
    if not text:
        text = "I can help with AlphaSync usage, Indian market learning, and safer trade steps."
    without_duplicates = text.replace(DISCLAIMER, "").strip()
    return f"{without_duplicates}\n\n{DISCLAIMER}"


def _sanitize_reply(reply: str) -> str:
    text = (reply or "").strip()
    lowered = text.lower()
    if "api key" in lowered or "secret" in lowered or "credential" in lowered:
        return _build_sensitive_refusal()
    text = text.replace("Alex", "Sarah")
    return _ensure_disclaimer(text)


def _format_recent_messages(messages: list["RecentMessage"]) -> str:
    normalized = [
        {
            "role": item.role,
            "content": item.content[:1200],
            "timestamp": item.timestamp,
        }
        for item in (messages or [])[-6:]
        if item.content and item.role in {"user", "assistant"}
    ]
    return json.dumps(normalized, ensure_ascii=False)


def _assemble_model_prompt(user_context: dict[str, Any], recent_messages: list["RecentMessage"]) -> str:
    return "\n".join(
        [
            grok_config.MENTOR_SYSTEM_PROMPT,
            "=== USER CONTEXT ===",
            json.dumps(user_context, ensure_ascii=False, default=str),
            "=== RECENT MESSAGES ===",
            _format_recent_messages(recent_messages),
            FINAL_INSTRUCTION_PREFIX,
            grok_config.FINAL_INSTRUCTION,
        ]
    )


def _build_route_map_reply(message: str) -> str:
    text = (message or "").strip().lower()

    if any(word in text for word in ["add capital", "reset capital", "capital", "funds"]):
        return (
            "Route: Sidebar → Settings → Trading → Capital Management → Add Capital / Reset Capital\n"
            "Steps:\n"
            "1) Open Settings from the left sidebar.\n"
            "2) Go to the Trading section.\n"
            "3) Scroll to Capital Management.\n"
            "4) Use Add Capital to increase funds or Reset Capital to return to default."
        )

    if any(word in text for word in ["reset account", "clear account", "delete all positions"]):
        return (
            "Route: Sidebar → Settings → Trading → Account Reset → Reset Account\n"
            "Steps:\n"
            "1) Open Settings from the left sidebar.\n"
            "2) Go to Trading section.\n"
            "3) Find Account Reset and click Reset Account.\n"
            "4) Confirm the warning to continue."
        )

    if any(word in text for word in ["order", "orders", "order history"]):
        return "Route: Sidebar → Orders\nYou can view pending, completed, and rejected orders there."

    if any(word in text for word in ["portfolio", "holdings", "p&l"]):
        return "Route: Sidebar → Portfolio\nYou can view holdings, invested value, and P&L from this page."

    if any(word in text for word in ["watchlist", "market watch", "symbol list"]):
        return "Route: Sidebar → Market\nUse Market to track symbols and build your watchlist quickly."

    if any(word in text for word in ["where", "how to", "how do i", "settings", "route", "map"]):
        return (
            "Route Map:\n"
            "- Dashboard: Sidebar → Dashboard\n"
            "- Terminal: Sidebar → Terminal\n"
            "- Market: Sidebar → Market\n"
            "- Portfolio: Sidebar → Portfolio\n"
            "- Orders: Sidebar → Orders\n"
            "- AI Mentor: Sidebar → AI Mentor\n"
            "- Capital tools: Sidebar → Settings → Trading"
        )

    return ""


def _build_fallback_reply(message: str) -> str:
    """Generate simple Indian-market-focused fallback reply."""
    text = message.strip().lower()
    compact = " ".join(text.split())

    route_help = _build_route_map_reply(message)
    if route_help:
        return route_help

    if _is_sensitive_alpha_query(message):
        return _build_sensitive_refusal()

    if _is_out_of_scope_query(message):
        return _build_warm_scope_redirect()

    if not text:
        return (
            "I can help with AlphaSync, Indian stocks, watchlists, portfolio, orders, and safe trading habits. "
            "Ask me a simple question and I will explain in easy words."
        )

    if compact in {"bye", "goodbye", "see you", "see you later", "thanks", "thank you"}:
        return "Happy to help. Take care and come back anytime if you want to learn more about AlphaSync or Indian markets."

    if compact in {"hey", "hi", "hii", "hello", "hello mentor", "hey mentor", "hii mentor"}:
        return (
            "Hello. I can explain AlphaSync features, Indian stock market basics, watchlists, "
            "portfolio, orders, and safe trading in simple words."
        )

    if "what is trading" in text or "define trading" in text or text.startswith("what is trade"):
        return (
            "Trading means buying and selling market products like stocks to benefit from price movement. "
            "In simple terms, buy at a good price and sell with a plan, always using stop-loss."
        )

    if any(phrase in text for phrase in ["what is risk management", "define risk", "risk management"]):
        return (
            "Risk management means protecting your money first. Keep trade size small, place stop-loss, "
            "set a daily loss limit, and avoid overtrading."
        )

    if any(phrase in text for phrase in ["what is portfolio", "portfolio management", "manage my portfolio"]):
        return (
            "Portfolio management means tracking what stocks you hold, how much money is invested, "
            "and when to rebalance or book profits."
        )

    if any(phrase in text for phrase in ["what is indicator", "what are indicators", "rsi", "macd", "ema", "sma"]):
        return (
            "Indicators are helper tools to understand trend and momentum. "
            "Use them as support, not as the only reason to take a trade."
        )

    if any(phrase in text for phrase in ["what is chart", "candlestick", "candle", "timeframe"]):
        return (
            "A chart shows price movement over time. Candles help you see whether buyers or sellers are stronger."
        )

    if any(phrase in text for phrase in ["what is zero loss", "zero loss", "zeroloss", "zll", "alpha auto"]):
        return (
            "Alpha Auto is the strategy section in AlphaSync. It helps you follow a planned process "
            "with better discipline and safer trade handling."
        )

    if any(word in text for word in ["stop loss", "stoploss", "sl order"]):
        return (
            "A stop-loss is a pre-set exit that limits loss if price goes against you. "
            "It is one of the most important safety rules in trading."
        )

    if any(word in text for word in ["risk", "loss", "drawdown"]):
        return (
            "The safest way to trade is to decide maximum loss first, then choose position size. "
            "If the loss feels too large, reduce the quantity."
        )

    if any(word in text for word in ["portfolio", "p&l", "profit", "loss"]):
        return (
            "Your portfolio is the list of stocks you own. Review profits/losses regularly and avoid too much concentration in one stock."
        )

    if any(word in text for word in ["watchlist", "watch list", "scrip", "symbol"]):
        return "A watchlist is your shortlist of stocks to monitor and trade with focus."

    if any(word in text for word in ["order", "limit", "market order", "slippage"]):
        return "Orders are how you buy or sell. Limit order gives price control, market order gives faster execution."

    return (
        "I can help with AlphaSync and Indian market topics in simple words. "
        "Ask me about NIFTY, SENSEX, stocks, watchlist, portfolio, orders, stop-loss, or Alpha Auto."
    )


async def _build_user_context(
    db: AsyncSession,
    user: User,
    *,
    client_time: Optional[str] = None,
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    portfolio_result = await db.execute(
        select(Portfolio).where(Portfolio.user_id == user.id)
    )
    portfolio = portfolio_result.scalar_one_or_none()

    holdings: list[Holding] = []
    if portfolio:
        holdings_result = await db.execute(
            select(Holding)
            .where(Holding.portfolio_id == portfolio.id, Holding.quantity != 0)
            .limit(8)
        )
        holdings = list(holdings_result.scalars().all())

    futures_positions_result = await db.execute(
        select(FuturesPosition)
        .where(FuturesPosition.user_id == user.id, FuturesPosition.quantity != 0)
        .limit(8)
    )
    futures_positions = list(futures_positions_result.scalars().all())

    open_positions: list[dict[str, Any]] = [
        {
            "symbol": holding.symbol,
            "qty": int(holding.quantity or 0),
            "entry": _money(holding.avg_price),
            "cmp": _money(holding.current_price),
            "pnl_inr": _money(holding.pnl),
            "type": "equity",
        }
        for holding in holdings
    ]
    open_positions.extend(
        {
            "symbol": position.contract_symbol,
            "qty": int(position.quantity or 0),
            "entry": _money(position.avg_entry_price),
            "cmp": _money(position.current_price),
            "pnl_inr": _money(position.unrealized_pnl),
            "type": "futures",
        }
        for position in futures_positions
    )

    orders_result = await db.execute(
        select(Order)
        .where(Order.user_id == user.id)
        .order_by(Order.created_at.desc())
        .limit(5)
    )
    orders = list(orders_result.scalars().all())

    futures_orders_result = await db.execute(
        select(FuturesOrder)
        .where(FuturesOrder.user_id == user.id)
        .order_by(FuturesOrder.created_at.desc())
        .limit(3)
    )
    futures_orders = list(futures_orders_result.scalars().all())

    recent_orders = [
        {
            "symbol": order.symbol,
            "side": order.side,
            "qty": int(order.quantity or 0),
            "price": _money(order.filled_price or order.price),
            "status": order.status,
            "created_at": _iso(order.created_at),
        }
        for order in orders
    ]
    recent_orders.extend(
        {
            "symbol": order.contract_symbol,
            "side": order.side,
            "qty": int(order.quantity or 0),
            "price": _money(order.filled_price or order.price),
            "status": order.status,
            "created_at": _iso(order.created_at),
        }
        for order in futures_orders
    )
    recent_orders.sort(key=lambda item: item.get("created_at") or "", reverse=True)

    strategy_result = await db.execute(
        select(AlgoStrategy)
        .where(AlgoStrategy.user_id == user.id, AlgoStrategy.is_active.is_(True))
        .order_by(AlgoStrategy.updated_at.desc())
        .limit(1)
    )
    active_strategy = strategy_result.scalar_one_or_none()

    try:
        alpha_auto_enabled = await zeroloss_manager.is_user_enabled(user.id)
    except Exception:
        logger.exception("Failed to read Alpha Auto status for mentor context")
        alpha_auto_enabled = False

    session = market_session.get_session_info()
    market_status = "OPEN" if session.get("state") == "open" else "CLOSED"
    pnl_value = _money(portfolio.total_pnl if portfolio else 0)
    pnl_value += sum(_money(position.unrealized_pnl) for position in futures_positions)

    return {
        "user_id": str(user.id),
        "first_name": _first_name(user),
        "available_capital_inr": _money(
            portfolio.available_capital if portfolio else user.virtual_capital
        ),
        "pnl_today_inr": pnl_value,
        "invested_capital_inr": _money(portfolio.total_invested if portfolio else 0),
        "open_positions": open_positions[:10],
        "recent_orders": recent_orders[:6],
        "active_strategy": active_strategy.name if active_strategy else None,
        "alpha_auto_status": "ON" if alpha_auto_enabled else "OFF",
        "market_status": market_status,
        "client_locale": "en-IN",
        "session_id": session_id,
        "client_time": client_time or datetime.now(timezone.utc).isoformat(),
    }


def _risk_level_from_context(user_context: dict[str, Any]) -> str:
    available = _money(user_context.get("available_capital_inr"))
    invested = _money(user_context.get("invested_capital_inr"))
    pnl_today = _money(user_context.get("pnl_today_inr"))
    open_positions = user_context.get("open_positions") or []
    capital_base = max(available + invested, 1.0)
    exposure_ratio = invested / capital_base
    pnl_ratio = abs(pnl_today) / capital_base

    if pnl_today < 0 and (pnl_ratio >= 0.02 or len(open_positions) >= 5 or exposure_ratio >= 0.75):
        return "high"
    if pnl_today < 0 or exposure_ratio >= 0.45 or len(open_positions) >= 3:
        return "medium"
    return "low"


class RecentMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(default="", max_length=2000)
    timestamp: Optional[Any] = None


class MentorMessageRequest(BaseModel):
    """User message payload."""

    message: str
    recent_messages: list[RecentMessage] = Field(default_factory=list, max_length=8)
    client_time: Optional[str] = None
    session_id: Optional[str] = None


class MentorMessageResponse(BaseModel):
    """AI Mentor response payload."""

    reply: str
    success: bool = True
    error: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None


@router.post("", response_model=MentorMessageResponse)
async def chat_with_mentor(
    request: MentorMessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MentorMessageResponse:
    """Chat with AI Mentor."""
    api_key = grok_config.get_api_key()
    user_message = _normalize_user_message(request.message)

    if not user_message or len(user_message) > 2000:
        raise HTTPException(
            status_code=400,
            detail="Message must be between 1 and 2000 characters",
        )

    if _is_sensitive_alpha_query(user_message):
        return MentorMessageResponse(reply=_build_sensitive_refusal(), success=True)

    if _is_out_of_scope_query(user_message):
        return MentorMessageResponse(reply=_build_warm_scope_redirect(), success=True)

    user_context = await _build_user_context(
        db,
        current_user,
        client_time=request.client_time,
        session_id=request.session_id,
    )

    if not api_key:
        logger.warning("Mentor API key not configured")
        return MentorMessageResponse(
            reply=_ensure_disclaimer(_build_fallback_reply(user_message)),
            success=True,
        )

    try:
        provider = grok_config.get_provider(api_key)
        api_url = grok_config.get_api_url(api_key)
        model = grok_config.get_model(api_key)

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": _assemble_model_prompt(
                        user_context,
                        request.recent_messages[-6:],
                    ),
                },
                {"role": "user", "content": user_message},
            ],
            "max_tokens": grok_config.MAX_TOKENS,
            "temperature": grok_config.TEMPERATURE,
            "top_p": grok_config.TOP_P,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                api_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            fallback_model = (
                grok_config.GROQ_DEFAULT_MODEL
                if provider == "groq"
                else grok_config.XAI_DEFAULT_MODEL
            )
            if response.status_code == 400 and model != fallback_model:
                body_text = (response.text or "").lower()
                if "model" in body_text:
                    payload["model"] = fallback_model
                    response = await client.post(
                        api_url,
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )

        if response.status_code != 200:
            logger.error("Mentor API error: %s - %s", response.status_code, response.text)
            return MentorMessageResponse(
                reply=_ensure_disclaimer(_build_fallback_reply(user_message)),
                success=True,
            )

        data = response.json()
        ai_reply = _extract_ai_reply(data)

        if not ai_reply:
            logger.warning("Mentor API returned empty response")
            return MentorMessageResponse(
                reply=_ensure_disclaimer(_build_fallback_reply(user_message)),
                success=True,
            )

        logger.info("Mentor response generated for user %s", current_user.id)
        return MentorMessageResponse(
            reply=_sanitize_reply(ai_reply),
            success=True,
            provider=provider,
            model=payload.get("model"),
        )

    except httpx.TimeoutException:
        logger.error("Mentor API timeout")
        return MentorMessageResponse(
            reply=_ensure_disclaimer(_build_fallback_reply(user_message)),
            success=True,
        )

    except httpx.RequestError as exc:
        logger.error("Mentor API request error: %s", exc)
        return MentorMessageResponse(
            reply=_ensure_disclaimer(_build_fallback_reply(user_message)),
            success=True,
        )

    except Exception as exc:
        logger.error("Unexpected mentor error: %s", exc)
        return MentorMessageResponse(
            reply=_ensure_disclaimer(_build_fallback_reply(user_message)),
            success=True,
        )


@router.get("/status", tags=["AI Mentor"])
async def mentor_status():
    """Check if AI Mentor is available and configured."""
    is_configured, message = grok_config.validate()
    api_key = grok_config.get_api_key()
    provider = grok_config.get_provider(api_key) if is_configured else None
    return {
        "available": is_configured,
        "status": message,
        "provider": provider,
        "model": (grok_config.get_model(api_key) if is_configured else None),
    }


@router.get("/welcome", tags=["AI Mentor"])
async def mentor_welcome():
    """Stateless welcome copy for a new mentor session."""
    return {"message": _ensure_disclaimer(WELCOME_MESSAGE)}


@router.get("/context-hints", tags=["AI Mentor"])
async def mentor_context_hints(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Lightweight live risk hints for the frontend without storing chats."""
    context = await _build_user_context(db, current_user)
    return {
        "risk_level": _risk_level_from_context(context),
        "pnl_today_inr": context["pnl_today_inr"],
        "open_positions_count": len(context["open_positions"]),
        "market_status": context["market_status"],
        "alpha_auto_status": context["alpha_auto_status"],
    }

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from firebase_admin import auth as firebase_auth

from models.user import User, UserSession, AdminSession, TwoFactorAuth, EmailNotificationLog
from models.order import Order
from models.portfolio import Portfolio, Holding, Transaction
from models.watchlist import Watchlist, WatchlistItem
from models.algo import AlgoStrategy, AlgoTrade, AlgoLog
from models.broker import BrokerAccount
from models.futures_order import FuturesOrder, FuturesPosition
from strategies.zeroloss.models import ZeroLossSignal, ZeroLossPerformance, ZeroLossRuntimeState
from services import admin_group_service

logger = logging.getLogger(__name__)


async def purge_user_account_data(db: AsyncSession, user_id: UUID) -> dict[str, Any]:
    """Permanently remove all known account-linked data for a user."""
    summary: dict[str, Any] = {
        "user_id": str(user_id),
        "deleted_at": datetime.now(timezone.utc).isoformat(),
    }

    portfolio_result = await db.execute(
        select(Portfolio.id).where(Portfolio.user_id == user_id)
    )
    portfolio_ids = [row[0] for row in portfolio_result.all()]

    strategy_result = await db.execute(
        select(AlgoStrategy.id).where(AlgoStrategy.user_id == user_id)
    )
    strategy_ids = [row[0] for row in strategy_result.all()]

    watchlist_result = await db.execute(
        select(Watchlist.id).where(Watchlist.user_id == user_id)
    )
    watchlist_ids = [row[0] for row in watchlist_result.all()]

    if watchlist_ids:
        watchlist_items_res = await db.execute(
            delete(WatchlistItem).where(WatchlistItem.watchlist_id.in_(watchlist_ids))
        )
        summary["watchlist_items"] = int(watchlist_items_res.rowcount or 0)

    if portfolio_ids:
        holdings_res = await db.execute(
            delete(Holding).where(Holding.portfolio_id.in_(portfolio_ids))
        )
        summary["holdings"] = int(holdings_res.rowcount or 0)

    tx_res = await db.execute(delete(Transaction).where(Transaction.user_id == user_id))
    summary["transactions"] = int(tx_res.rowcount or 0)

    orders_res = await db.execute(delete(Order).where(Order.user_id == user_id))
    summary["orders"] = int(orders_res.rowcount or 0)

    algo_trades_res = await db.execute(delete(AlgoTrade).where(AlgoTrade.user_id == user_id))
    summary["algo_trades"] = int(algo_trades_res.rowcount or 0)

    if strategy_ids:
        algo_logs_res = await db.execute(
            delete(AlgoLog).where(AlgoLog.strategy_id.in_(strategy_ids))
        )
        summary["algo_logs"] = int(algo_logs_res.rowcount or 0)

    algo_strat_res = await db.execute(
        delete(AlgoStrategy).where(AlgoStrategy.user_id == user_id)
    )
    summary["algo_strategies"] = int(algo_strat_res.rowcount or 0)

    futures_orders_res = await db.execute(
        delete(FuturesOrder).where(FuturesOrder.user_id == user_id)
    )
    summary["futures_orders"] = int(futures_orders_res.rowcount or 0)

    futures_pos_res = await db.execute(
        delete(FuturesPosition).where(FuturesPosition.user_id == user_id)
    )
    summary["futures_positions"] = int(futures_pos_res.rowcount or 0)

    zeroloss_sig_res = await db.execute(
        delete(ZeroLossSignal).where(ZeroLossSignal.user_id == user_id)
    )
    summary["zeroloss_signals"] = int(zeroloss_sig_res.rowcount or 0)

    zeroloss_perf_res = await db.execute(
        delete(ZeroLossPerformance).where(ZeroLossPerformance.user_id == user_id)
    )
    summary["zeroloss_performance"] = int(zeroloss_perf_res.rowcount or 0)

    zeroloss_runtime_res = await db.execute(
        delete(ZeroLossRuntimeState).where(ZeroLossRuntimeState.user_id == str(user_id))
    )
    summary["zeroloss_runtime_state"] = int(zeroloss_runtime_res.rowcount or 0)

    broker_res = await db.execute(
        delete(BrokerAccount).where(BrokerAccount.user_id == user_id)
    )
    summary["broker_accounts"] = int(broker_res.rowcount or 0)

    watchlist_res = await db.execute(delete(Watchlist).where(Watchlist.user_id == user_id))
    summary["watchlists"] = int(watchlist_res.rowcount or 0)

    portfolio_res = await db.execute(delete(Portfolio).where(Portfolio.user_id == user_id))
    summary["portfolios"] = int(portfolio_res.rowcount or 0)

    user_sessions_res = await db.execute(
        delete(UserSession).where(UserSession.user_id == user_id)
    )
    summary["user_sessions"] = int(user_sessions_res.rowcount or 0)

    admin_sessions_res = await db.execute(
        delete(AdminSession).where(AdminSession.user_id == user_id)
    )
    summary["admin_sessions"] = int(admin_sessions_res.rowcount or 0)

    totp_res = await db.execute(delete(TwoFactorAuth).where(TwoFactorAuth.user_id == user_id))
    summary["totp_secrets"] = int(totp_res.rowcount or 0)

    email_log_res = await db.execute(
        delete(EmailNotificationLog).where(EmailNotificationLog.user_id == user_id)
    )
    summary["email_logs"] = int(email_log_res.rowcount or 0)

    user_res = await db.execute(delete(User).where(User.id == user_id))
    summary["users"] = int(user_res.rowcount or 0)

    try:
        await admin_group_service.remove_user_from_group(str(user_id))
    except Exception:
        logger.exception("Failed to remove deleted user from group assignment: user_id=%s", user_id)

    return summary


def try_delete_firebase_account(firebase_uid: str | None) -> dict[str, Any]:
    """Best-effort Firebase Auth account deletion."""
    if not firebase_uid:
        return {"attempted": False, "deleted": False, "error": None}

    try:
        firebase_auth.delete_user(firebase_uid)
        return {"attempted": True, "deleted": True, "error": None}
    except Exception as exc:
        logger.warning("Failed to delete Firebase account uid=%s: %s", firebase_uid, exc)
        return {"attempted": True, "deleted": False, "error": str(exc)}

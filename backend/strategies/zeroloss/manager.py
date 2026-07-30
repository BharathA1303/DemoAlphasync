"""Per-user ZeroLoss controller manager.

Runs one ZeroLossController task per user so strategy state, positions,
and stats remain isolated across users.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from strategies.zeroloss.controller import ZeroLossController
from strategies.zeroloss.models import ZeroLossRuntimeState
from database.connection import async_session_factory
from engines.market_session import market_session

logger = logging.getLogger(__name__)


class ZeroLossManager:
    def __init__(self):
        self._controllers: dict[str, ZeroLossController] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _normalize_user_id(user_id: Optional[object]) -> str:
        if user_id is None:
            raise ValueError("user_id is required")
        return str(user_id)

    def get_controller(self, user_id: object) -> ZeroLossController:
        uid = self._normalize_user_id(user_id)
        controller = self._controllers.get(uid)
        if controller is None:
            controller = ZeroLossController()
            controller.set_user(user_id)
            self._controllers[uid] = controller
        else:
            controller.set_user(user_id)
        return controller

    async def _set_persistent_enabled(self, user_id: object, enabled: bool) -> None:
        uid = self._normalize_user_id(user_id)
        try:
            async with async_session_factory() as session:
                state = await session.get(ZeroLossRuntimeState, uid)
                if state is None:
                    state = ZeroLossRuntimeState(user_id=uid)
                    session.add(state)

                state.enabled = bool(enabled)
                state.updated_at = datetime.now(timezone.utc)
                await session.commit()
        except Exception:
            logger.exception(
                "Failed persisting ZeroLoss state for user %s (enabled=%s)",
                uid,
                enabled,
            )

    async def _get_persistent_enabled(self, user_id: object) -> bool:
        uid = self._normalize_user_id(user_id)
        try:
            async with async_session_factory() as session:
                state = await session.get(ZeroLossRuntimeState, uid)
                return bool(state and state.enabled)
        except Exception:
            logger.exception("Failed reading ZeroLoss persisted state for user %s", uid)
            return False

    async def _get_all_persisted_enabled_user_ids(self) -> list[str]:
        try:
            async with async_session_factory() as session:
                rows = await session.scalars(
                    select(ZeroLossRuntimeState.user_id).where(
                        ZeroLossRuntimeState.enabled.is_(True)
                    )
                )
                return [str(uid) for uid in rows.all() if uid]
        except Exception:
            logger.exception("Failed loading persisted ZeroLoss enabled users")
            return []

    async def ensure_user_runtime(self, user_id: object) -> ZeroLossController:
        """Ensure in-memory controller/task reflects persisted enabled state."""
        uid = self._normalize_user_id(user_id)
        controller = self.get_controller(user_id)
        persisted_enabled = await self._get_persistent_enabled(uid)

        if not persisted_enabled:
            return controller

        # Never auto-restore strategy runtimes outside live NSE open session.
        # This also heals stale persisted flags from prior days/restarts.
        if not market_session.is_live_trading_session():
            await self._set_persistent_enabled(uid, False)
            if controller.is_enabled():
                controller.disable()

            task = self._tasks.pop(uid, None)
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.exception(
                        "ZeroLoss worker task failed while cancelling closed-session restore for user %s",
                        uid,
                    )
            return controller

        async with self._lock:
            controller = self.get_controller(user_id)
            if not controller.is_enabled():
                controller.enable(user_id=user_id)

            task = self._tasks.get(uid)
            if task is None or task.done():
                self._tasks[uid] = asyncio.create_task(
                    controller.run(), name=f"zeroloss:{uid}"
                )
                logger.info(
                    "ZeroLoss worker auto-restored for user %s from persisted state",
                    uid[:8],
                )

            return controller

    async def is_user_enabled(self, user_id: object) -> bool:
        uid = self._normalize_user_id(user_id)
        controller = self._controllers.get(uid)
        if controller and controller.is_enabled():
            return True
        return await self._get_persistent_enabled(uid)

    async def restore_enabled_users(self) -> int:
        """Restore workers for users who had strategy enabled before restart."""
        restored = 0
        for uid in await self._get_all_persisted_enabled_user_ids():
            try:
                await self.ensure_user_runtime(uid)
                restored += 1
            except Exception:
                logger.exception("Failed restoring ZeroLoss for user %s", uid)
        if restored:
            logger.info(
                "ZeroLoss restored %d enabled users from persisted state", restored
            )
        return restored

    async def enable(self, user_id: object) -> ZeroLossController:
        uid = self._normalize_user_id(user_id)
        async with self._lock:
            controller = self.get_controller(user_id)
            controller.enable(user_id=user_id)
            await self._set_persistent_enabled(uid, True)

            task = self._tasks.get(uid)
            if task is None or task.done():
                self._tasks[uid] = asyncio.create_task(
                    controller.run(), name=f"zeroloss:{uid}"
                )
                logger.info(f"ZeroLoss worker started for user {uid[:8]}...")
            return controller

    async def disable(
        self, user_id: object, close_positions: bool = True
    ) -> list[dict]:
        uid = self._normalize_user_id(user_id)
        async with self._lock:
            controller = self._controllers.get(uid)
            if controller is None:
                await self._set_persistent_enabled(uid, False)
                return []

            closed: list[dict] = []
            if close_positions:
                closed = await controller.close_all_positions()
                try:
                    from database.connection import async_session_factory
                    from services.trading_engine import close_zeroloss_holdings

                    async with async_session_factory() as session:
                        orphan_closed = await close_zeroloss_holdings(session, uid)
                        await session.commit()
                    for item in orphan_closed:
                        if item.get("success"):
                            closed.append(
                                {
                                    "symbol": item.get("symbol"),
                                    "pnl": None,
                                    "status": "PORTFOLIO_CLOSED",
                                }
                            )
                        elif item.get("error"):
                            closed.append(
                                {
                                    "symbol": item.get("symbol"),
                                    "error": item.get("error"),
                                }
                            )
                except Exception:
                    logger.exception(
                        "ZeroLoss orphan holding close failed for user %s", uid
                    )
            controller.disable()
            await controller.stop()

            task = self._tasks.pop(uid, None)
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.exception(
                        "ZeroLoss worker task failed while stopping user %s", uid
                    )

            logger.info(f"ZeroLoss worker stopped for user {uid[:8]}...")
            await self._set_persistent_enabled(uid, False)
            return closed

    async def stop_all(self) -> None:
        user_ids = list(self._controllers.keys())
        for uid in user_ids:
            try:
                await self.disable(uid, close_positions=False)
            except Exception:
                logger.exception("Failed to stop ZeroLoss worker for user %s", uid)

    def get_stats(self) -> dict:
        enabled_users = [
            uid
            for uid, controller in self._controllers.items()
            if controller.is_enabled()
        ]
        running_tasks = [uid for uid, task in self._tasks.items() if not task.done()]
        return {
            "enabled_users": len(enabled_users),
            "running_workers": len(running_tasks),
            "users": [uid[:8] for uid in enabled_users],
        }


zeroloss_manager = ZeroLossManager()

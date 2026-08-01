import logging
from collections.abc import Callable
from typing import Any

from app.kernel.primitives.command import Command

logger = logging.getLogger(__name__)

CommandHandler = Callable[[Any], Any]


class CommandBus:
    """In-Process CQS Command Bus Dispatcher. Enforces single-handler point-to-point routing."""

    def __init__(self) -> None:
        self._handlers: dict[type[Command], CommandHandler] = {}

    def register(self, command_type: type[Command], handler: CommandHandler) -> None:
        if command_type in self._handlers:
            raise ValueError(f"Command {command_type.__name__} already has a registered handler")
        self._handlers[command_type] = handler
        logger.info(f"Registered handler for Command: {command_type.__name__}")

    async def dispatch(self, command: Command) -> Any:
        command_type = type(command)
        handler = self._handlers.get(command_type)
        if not handler:
            raise KeyError(f"No handler registered for Command: {command_type.__name__}")

        logger.debug(
            f"Dispatching Command {command_type.__name__} "
            f"[cmd_id={command.command_id}, corr_id={command.correlation_id}]"
        )
        return await handler(command)

# tick_queue.py - In-memory priority queue for chronologically sorted ticks
import asyncio
import heapq
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

class TickQueue:
    """
    An in-memory priority queue for market ticks.
    Ticks are stored and sorted chronologically based on their timestamp.
    Ensures thread-safe and async-safe access for the 3-tier replay pipeline.
    """

    def __init__(self):
        # List of tuples: (timestamp_float, index, tick_dict)
        # index is used as a tie-breaker to preserve insertion order for identical timestamps
        self._queue: List[Tuple[float, int, Dict[str, Any]]] = []
        self._index = 0
        self._lock = asyncio.Lock()

    async def push_batch(self, ticks: List[Dict[str, Any]]) -> None:
        """
        Push a batch of ticks into the queue.
        Each tick must be a dictionary containing a 'timestamp' (datetime or ISO string).
        """
        async with self._lock:
            for tick in ticks:
                ts = tick.get("timestamp")
                if isinstance(ts, str):
                    try:
                        ts_val = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                    except ValueError:
                        ts_val = datetime.now().timestamp()
                elif isinstance(ts, datetime):
                    ts_val = ts.timestamp()
                else:
                    ts_val = float(ts or datetime.now().timestamp())

                heapq.heappush(self._queue, (ts_val, self._index, tick))
                self._index += 1

    async def pop(self) -> Optional[Dict[str, Any]]:
        """
        Pop the oldest tick from the queue.
        Returns None if the queue is empty.
        """
        async with self._lock:
            if not self._queue:
                return None
            _, _, tick = heapq.heappop(self._queue)
            return tick

    async def peek(self) -> Optional[Dict[str, Any]]:
        """
        Look at the oldest tick without removing it.
        """
        async with self._lock:
            if not self._queue:
                return None
            return self._queue[0][2]

    async def clear(self) -> None:
        """
        Empty the queue and reset the index.
        """
        async with self._lock:
            self._queue.clear()
            self._index = 0

    async def size(self) -> int:
        """
        Get the current size of the queue.
        """
        async with self._lock:
            return len(self._queue)

tick_queue = TickQueue()

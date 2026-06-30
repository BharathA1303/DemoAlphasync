from threading import Lock


class _AdminRuntimeFlags:
    def __init__(self) -> None:
        self._lock = Lock()
        self._auto_approval_enabled = False

    def is_auto_approval_enabled(self) -> bool:
        with self._lock:
            return self._auto_approval_enabled

    def set_auto_approval_enabled(self, enabled: bool) -> bool:
        normalized = bool(enabled)
        with self._lock:
            self._auto_approval_enabled = normalized
            return self._auto_approval_enabled


admin_runtime_flags = _AdminRuntimeFlags()

import threading
import time
from concurrent.futures import CancelledError, ThreadPoolExecutor
from contextlib import contextmanager


class BusyError(RuntimeError):
    run_id: str | None = None


class ResourceLimiter:
    def __init__(self, capacity=16):
        if type(capacity) is not int or capacity < 1:
            raise ValueError("Resource capacity must be positive")
        self.capacity = capacity
        self.active = 0
        self.peak = 0
        self.providers = {}
        self.condition = threading.Condition()

    @contextmanager
    def acquire(self, provider, limit=4, timeout=30, cancelled=lambda: False):
        deadline = time.monotonic() + timeout
        acquired = False
        with self.condition:
            entry = self.providers.setdefault(provider, {"active": 0, "users": 0})
            entry["users"] += 1
        try:
            with self.condition:
                while True:
                    if cancelled():
                        raise CancelledError()
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise BusyError(f"Resource wait timed out: {provider}")
                    if self.active < self.capacity and entry["active"] < limit:
                        entry["active"] += 1
                        self.active += 1
                        self.peak = max(self.peak, self.active)
                        acquired = True
                        break
                    self.condition.wait(min(remaining, 0.05))
            yield
        finally:
            with self.condition:
                if acquired:
                    entry["active"] -= 1
                    self.active -= 1
                entry["users"] -= 1
                if not entry["users"]:
                    self.providers.pop(provider)
                self.condition.notify_all()


class RunQueue:
    def __init__(self, workers=4, queue_capacity=16):
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="genbi-run")
        self.slots = threading.BoundedSemaphore(workers + queue_capacity)
        self.futures = {}
        self.lock = threading.RLock()

    def submit(self, key, function, *args):
        with self.lock:
            if key in self.futures:
                return self.futures[key]
            if not self.slots.acquire(blocking=False):
                raise BusyError("Run queue is full; retry after an active run completes")
            try:
                future = self.pool.submit(function, *args)
            except BaseException:
                self.slots.release()
                raise
            self.futures[key] = future
            future.add_done_callback(lambda completed: self._release(key))
            return future

    def _release(self, key):
        with self.lock:
            self.futures.pop(key, None)
            self.slots.release()

    def cancel(self, key):
        with self.lock:
            future = self.futures.get(key)
            return bool(future and future.cancel())

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)


tool_resources = ResourceLimiter()
step_resources = ResourceLimiter()
run_queue = RunQueue()

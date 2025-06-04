import asyncio
import time
from typing import Any, Dict


# All time units are in milliseconds
class DeadlineAwareRequestQueue:
    def __init__(self, buffer_ms: int = 0, bucket_ms: int = 1):
        if buffer_ms < 0:
            raise ValueError(f"buffer_ms must be non-negative, got {buffer_ms}")

        self.buffer_ms = buffer_ms
        self.bucket_ms = bucket_ms
        self._queue = asyncio.PriorityQueue()
        self._counter = 0

    def _get_deadline(self, request: Dict[str, Any]) -> float:
        arrival = request["arrival_time"]
        ttft = request["ttft"]
        prefill_time = request["estimated_prefill_time"]
        raw_ddl = arrival + ttft - prefill_time
        return ((raw_ddl + self.bucket_ms - 1) // self.bucket_ms) * self.bucket_ms

    async def put(self, request: Dict[str, Any]):
        deadline = self._get_deadline(request)
        prefill_time = request["estimated_prefill_time"]
        self._counter += 1
        priority = (deadline, prefill_time, self._counter)
        await self._queue.put((priority, request))

    async def get_eligible(self, is_idle: bool) -> Dict[str, Any]:
        while True:
            priority, request = await self._queue.get()
            deadline, prefill_time, _ = priority
            now_ms = int(time.time() * 1000)
            eligible_at = deadline - self.buffer_ms

            if is_idle or eligible_at <= now_ms:
                return request

            # Not yet eligible, put back into queue and wait for next eligible request
            await self._queue.put((priority, request))
            wait_time = max(0, (eligible_at - now_ms)) / 1000.0  # seconds
            try:
                await asyncio.wait_for(self._queue.join(), timeout=wait_time)
            except asyncio.TimeoutError:
                pass  # retry after timeout

    # Optional: expose queue size if needed
    def size(self) -> int:
        return self._queue.qsize()

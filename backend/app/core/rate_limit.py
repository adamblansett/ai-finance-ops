import asyncio
import json
import time
from typing import Any

from redis.asyncio import Redis
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings


class RateLimiter:
    """Fixed-window rate limiter backed by Redis with automatic in-memory fallback."""

    def __init__(self, limit: int = 180, window_seconds: int = 60, redis_url: str = "") -> None:
        self.limit = max(1, limit)
        self.window_seconds = max(1, window_seconds)
        self.redis_url = redis_url.strip()
        self._redis: Redis | None = (
            Redis.from_url(self.redis_url, decode_responses=True, socket_timeout=0.5)
            if self.redis_url.startswith("redis")
            else None
        )
        self._memory_buckets: dict[str, tuple[int, int]] = {}
        self._lock = asyncio.Lock()

    async def check(self, client_key: str) -> tuple[bool, int, int]:
        """Return (allowed, remaining, retry_after_seconds)."""
        now = int(time.time())
        bucket = now // self.window_seconds
        retry_after = max(1, (bucket + 1) * self.window_seconds - now)

        if self._redis is not None:
            key = f"finops:rl:{client_key}:{bucket}"
            try:
                count = int(await self._redis.incr(key))
                if count == 1:
                    await self._redis.expire(key, self.window_seconds + 2)
                remaining = max(0, self.limit - count)
                return count <= self.limit, remaining, retry_after
            except Exception:
                pass

        async with self._lock:
            prev_bucket, prev_count = self._memory_buckets.get(client_key, (bucket, 0))
            new_count = 1 if prev_bucket != bucket else prev_count + 1
            self._memory_buckets[client_key] = (bucket, new_count)
            if len(self._memory_buckets) > 4096:
                stale = [k for k, (b, _) in self._memory_buckets.items() if b < bucket]
                for k in stale:
                    del self._memory_buckets[k]
            remaining = max(0, self.limit - new_count)
            return new_count <= self.limit, remaining, retry_after

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()


class RateLimitMiddleware:
    """Pure ASGI rate-limiting middleware exempting health/docs routes."""

    def __init__(self, app: ASGIApp, settings: Settings, limiter: RateLimiter) -> None:
        self.app = app
        self.settings = settings
        self.limiter = limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.settings.rate_limit_enabled:
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "")
        if path.startswith(f"{self.settings.api_v1_prefix}/health") or path in {
            "/docs",
            "/openapi.json",
            "/redoc",
        }:
            await self.app(scope, receive, send)
            return

        client_key = self._extract_client_key(scope)
        allowed, remaining, retry_after = await self.limiter.check(client_key)

        if not allowed:
            body = json.dumps(
                {
                    "detail": (
                        f"Rate limit exceeded ({self.limiter.limit} requests/"
                        f"{self.limiter.window_seconds}s). Retry in {retry_after}s."
                    )
                }
            ).encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("latin-1")),
                        (b"retry-after", str(retry_after).encode("latin-1")),
                        (b"x-ratelimit-limit", str(self.limiter.limit).encode("latin-1")),
                        (b"x-ratelimit-remaining", b"0"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.append(
                    (b"x-ratelimit-limit", str(self.limiter.limit).encode("latin-1"))
                )
                headers.append((b"x-ratelimit-remaining", str(remaining).encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)

    @staticmethod
    def _extract_client_key(scope: Scope) -> str:
        for key, value in scope.get("headers") or []:
            if key.decode("latin-1").lower() == "x-forwarded-for":
                first_ip = value.decode("latin-1", errors="ignore").split(",")[0].strip()
                if first_ip:
                    return first_ip[:64]
        client: Any = scope.get("client")
        if isinstance(client, tuple | list) and client:
            return str(client[0])[:64]
        return "local-client"

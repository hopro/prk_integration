from redis.asyncio import Redis

from app.config import get_settings

settings = get_settings()

redis: Redis | None = None


async def get_redis() -> Redis:
    if redis is None:
        raise RuntimeError("Redis is not initialized")
    return redis


async def init_redis() -> Redis:
    global redis
    redis = Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        decode_responses=True,
    )
    return redis


async def close_redis():
    global redis
    if redis:
        await redis.aclose()
        redis = None

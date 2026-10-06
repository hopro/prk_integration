import json
from dataclasses import dataclass

from redis.asyncio import Redis

SESSION_TTL = 60 * 60 * 24


@dataclass
class MisSession:
    sess_id: str
    cookies: dict[str, str]
    csrf_token: str | None = None

    async def save(self, redis_con: Redis, user_id: str):
        key = f"mis_session:{user_id}"
        data = {
            "sess_id": self.sess_id,
            "cookies": self.cookies,
            "csrf_token": self.csrf_token,
        }
        await redis_con.set(key, json.dumps(data), ex=SESSION_TTL)


async def get_mis_session(redis_con: Redis, user_id: str) -> MisSession | None:
    key = f"mis_session:{user_id}"
    raw = await redis_con.get(key)
    if raw is None:
        return None
    data = json.loads(raw)
    return MisSession(
        sess_id=data["sess_id"],
        cookies=data.get("cookies", {}),
        csrf_token=data.get("csrf_token"),
    )


async def delete_mis_session(redis_con: Redis, user_id: str):
    key = f"mis_session:{user_id}"
    await redis_con.delete(key)

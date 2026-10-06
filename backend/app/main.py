import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import prk, check, spmo, settings, mis, auth, dictionaries

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # При старте один раз проверяем шлюз и пишем вердикт в лог. Раньше о том,
    # куда именно настроен MIS_GATEWAY_URL, можно было узнать только из
    # трассировки в момент ошибки.
    from app.services import mis_client

    logger.info("МИС-ШЛЮЗ настроен на %s", mis_client.MIS_GATEWAY_URL)
    try:
        probe = await mis_client.probe_gateway()
    except Exception as exc:  # noqa: BLE001 — старт не должен падать из-за шлюза
        logger.warning("МИС-ШЛЮЗ: проверка при старте не удалась: %s", exc)
    else:
        if probe.get("isGateway"):
            logger.info(
                "МИС-ШЛЮЗ готов: адрес=%s пир=%s сервис=%s",
                probe.get("url"), probe.get("peer"), probe.get("service") or "(по маршруту)",
            )
        else:
            logger.error("МИС-ШЛЮЗ НЕ ГОТОВ: %s", probe.get("reason"))

    yield


APP_VERSION = "1.0.0"

logger = logging.getLogger(__name__)

app = FastAPI(
    title="PRK Integration API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(prk.router)
app.include_router(check.router)
app.include_router(spmo.router)
app.include_router(settings.router)
app.include_router(mis.router)
app.include_router(auth.router)
app.include_router(dictionaries.router)

# Логи SQL и HTTP-обмена забивают собой сообщения о сессиях ЕЦП и ошибках.
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


@app.get("/api/health")
async def health():
    """Проверка живости.

    Метка service обязательна: если в MIS_GATEWAY_URL по ошибке попадёт адрес
    самого backend, он отвечает на /health так же, как шлюз, и отличить их
    можно только по этой метке. Именно так выглядел сбой у заказчика:
    404 {"detail":"Not Found"} на /api/v1/auth/login.
    """
    return {"status": "ok", "service": "prk-backend", "version": APP_VERSION}
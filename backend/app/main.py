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
    yield


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
    return {"status": "ok"}
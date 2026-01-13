from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import OLLAMA_API_URL, MODEL_NAME, MAX_TOKENS, MAX_QUEUE_SIZE, IN_DOCKER
from app.core.log import log
from app.db.database import engine, dispose_engine
from app.db.models import Base
from app.api.summarize import router as summarize_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("🟢 Backend started")
    log.info(
        f"Settings: IN_DOCKER={IN_DOCKER}\n"
        f"OLLAMA_API_URL={OLLAMA_API_URL}\n"
        f"MODEL_NAME={MODEL_NAME}\n"
        f"MAX_TOKENS={MAX_TOKENS}\n"
        f"MAX_QUEUE_SIZE={MAX_QUEUE_SIZE}"
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        yield
    finally:
        log.info("🔴 Backend stopped")
        await dispose_engine()


app = FastAPI(lifespan=lifespan)
app.include_router(summarize_router)

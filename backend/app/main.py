from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health
from app.config import get_settings
from app.db import connect, init_db


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    conn = connect(get_settings().db_path)
    init_db(conn)
    conn.close()
    yield


app = FastAPI(title="PlantSentinel", lifespan=lifespan)
app.include_router(health.router, prefix="/api")

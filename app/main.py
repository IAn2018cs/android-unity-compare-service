from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import discover_router, router
from app.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings().ensure_directories()
    yield


app = FastAPI(title="Android Unity Compare Service", lifespan=lifespan)
app.include_router(discover_router)
app.include_router(router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

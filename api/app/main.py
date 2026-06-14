import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from fastapi.middleware.cors import CORSMiddleware

from app.shared.database import init_db, get_db_context
from app.modules.applications.router import router as applications_router
from app.modules.agents.router import router as agents_router
from app.modules.profile.router import router as profile_router

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    from app.pipeline.scheduler import start, stop
    start(get_db_context)
    yield
    stop()


app = FastAPI(
    title="AI Career Assistant",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "X-User-Email"],
)

app.include_router(applications_router)
app.include_router(agents_router)
app.include_router(profile_router)


@app.get("/health")
async def health():
    return {"status": "ok"}

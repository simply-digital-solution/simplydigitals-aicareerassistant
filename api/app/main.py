import logging
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from fastapi.middleware.cors import CORSMiddleware

from app.shared.database import init_db, get_db_context
from app.modules.applications.router import router as applications_router
from app.modules.agents.router import router as agents_router
from app.modules.profile.router import router as profile_router
from app.modules.scoring.router import router as scoring_router
from app.modules.stats.router import router as stats_router
from app.modules.admin.router import router as admin_router

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import os
    await init_db()
    if os.getenv("ENABLE_SCHEDULER", "true").lower() == "true":
        from app.pipeline.scheduler import start, stop
        start(get_db_context)
        yield
        stop()
    else:
        yield


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
app.include_router(scoring_router)
app.include_router(stats_router)
app.include_router(admin_router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "Unhandled exception: %s %s → %s: %s\n%s",
        request.method,
        request.url.path,
        type(exc).__name__,
        exc,
        traceback.format_exc(),
    )
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})


@app.get("/health")
async def health():
    return {"status": "ok"}

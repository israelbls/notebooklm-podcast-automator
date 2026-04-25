"""FastAPI application for NotebookLM Automator."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from notebooklm_automator.api.routes import router, get_automator, _automator_instance


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown."""
    yield

    try:
        if _automator_instance:
            _automator_instance.close()
    except Exception:
        pass


app = FastAPI(title="NotebookLM Automator API", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok"}

"""FastAPI-приложение: API генератора + раздача фронтенда."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.routes_generate import router as generate_router
from .api.routes_questions import router as questions_router
from .api.routes_sections import router as sections_router
from .config import get_settings


def create_app() -> FastAPI:
    app = FastAPI(title="AI-генератор квизов", version="1.0.0")

    app.include_router(sections_router)
    app.include_router(generate_router)
    app.include_router(questions_router)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    frontend_dir = get_settings().frontend_dir

    @app.get("/", include_in_schema=False)
    def index():
        """Главная страница конструктора (html.html)."""
        return FileResponse(str(frontend_dir / "html.html"))

    # Статика фронтенда (js.js, ai.js) — в самый конец, чтобы не перехватывать API.
    if frontend_dir.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
    return app


app = create_app()


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()

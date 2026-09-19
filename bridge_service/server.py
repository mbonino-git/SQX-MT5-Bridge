"""SQX-MT5 Bridge Service - FastAPI application entry point."""

from fastapi import FastAPI

from config import settings

app = FastAPI(
    title=settings.app_name,
    description="Bridge service between StrategyQuant X and MetaTrader 5",
)


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": settings.app_name}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host=settings.host, port=settings.port, reload=settings.debug)

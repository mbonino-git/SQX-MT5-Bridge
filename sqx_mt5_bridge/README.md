# SQX-MT5 Bridge Service

Python backend service that handles AI code review, MQL5 compilation, MT5 deployment, and backtest execution.

## Quick Start

```bash
pip install -r requirements.txt
python server.py
```

The server starts on port 8080 by default. Configure via environment variables with the `BRIDGE_` prefix.

## Endpoints

- `GET /health` - Health check

## Configuration

Settings are loaded from environment variables (prefix `BRIDGE_`) or a `.env` file.

| Variable | Default | Description |
|----------|---------|-------------|
| `BRIDGE_HOST` | `0.0.0.0` | Listen host |
| `BRIDGE_PORT` | `8080` | Listen port |
| `BRIDGE_DEBUG` | `false` | Enable auto-reload |
| `BRIDGE_DATABASE_PATH` | `bridge_service.db` | SQLite database path |
| `BRIDGE_METAEDITOR_PATH` | `...metaeditor64.exe` | Path to MQL5 compiler |
| `BRIDGE_TERMINAL_PATH` | `...terminal64.exe` | Path to MT5 terminal |
| `BRIDGE_MAX_COMPILE_RETRIES` | `3` | Max AI fix+compile retries |
| `BRIDGE_MAX_CONCURRENT_BACKTESTS` | `3` | Max parallel backtests |

# SQX-MT5-Bridge Design Spec

**Date:** 2026-09-19
**Status:** Approved
**Author:** Brainstorming session

## 1. Overview

SQX-MT5-Bridge is a two-component system that automates the pipeline from StrategyQuant X strategy generation to MetaTrader 5 backtesting and deployment.

**Components:**
- **SQX Plugin (Java)** - UI inside StrategyQuant X for strategy selection, deployment, configuration, and reporting
- **Bridge Service (Python)** - Backend service handling AI code review, MQL5 compilation, MT5 deployment, backtest execution, and history tracking

## 2. Architecture

```
SQX Plugin (Java) ----HTTP/JSON----> Bridge Service (Python) ----> MT5 Instances
     |                                    |
     |                                    +-- AI Provider Router
     |                                    +-- MQL5 Compiler
     |                                    +-- MT5 Deployer
     |                                    +-- Backtest Runner
     |                                    +-- SQLite DB
```

## 3. SQX Plugin (Java)

### 3.1 Plugin Structure

Install path: `<SQX_install>/user/extend/Plugins/SQXMT5Bridge/`

Files:
- `SQXMT5BridgePlugin.java` - entry point, registers plugin
- `SQXMT5BridgeServlet.java` - handles HTTP commands from UI
- `ui/module.js` - AngularJS frontend

### 3.2 UI Panels

#### Deploy Button (Databank Toolbar)
- Adds "Deploy to MT5" button to databank toolbar
- Opens deploy dialog with strategy selection, target selection, AI provider selection, progress display

#### Config Panel (Settings Tab)
Three tabs:
- **MT5 Targets** - add/edit/remove MT5 instances
- **AI Providers** - add/edit/remove/set-default/test AI providers
- **Deploy Settings** - auto-compile, backup before overwrite

#### History Tab (Results Area)
- Table of past deployments with status, errors fixed, actions (Rollback, Compare)
- Comparison view: side-by-side SQX vs MT5 backtest metrics

### 3.3 First-Run Setup Wizard

Triggered on first install. Three steps:
1. Configure MT5 targets (name, install path, data path, portable flag)
2. Configure AI providers (name, type, base URL, API key, model)
3. Confirm and finish

All configuration via plugin UI. No config files to edit.

### 3.4 MT5 Target Configuration

| Field | Description |
|-------|-------------|
| Name | Friendly name (e.g., "Broker A - Live") |
| Install Path | MT5 installation directory |
| Data Path | MT5 data directory (nullable if portable) |
| Portable Mode | Checkbox - if checked, Data Path ignored; Install Path = Data Path |

Path resolution:
- Portable: `install_path/MQL5/Experts/`
- Normal: `data_path/MQL5/Experts/`

### 3.5 AI Provider Configuration

| Field | Description |
|-------|-------------|
| Name | Friendly name |
| Type | OpenAI-compatible, Claude API, OpenAI |
| Base URL | API endpoint |
| API Key | Authentication key |
| Model | Model identifier |
| Default | Mark one provider as default |

All providers use OpenAI-compatible API format where possible.

### 3.6 Plugin API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/bridge/deploy` | POST | Trigger deployment pipeline |
| `/api/bridge/status/{id}` | GET | Get deployment status |
| `/api/bridge/history` | GET | List past deployments |
| `/api/bridge/rollback/{id}` | POST | Rollback a deployment |
| `/api/bridge/compare/{id}` | GET | Get SQX vs MT5 comparison |
| `/api/bridge/config/mt5` | GET/POST | Manage MT5 targets |
| `/api/bridge/config/providers` | GET/POST | Manage AI providers |

## 4. Python Bridge Service

### 4.1 Deployment Pipeline

```
1. Export from SQX -> get .mq5 file
2. Version Backup -> save copy with timestamp
3. AI Pre-Review -> send code to AI, get fixed code
4. Compile -> metaeditor64.exe /compile, parse errors
5. If errors -> AI Fix Errors -> compile (max 3 retries)
6. Deploy to MT5 -> copy .mq5 to MT5 Experts folder x N targets
7. Run Backtest -> generate .ini, launch terminal64.exe headless
8. Compare Results -> SQX metrics vs MT5 metrics
9. Log & Notify -> save to SQLite, update UI status
```

### 4.2 AI Prompt Strategy

**Pre-review prompt:**
```
You are an MQL5 expert. Review this StrategyQuant X generated
Expert Advisor code. Fix common issues:
- Missing #include directives
- Deprecated function calls
- Incorrect lot sizing calculations
- Missing error handling
- Wrong exit logic
Return only the fixed code, no explanations.
```

**Error-fix prompt:**
```
This MQL5 code has compilation errors. Fix them.
Errors: [metaeditor output]
Code: [current code]
Return only the fixed code.
```

### 4.3 MT5 Backtest Integration

Uses `terminal64.exe /config:backtest.ini` for headless backtesting.

Each backtest:
1. Generate `.ini` file with EA name, symbol, timeframe, date range
2. Launch `terminal64.exe /config:<ini_path>`
3. Wait for completion
4. Parse HTML report from `tester/` directory

Multiple backtests run in parallel across independent MT5 instances. Resource limit: 2-3 concurrent backtests per machine.

### 4.4 Comparison Logic

SQX vs MT5 metrics compared with tolerance rules:
- Delta < 5%: OK (expected minor differences)
- Delta 5-10%: Warning (worth investigating)
- Delta > 10%: Alert (possible code issue)

### 4.5 Rollback Logic

1. Find backup before target deployment
2. Copy backup `.mq5` to MT5 Experts folder
3. Update deployment status to "rolled_back"
4. Optional: recompile in MT5

## 5. SQLite Schema

```sql
CREATE TABLE ai_providers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    base_url TEXT,
    api_key TEXT,
    model TEXT,
    is_default BOOLEAN DEFAULT 0,
    created_at TIMESTAMP
);

CREATE TABLE mt5_targets (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    install_path TEXT NOT NULL,
    data_path TEXT,
    is_portable BOOLEAN DEFAULT 0,
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP
);

CREATE TABLE deployments (
    id INTEGER PRIMARY KEY,
    strategy_name TEXT NOT NULL,
    mt5_target_id INTEGER,
    ai_provider_id INTEGER,
    status TEXT NOT NULL,
    sqx_version TEXT,
    deployed_version TEXT,
    errors_found INTEGER DEFAULT 0,
    errors_fixed INTEGER DEFAULT 0,
    ai_review_log TEXT,
    compilation_log TEXT,
    created_at TIMESTAMP,
    FOREIGN KEY (mt5_target_id) REFERENCES mt5_targets(id),
    FOREIGN KEY (ai_provider_id) REFERENCES ai_providers(id)
);

CREATE TABLE backups (
    id INTEGER PRIMARY KEY,
    deployment_id INTEGER,
    strategy_name TEXT,
    file_path TEXT,
    file_hash TEXT,
    created_at TIMESTAMP,
    FOREIGN KEY (deployment_id) REFERENCES deployments(id)
);

CREATE TABLE comparisons (
    id INTEGER PRIMARY KEY,
    deployment_id INTEGER,
    sqx_metrics TEXT,
    mt5_metrics TEXT,
    deltas TEXT,
    status TEXT,
    report_path TEXT,
    created_at TIMESTAMP,
    FOREIGN KEY (deployment_id) REFERENCES deployments(id)
);
```

## 6. Scope

**MVP includes:**
- SQX plugin with deploy button, config panel, history tab
- First-run setup wizard
- AI code review with two-pass (pre-review + compile fix)
- MT5 target management with portable mode support
- Multiple AI provider support (OpenAI-compatible format)
- Batch deployment across multiple MT5 instances
- Parallel backtests across MT5 instances
- SQX vs MT5 comparison with tolerance rules
- Full rollback with version history
- All configuration via plugin UI (zero file editing)

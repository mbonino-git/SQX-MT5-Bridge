# SQX-MT5-Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\- [ ]\) syntax for tracking.

**Goal:** Build a two-component system (SQX Java plugin + Python bridge service) that automates strategy deployment from StrategyQuant X to MetaTrader 5 with AI code review, backtesting, and comparison.

**Architecture:** SQX Plugin (Java/AngularJS) provides UI inside SQX. Python Bridge Service handles AI review, MQL5 compilation, MT5 deployment, backtest execution, and history. Communication via HTTP/JSON. SQLite for persistence.

**Tech Stack:** Python 3.11+ (FastAPI, SQLite, httpx), Java (SQX plugin API), AngularJS (SQX frontend), metaeditor64.exe (MQL5 compilation), terminal64.exe (MT5 backtesting)

**Spec:** docs/superpowers/specs/2026-09-19-sqx-mt5-bridge-design.md

---

## Task 1: Python Project Scaffolding

**Files:**
- Create: bridge_service/requirements.txt
- Create: bridge_service/config.py
- Create: bridge_service/server.py
- Create: bridge_service/README.md

**Interfaces:**
- Produces: FastAPI app that starts on port 8080

- [x] Step 1: Create bridge_service directory structure
- [x] Step 2: Create requirements.txt with fastapi, uvicorn, httpx, pydantic
- [x] Step 3: Create config.py with settings class
- [x] Step 4: Create server.py with FastAPI app and health endpoint
- [x] Step 5: Test server starts and responds to /health
- [x] Step 6: Commit

---

## Task 2: SQLite Database Layer

**Files:**
- Create: bridge_service/database.py
- Create: bridge_service/tests/test_database.py

**Interfaces:**
- Produces: Database class with init_db(), CRUD for providers, targets, deployments, backups, comparisons

- [ ] Step 1: Write test for database initialization
- [ ] Step 2: Run test to verify it fails
- [ ] Step 3: Implement Database class with SQLite schema creation
- [ ] Step 4: Run test to verify it passes
- [ ] Step 5: Write tests for provider CRUD operations
- [ ] Step 6: Implement provider CRUD methods
- [ ] Step 7: Write tests for target CRUD operations
- [ ] Step 8: Implement target CRUD methods
- [ ] Step 9: Write tests for deployment CRUD operations
- [ ] Step 10: Implement deployment CRUD methods
- [ ] Step 11: Commit

---

## Task 3: Pydantic Models

**Files:**
- Create: bridge_service/models.py
- Create: bridge_service/tests/test_models.py

**Interfaces:**
- Produces: AIProvider, MT5Target, Deployment, Backup, Comparison models

- [ ] Step 1: Write tests for AIProvider model validation
- [ ] Step 2: Implement AIProvider model
- [ ] Step 3: Write tests for MT5Target model with portable mode
- [ ] Step 4: Implement MT5Target model
- [ ] Step 5: Write tests for Deployment model
- [ ] Step 6: Implement Deployment model
- [ ] Step 7: Commit

---

## Task 4: AI Provider Router

**Files:**
- Create: bridge_service/services/ai_reviewer.py
- Create: bridge_service/tests/test_ai_reviewer.py

**Interfaces:**
- Consumes: AIProvider model
- Produces: AIReviewer.review_code(code, prompt) -> str, AIReviewer.fix_errors(code, errors) -> str

- [ ] Step 1: Write test for AI provider initialization
- [ ] Step 2: Implement AIReviewer class with provider config
- [ ] Step 3: Write test for code review prompt construction
- [ ] Step 4: Implement review_code method with OpenAI-compatible API
- [ ] Step 5: Write test for error fix prompt construction
- [ ] Step 6: Implement fix_errors method
- [ ] Step 7: Write test for response parsing (extract code from AI response)
- [ ] Step 8: Implement response parser
- [ ] Step 9: Commit

---

## Task 5: MQL5 Compiler Wrapper

**Files:**
- Create: bridge_service/services/compiler.py
- Create: bridge_service/tests/test_compiler.py

**Interfaces:**
- Produces: Compiler.compile(file_path, include_paths) -> CompileResult

- [ ] Step 1: Write test for compiler initialization with metaeditor path
- [ ] Step 2: Implement Compiler class
- [ ] Step 3: Write test for successful compilation (mock metaeditor output)
- [ ] Step 4: Implement compile method with subprocess call
- [ ] Step 5: Write test for error parsing from metaeditor output
- [ ] Step 6: Implement error parser
- [ ] Step 7: Write test for CompileResult model (success, errors list)
- [ ] Step 8: Commit

---

## Task 6: MT5 Deployer

**Files:**
- Create: bridge_service/services/deployer.py
- Create: bridge_service/tests/test_deployer.py

**Interfaces:**
- Consumes: MT5Target model
- Produces: Deployer.deploy_file(target, source_path, filename) -> str (destination path)

- [ ] Step 1: Write test for path resolution with portable mode
- [ ] Step 2: Implement get_experts_path() with portable flag logic
- [ ] Step 3: Write test for path resolution with normal mode
- [ ] Step 4: Write test for file copy operation
- [ ] Step 5: Implement deploy_file method with shutil.copy
- [ ] Step 6: Write test for backup creation
- [ ] Step 7: Implement create_backup method
- [ ] Step 8: Commit

---

## Task 7: MT5 Backtest Runner

**Files:**
- Create: bridge_service/services/backtest.py
- Create: bridge_service/tests/test_backtest.py

**Interfaces:**
- Consumes: MT5Target model
- Produces: BacktestRunner.run_backtest(target, ea_name, symbol, timeframe, date_from, date_to) -> BacktestResult

- [ ] Step 1: Write test for .ini file generation
- [ ] Step 2: Implement generate_ini method
- [ ] Step 3: Write test for backtest execution (mock terminal64.exe)
- [ ] Step 4: Implement run_backtest method with subprocess
- [ ] Step 5: Write test for timeout handling
- [ ] Step 6: Implement timeout and process management
- [ ] Step 7: Commit

---

## Task 8: HTML Report Parser

**Files:**
- Create: bridge_service/services/reporter.py
- Create: bridge_service/tests/test_reporter.py

**Interfaces:**
- Produces: Reporter.parse_report(html_path) -> BacktestMetrics

- [ ] Step 1: Write test for HTML parsing with sample MT5 report
- [ ] Step 2: Implement parse_report method with BeautifulSoup
- [ ] Step 3: Write test for metric extraction (net profit, drawdown, sharpe, etc.)
- [ ] Step 4: Implement metric extractors
- [ ] Step 5: Write test for BacktestMetrics model
- [ ] Step 6: Commit

---

## Task 9: Comparison Logic

**Files:**
- Create: bridge_service/services/comparison.py
- Create: bridge_service/tests/test_comparison.py

**Interfaces:**
- Consumes: BacktestMetrics (SQX), BacktestMetrics (MT5)
- Produces: ComparisonResult with deltas and status

- [ ] Step 1: Write test for delta calculation
- [ ] Step 2: Implement calculate_deltas method
- [ ] Step 3: Write test for tolerance rules (ok, warning, alert)
- [ ] Step 4: Implement evaluate_tolerance method
- [ ] Step 5: Write test for ComparisonResult generation
- [ ] Step 6: Commit

---

## Task 10: Deployment Pipeline

**Files:**
- Create: bridge_service/services/pipeline.py
- Create: bridge_service/tests/test_pipeline.py

**Interfaces:**
- Consumes: All services from Tasks 4-9
- Produces: Pipeline.execute(strategy_name, mt5_targets, ai_provider, strategy_code) -> DeploymentResult

- [ ] Step 1: Write test for pipeline orchestration (mock all services)
- [ ] Step 2: Implement Pipeline class with step sequencing
- [ ] Step 3: Write test for two-pass AI review (pre-review + compile fix)
- [ ] Step 4: Implement two-pass logic with retry loop
- [ ] Step 5: Write test for parallel deployment across targets
- [ ] Step 6: Implement parallel deployment with concurrent.futures
- [ ] Step 7: Write test for status updates during pipeline
- [ ] Step 8: Implement progress callback
- [ ] Step 9: Commit

---

## Task 11: API Routers

**Files:**
- Create: bridge_service/routers/providers.py
- Create: bridge_service/routers/targets.py
- Create: bridge_service/routers/deploy.py
- Create: bridge_service/routers/history.py
- Create: bridge_service/routers/compare.py

**Interfaces:**
- Consumes: Database, Pipeline, all services
- Produces: FastAPI router endpoints matching spec section 3.6

- [ ] Step 1: Write tests for provider CRUD endpoints
- [ ] Step 2: Implement providers router (GET/POST providers)
- [ ] Step 3: Write tests for target CRUD endpoints
- [ ] Step 4: Implement targets router (GET/POST targets)
- [ ] Step 5: Write tests for deploy endpoint
- [ ] Step 6: Implement deploy router (POST deploy, GET status)
- [ ] Step 7: Write tests for history endpoint
- [ ] Step 8: Implement history router (GET history)
- [ ] Step 9: Write tests for rollback endpoint
- [ ] Step 10: Implement rollback endpoint (POST rollback)
- [ ] Step 11: Write tests for compare endpoint
- [ ] Step 12: Implement compare router (GET comparison)
- [ ] Step 13: Register all routers in server.py
- [ ] Step 14: Commit

---

## Task 12: SQX Plugin - Java Backend

**Files:**
- Create: sqx_plugin/user/extend/Plugins/SQXMT5Bridge/SQXMT5BridgePlugin.java
- Create: sqx_plugin/user/extend/Plugins/SQXMT5Bridge/SQXMT5BridgeServlet.java

**Interfaces:**
- Consumes: Python Bridge Service API
- Produces: SQX plugin that registers UI elements and proxies requests

- [ ] Step 1: Create plugin directory structure
- [ ] Step 2: Implement SQXMT5BridgePlugin.java (ISQPlugin, IServletPlugin)
- [ ] Step 3: Implement SQXMT5BridgeServlet.java with proxy to Python service
- [ ] Step 4: Test plugin loads in SQX Code Editor
- [ ] Step 5: Commit

---

## Task 13: SQX Plugin - Frontend

**Files:**
- Create: sqx_plugin/user/extend/Plugins/SQXMT5Bridge/ui/module.js

**Interfaces:**
- Consumes: SQXMT5BridgeServlet endpoints
- Produces: AngularJS module with deploy dialog, config panel, history tab

- [ ] Step 1: Create AngularJS module with plugin registration
- [ ] Step 2: Implement deploy button in databank toolbar
- [ ] Step 3: Implement deploy dialog (strategy selection, target selection, progress)
- [ ] Step 4: Implement config panel with MT5 targets tab
- [ ] Step 5: Implement config panel with AI providers tab
- [ ] Step 6: Implement first-run setup wizard
- [ ] Step 7: Implement history tab with deployment table
- [ ] Step 8: Implement comparison view (side-by-side metrics)
- [ ] Step 9: Implement rollback button and confirmation
- [ ] Step 10: Commit

---

## Task 14: Integration Testing

**Files:**
- Create: bridge_service/tests/test_integration.py

**Interfaces:**
- Tests full pipeline from API call to deployment

- [ ] Step 1: Write test for full deployment pipeline (mock external services)
- [ ] Step 2: Write test for error handling across pipeline
- [ ] Step 3: Write test for concurrent deployments
- [ ] Step 4: Run all tests and verify pass
- [ ] Step 5: Commit

---

## Task 15: Documentation

**Files:**
- Create: README.md (project root)
- Create: bridge_service/README.md
- Create: sqx_plugin/README.md
- Create: docs/user/setup.md

- [ ] Step 1: Write project README with overview and architecture
- [ ] Step 2: Write bridge service README with API docs
- [ ] Step 3: Write SQX plugin README with installation instructions
- [ ] Step 4: Write user setup guide
- [ ] Step 5: Commit

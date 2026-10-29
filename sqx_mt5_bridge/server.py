"""SQX-MT5 Bridge - FastAPI application entry point.

End points:
  GET  /health                  - health check
  GET  /projects                - list SQX projects (proxied)
  GET  /databanks?project=X     - list databanks for project (proxied)
  GET  /strategies?project=X&databank=Y - list strategies (proxied)
  GET  /backtest-settings       - extract strategy config from SQX
  GET  /stats?project=X&databank=Y&strategyName=Z - SQX stats (proxied)
  GET  /equity?project=X&...    - equity curves (proxied)
  GET  /mt5-symbols/live        - live broker symbol list from MT5
  GET  /mt5-symbols             - cached symbol list (legacy compat)
  POST /compile                 - compile MQ5 source from SQX
  POST /backtest                - submit async backtest (returns jobId)
  GET  /backtest/{jobId}/status - poll backtest status
  GET  /local-jobs              - backtest history
  GET  /settings/json           - bridge config as JSON
  GET  /view-report             - open MT5 HTML report
"""

import asyncio
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Path as FastAPIPath
from fastapi.middleware.cors import CORSMiddleware
import urllib.request
import urllib.parse

from .config import settings
from .services import sqx_client, symbol_service
from .services.backtest import archive_reports, find_report

app = FastAPI(title=settings.app_name, description="Bridge service between StrategyQuant X and MetaTrader 5")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: connect to MT5 once (background thread)
    import threading
    t = threading.Thread(
        target=symbol_service._init_persistent,
        args=(settings.terminal_path,),
        daemon=True,
    )
    t.start()
    yield
    # Shutdown: close persistent MT5 connection
    symbol_service.shutdown_persistent()


app.router.lifespan_context = lifespan

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── SQX Proxy Helper ───────────────────────────────────────────────

_SQX_PORT: int | None = None


# ── MT5 HTML Report Stats Parser (BotPulse pattern) ─────────────────
def parse_mt5_report_stats(html_content: str) -> dict | None:
    """Parse MT5 Strategy Tester Report HTML for key stats.

    Returns a dict with: NetProfit, NumberOfTrades, ProfitFactor,
    PctDrawdown, WinningPct, AvgLoss, MaxConsecWins, MaxConsecLoss.
    """
    if not html_content:
        return None
    stats = {}

    # Total Net Profit
    m = re.search(r'Total Net Profit:</td>\s*<td[^>]*><b>([^<]+)<', html_content, re.IGNORECASE)
    if m:
        val = m.group(1).replace(',', '').replace(' ', '')
        try: stats['NetProfit'] = float(val)
        except ValueError: pass

    # Total Trades
    m = re.search(r'Total Trades:</td>\s*<td[^>]*><b>(\d+)', html_content, re.IGNORECASE)
    if m:
        stats['NumberOfTrades'] = int(m.group(1))

    # Profit Factor
    m = re.search(r'Profit Factor:</td>\s*<td[^>]*><b>(\d+\.?\d*)', html_content, re.IGNORECASE)
    if m:
        stats['ProfitFactor'] = float(m.group(1))

    # Equity Drawdown Relative
    m = re.search(r'Equity Drawdown Relative:</td>\s*<td[^>]*><b>[^<]*?([\d.]+)%', html_content, re.IGNORECASE)
    if m:
        stats['PctDrawdown'] = float(m.group(1))

    # Profit Trades (% of total)
    m = re.search(r'Profit Trades \(% of total\):</td>\s*<td[^>]*><b>[^<]*?([\d.]+)%', html_content, re.IGNORECASE)
    if m:
        stats['WinningPct'] = float(m.group(1))

    # Average loss trade
    m = re.search(r'Average loss trade:</td>\s*<td[^>]*><b>(-?[\d.]+)', html_content, re.IGNORECASE)
    if m:
        try: stats['AvgLoss'] = abs(float(m.group(1)))
        except ValueError: pass

    # Maximum consecutive wins — MT5 format: "3 (317.85)" (count + amount)
    m = re.search(r'Maximum consecutive wins \(\$\):</td>\s*<td[^>]*><b>(\d+)', html_content, re.IGNORECASE)
    if m:
        stats['MaxConsecWins'] = int(m.group(1))

    # Maximum consecutive losses — MT5 format: "4 (-148.35)" (count + amount)
    m = re.search(r'Maximum consecutive losses \(\$\):</td>\s*<td[^>]*><b>(\d+)', html_content, re.IGNORECASE)
    if m:
        stats['MaxConsecLoss'] = int(m.group(1))

    if not stats:
        return None
    return stats


def _get_sqx_port() -> int:
    global _SQX_PORT
    if _SQX_PORT is None:
        import socket
        for port in range(8080, 8100):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.2)
                result = sock.connect_ex((settings.sqx_host, port))
                sock.close()
                if result == 0:
                    _SQX_PORT = port
                    return port
            except Exception:
                pass
        _SQX_PORT = 8080
    return _SQX_PORT


def _proxy_sqx_get(path: str, params: dict | None = None) -> dict | None:
    port = _get_sqx_port()
    base = f"http://{settings.sqx_host}:{port}"
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
            return None
    except Exception as e:
        print(f"[SQX proxy GET] {path}: {e}")
        return None


def _proxy_sqx_post(path: str, data: dict) -> dict | None:
    port = _get_sqx_port()
    url = f"http://{settings.sqx_host}:{port}{path}"
    body = json.dumps(data).encode("utf-8")
    try:
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
            return None
    except Exception as e:
        print(f"[SQX proxy POST] {path}: {e}")
        return None


# ── Job Manager for async backtests ────────────────────────────────

class BacktestJob:
    def __init__(self, job_id: str, project: str, databank: str,
                 strategy_name: str, symbol: str, period: str,
                 from_date: str, to_date: str, tick_model: str,
                 deposit: float, currency: str, leverage: int,
                 terminal_path: str, forward_mode: bool = False,
                 forward_date: str | None = None,
                 expert_relative_path: str | None = None,
                 ex5_path: str | None = None):
        self.job_id = job_id
        self.project = project
        self.databank = databank
        self.strategy_name = strategy_name
        self.symbol = symbol
        self.period = period
        self.from_date = from_date
        self.to_date = to_date
        self.tick_model = tick_model
        self.deposit = deposit
        self.currency = currency
        self.leverage = leverage
        self.terminal_path = terminal_path
        self.forward_mode = forward_mode
        self.forward_date = forward_date
        self.expert_relative_path = expert_relative_path
        self.ex5_path = ex5_path
        self.status = "pending"       # pending | compiling | testing | done | error
        self.result: dict | None = None
        self.error: str | None = None
        self.created_at = time.time()


_jobs: dict[str, BacktestJob] = {}
_jobs_lock = asyncio.Lock()
_jobs_db_lock = threading.Lock()

# ── SQLite for local jobs history ──────────────────────────────────

_DB_PATH = Path(__file__).parent / "bridge_jobs.db"


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            project TEXT,
            databank TEXT,
            strategy_name TEXT,
            symbol TEXT,
            period TEXT,
            from_date TEXT,
            to_date TEXT,
            status TEXT,
            result TEXT,
            error TEXT,
            created_at REAL
        )
    """)
    conn.commit()
    return conn


def _save_job(job: BacktestJob):
    conn = _get_db()
    conn.execute(
        "INSERT OR REPLACE INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (job.job_id, job.project, job.databank, job.strategy_name,
         job.symbol, job.period, job.from_date, job.to_date,
         job.status, json.dumps(job.result or {}), job.error,
         job.created_at),
    )
    conn.commit()
    conn.close()


def _load_jobs() -> list[BacktestJob]:
    conn = _get_db()
    rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
    conn.close()
    jobs = []
    for row in rows:
        job = BacktestJob(
            job_id=row[0], project=row[1], databank=row[2],
            strategy_name=row[3], symbol=row[4], period=row[5],
            from_date=row[6], to_date=row[7],
            tick_model="", deposit=10000, currency="USD",
            leverage=100, terminal_path="",
        )
        job.status = row[8]
        job.result = json.loads(row[9]) if row[9] else None
        job.error = row[10]
        job.created_at = row[11]
        jobs.append(job)
    return jobs


def _save_jobs(jobs: list[BacktestJob]):
    conn = _get_db()
    for job in jobs:
        conn.execute(
            "INSERT OR REPLACE INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (job.job_id, job.project, job.databank, job.strategy_name,
             job.symbol, job.period, job.from_date, job.to_date,
             job.status, json.dumps(job.result or {}), job.error,
             job.created_at),
        )
    conn.commit()
    conn.close()


def _get_jobs(project: str | None = None, databank: str | None = None, limit: int = 50) -> list[dict]:
    conn = _get_db()
    query = "SELECT * FROM jobs WHERE 1=1"
    params = []
    if project:
        query += " AND project = ?"
        params.append(project)
    if databank:
        query += " AND databank = ?"
        params.append(databank)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [
        {
            "id": r[0], "project": r[1], "databank": r[2],
            "strategyName": r[3], "symbol": r[4], "period": r[5],
            "fromDate": r[6], "toDate": r[7], "status": r[8],
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(r[11])),
            "reportKey": r[3] + "_" + r[4] + "_" + r[5],  # used for view-report
        }
        for r in rows
    ]


# ── Timeframe map ──────────────────────────────────────────────────

_TIMEFRAME_MAP = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 60, "H4": 240, "D1": 1440, "W1": 10080, "MN1": 43200,
}


def _resolve_mt5_symbol(symbol: str) -> str:
    """Map a SQX strategy symbol to the symbol this MT5 terminal actually has.

    Resolution order:
      1. Exact case-insensitive match in mapping.
      2. Base-name match (strip SQX suffix after '_') against mapping.
      3. Return base name directly when no mapping (handles names like
         XAUUSD_TickData_FTMO → XAUUSD).
      4. Return unchanged as last resort.
    """
    if not symbol:
        return symbol
    try:
        mapping = settings.symbol_mapping_dict or {}
    except Exception:
        return symbol

    # Exact match (case-insensitive)
    for k, v in mapping.items():
        if k.lower() == symbol.lower():
            return v

    # Base-name match (strip SQX suffix after '_')
    base = symbol.split("_")[0]
    for k, v in mapping.items():
        if k.lower() == base.lower():
            return v

    # When no mapping is configured and the symbol has an SQX suffix,
    # use the base name directly (e.g. XAUUSD_TickData_FTMO → XAUUSD)
    # instead of passing through the full SQX internal name which MT5
    # will not recognise.
    if base and base != symbol:
        return base

    return symbol


def _find_trade_csv(tester_dir: Path, expert_base: str) -> Path | None:
    """Locate the EA's deal-export CSV in the Tester Agent directories.

    MT5 truncates long file names, so the CSV on disk is often a *prefix* of
    the expert name (e.g. "..._M_NN_CD.csv" instead of "..._M_NN_CD_SQX.csv").
    Try the exact name first, then fall back to prefix matching.
    """
    if not tester_dir or not tester_dir.exists():
        return None

    def _agent_files_dir(agent: Path) -> Path | None:
        if not (agent.name.startswith("Agent-") and agent.is_dir()):
            return None
        d = agent / "MQL5" / "Files"
        return d if d.exists() else None

    # 1) Exact match (fast path)
    for agent in tester_dir.iterdir():
        d = _agent_files_dir(agent)
        if d is None:
            continue
        cand = d / f"{expert_base}.csv"
        try:
            if cand.exists():
                return cand
        except OSError:
            pass

    # 2) Prefix match for truncated names, newest first
    matches: list[Path] = []
    for agent in tester_dir.iterdir():
        d = _agent_files_dir(agent)
        if d is None:
            continue
        try:
            for f in d.glob("*.csv"):
                stem = f.stem
                # The truncated name is always a prefix of the full name
                if len(stem) >= 20 and expert_base.startswith(stem):
                    matches.append(f)
        except OSError:
            pass

    if not matches:
        return None
    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0]


# ── Health ──────────────────────────────────────────────────────────


@app.get("/health")
def health_check():
    return {"status": "ok", "service": settings.app_name}


# ── SQX Proxy Endpoints ────────────────────────────────────────────


def _scan_projects_from_disk() -> list[str]:
    """Read custom project names from the SQX data directory.

    Excludes SQX's built-in project types (Builder, Retester, etc.)
    which always appear in the sidebar, not the Custom projects area.
    """
    _SQX_BUILTIN = {
        "Builder", "Retester", "Optimizer",
        "PortfolioMaster", "PortfolioComposer",
    }
    projects_dir = Path(settings.sqx_data_dir) / "projects"
    if not projects_dir.is_dir():
        return []
    return sorted(
        d.name for d in projects_dir.iterdir()
        if d.is_dir() and d.name not in _SQX_BUILTIN
        and (d / "project.cfx").exists()
    )


def _scan_databanks_from_disk(project: str) -> list[dict]:
    """Read databank names and record counts from the SQX data directory."""
    db_dir = Path(settings.sqx_data_dir) / "projects" / project / "databanks"
    if not db_dir.is_dir():
        return []
    result = []
    for d in sorted(db_dir.iterdir()):
        if d.is_dir():
            records = len(list(d.glob("*.sqx")))
            result.append({"name": d.name, "records": records})
    return result


@app.get("/projects")
def list_projects():
    result = _proxy_sqx_get("/projects")
    if result:
        projects = result.get("projects") or result.get("list") or []
        if projects:
            return {"projects": projects}
    # Fallback: scan the filesystem
    return {"projects": _scan_projects_from_disk()}


@app.get("/databanks")
def list_databanks(project: str = Query(..., description="SQX project name")):
    result = _proxy_sqx_get("/databanks", {"projectName": project})
    if result:
        databanks = result.get("databanks") or result.get("list") or []
        if databanks:
            return {"databanks": databanks}
    # Fallback: scan the filesystem
    return {"databanks": _scan_databanks_from_disk(project)}


@app.get("/strategies")
def list_strategies(
    project: str = Query(..., description="SQX project name"),
    databank: str = Query(..., description="SQX databank name"),
):
    # SQX /project/loadGridData returns {totalCount, gridData} where gridData[i][0] is strategy name
    try:
        port = _get_sqx_port()
        base = f"http://{settings.sqx_host}:{port}"
        body = (
            f"projectName={urllib.parse.quote(project)}"
            f"&databankName={urllib.parse.quote(databank)}"
            f"&first1000=true"
            f"&lastChangeTime=0"
            f"&refreshAction=true"
        )
        body_buf = body.encode("utf-8")
        req = urllib.request.Request(
            f"{base}/project/loadGridData",
            data=body_buf,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        grid_data = data.get("gridData") or []
        strategies = [{"name": row[0]} for row in grid_data if len(row) > 0]
        return {
            "strategies": strategies,
            "totalCount": data.get("totalCount", len(strategies)),
        }
    except Exception as e:
        print(f"[STRATEGIES] Error: {e}")

    # Fallback: scan .sqx files from the databank folder
    db_dir = Path(settings.sqx_data_dir) / "projects" / project / "databanks" / databank
    if db_dir.is_dir():
        strategies = [
            {"name": f.stem} for f in sorted(db_dir.glob("*.sqx"))
        ]
        return {"strategies": strategies}


@app.get("/list-portfolios")
def list_portfolios(
    project: str = Query(..., description="SQX project name"),
    databank: str = Query(..., description="SQX databank name"),
):
    """List portfolio .sqx files in a databank."""
    db_dir = Path(settings.sqx_data_dir) / "projects" / project / "databanks" / databank
    if not db_dir.is_dir():
        return {"portfolios": []}
    portfolios = sorted([f.stem for f in db_dir.glob("*.sqx")])
    return {"portfolios": portfolios}


@app.get("/portfolio-strategies")
def get_portfolio_strategies(
    project: str = Query(..., description="SQX project name"),
    databank: str = Query(..., description="SQX databank name (e.g. Portfolios)"),
    portfolio: str = Query(..., description="Portfolio .sqx filename (without .sqx extension)"),
):
    """Parse a portfolio .sqx file and return the list of strategies with their settings.

    Reads the portfolio .sqx from disk, extracts strategy names from the Results/
    directory structure, and for each strategy reads its individual .sqx file
    to get symbol, timeframe, and date range.
    """
    import zipfile

    portfolio_path = Path(settings.sqx_data_dir) / "projects" / project / "databanks" / databank / f"{portfolio}.sqx"
    if not portfolio_path.is_file():
        return {"ok": False, "error": f"Portfolio not found: {portfolio}.sqx"}

    strategies = []
    results_pattern = re.compile(r'^Results/([^:]+):\s+([^\s]+)/dailyEquity\.bin$')

    try:
        with zipfile.ZipFile(portfolio_path) as z:
            ls_content = z.read('lastSettings.xml').decode('utf-8', errors='replace')

            # Portfolio-level settings
            setup_match = re.search(r'<Setup\s+dateFrom="([\d.]+)"\s+dateTo="([\d.]*)"', ls_content)
            capital_match = re.search(r'<InitialCapital>([\d.]+)</InitialCapital>', ls_content)

            # Extract strategy entries from Results/ directory listing
            all_names = z.namelist()
            strategy_dirs = []
            for name in all_names:
                m = results_pattern.match(name)
                if m:
                    strategy_dirs.append(m.group(1))
            # Deduplicate (one dir per strategy)
            strategy_dirs = sorted(set(strategy_dirs))

            for strat_name in strategy_dirs:
                # Search for the strategy .sqx file across ALL projects
                projects_dir = Path(settings.sqx_data_dir) / "projects"
                found_path = None
                for proj_d in projects_dir.iterdir():
                    if not proj_d.is_dir():
                        continue
                    sqx_file = proj_d / "databanks" / "Results" / f"{strat_name}.sqx"
                    if sqx_file.is_file():
                        found_path = sqx_file
                        break
                    # Also check other databanks (e.g. "Simple strategies")
                    for db_d in proj_d.glob("databanks/*"):
                        if db_d.is_dir():
                            cand = db_d / f"{strat_name}.sqx"
                            if cand.is_file():
                                found_path = cand
                                break
                    if found_path:
                        break

                if found_path and found_path.is_file():
                    try:
                        with zipfile.ZipFile(found_path) as sz:
                            if "lastSettings.xml" in sz.namelist():
                                strat_xml = sz.read("lastSettings.xml").decode("utf-8", errors="replace")
                                s_setup = re.search(r'<Setup\s+dateFrom="([\d.]+)"\s+dateTo="([\d.]*)"', strat_xml)
                                s_chart = re.search(r'<Chart\b[^>]*symbol="([^"]*)"[^>]*timeframe="([^"]*)"', strat_xml)
                                if not s_chart:
                                    s_chart = re.search(r'<Chart\b[^>]*timeframe="([^"]*)"[^>]*symbol="([^"]*)"', strat_xml)
                                s_capital = re.search(r'<InitialCapital>([\d.]+)</InitialCapital>', strat_xml)

                                raw_symbol = s_chart.group(1) if s_chart else None
                                resolved_symbol = _resolve_mt5_symbol(raw_symbol) if raw_symbol else None
                                timeframe = s_chart.group(2) if s_chart else None

                                strategies.append({
                                    "name": strat_name,
                                    "symbol": resolved_symbol,
                                    "raw_symbol": raw_symbol,
                                    "timeframe": timeframe,
                                    "from_date": s_setup.group(1) if s_setup else None,
                                    "to_date": s_setup.group(2) if s_setup else None,
                                    "initial_capital": float(s_capital.group(1)) if s_capital else None,
                                })
                    except Exception as e:
                        strategies.append({
                            "name": strat_name,
                            "error": f"Could not read settings: {e}",
                        })
                else:
                    strategies.append({
                        "name": strat_name,
                        "error": "Strategy .sqx file not found in any project",
                    })

    except Exception as e:
        return {"ok": False, "error": f"Failed to parse portfolio: {e}"}

    return {
        "ok": True,
        "portfolio": portfolio,
        "fromDate": setup_match.group(1) if setup_match else None,
        "toDate": setup_match.group(2) if setup_match else None,
        "initialCapital": float(capital_match.group(1)) if capital_match else 10000.0,
        "strategies": strategies,
        "strategyCount": len(strategies),
    }


# ── Portfolio Backtest Job Tracking ─────────────────────────────────

_portfolio_backtest_jobs: dict[str, dict] = {}


@app.post("/portfolio/backtest")
async def submit_portfolio_backtest(body: dict[str, Any]):
    """Submit batch backtests for all strategies in a portfolio.

    Request body:
        {
            "project": "...", "databank": "Portfolios", "portfolio": "Portfolio",
            "symbol": "...", "period": "M30",
            "fromDate": "2022-01-01", "toDate": "2026-10-16",
            "deposit": 10000, "currency": "USD", "leverage": 100,
            "tickModel": "every_tick_real"
        }

    Returns: { "portfolioKey": "...", "jobs": [{ "index": 0, "jobId": "...", "strategy": "..." }] }
    """
    project = body.get("project", "")
    databank = body.get("databank", "")
    portfolio = body.get("portfolio", "")
    symbol_override = body.get("symbol")
    period = body.get("period", "M30")
    from_date = body.get("fromDate", "2022-01-01")
    to_date = body.get("toDate", "2026-10-16")
    deposit = body.get("deposit", 10000)
    currency = body.get("currency", "USD")
    leverage = body.get("leverage", 100)
    tick_model = body.get("tickModel", "every_tick_real")

    portfolio_key = f"{project}__{databank}__{portfolio}"

    # Parse portfolio strategies
    strategies_resp = get_portfolio_strategies(project=project, databank=databank, portfolio=portfolio)
    if not strategies_resp.get("ok"):
        return {"ok": False, "error": strategies_resp.get("error", "Failed to parse portfolio")}

    strategy_list = strategies_resp["strategies"]
    job_list = []
    skipped = 0

    for idx, strat in enumerate(strategy_list):
        if "error" in strat or not strat.get("symbol"):
            skipped += 1
            continue

        # Submit backtest
        backtest_body = {
            "project": project,
            "databank": "Results",
            "strategyName": strat["name"],
            "symbol": strat["symbol"],
            "period": strat.get("timeframe") or period,
            "fromDate": strat.get("from_date") and strat["from_date"].replace(".", "-") or from_date,
            "toDate": strat.get("to_date") and strat["to_date"].replace(".", "-") or to_date,
            "deposit": strat.get("initial_capital") or deposit,
            "currency": currency,
            "leverage": leverage,
            "tickModel": tick_model,
        }

        resp = await submit_backtest(backtest_body)
        if "jobId" in resp:
            job_list.append({
                "index": idx,
                "jobId": resp["jobId"],
                "strategy": strat["name"],
                "status": "pending",
            })
        else:
            skipped += 1
            job_list.append({
                "index": idx,
                "jobId": None,
                "strategy": strat["name"],
                "status": "failed",
                "error": resp.get("error", "Unknown error"),
            })

    _portfolio_backtest_jobs[portfolio_key] = {
        "project": project,
        "databank": databank,
        "portfolio": portfolio,
        "strategies": strategy_list,
        "jobs": job_list,
        "total": len(strategy_list),
        "completed": 0,
        "deposit": deposit,
        "started_at": time.time(),
    }

    return {
        "ok": True,
        "portfolioKey": portfolio_key,
        "jobs": job_list,
        "total": len(job_list),
        "skipped": skipped,
    }


@app.get("/portfolio-status")
def get_portfolio_status(portfolio_key: str = Query(...)):
    """Get the status of a portfolio backtest job.

    Returns: { "ok": true, "portfolioKey": "...", "jobs": [...], "total": N, "completed": N, "progress": 0.0 }
    """
    job_info = _portfolio_backtest_jobs.get(portfolio_key)
    if not job_info:
        return {"ok": False, "error": "Portfolio backtest not found"}

    # Update completed count from DB
    conn = _get_db()
    rows = conn.execute(
        "SELECT status FROM jobs WHERE id IN (" + ",".join(["?"] * len(job_info["jobs"])) + ")",
        [j["jobId"] for j in job_info["jobs"] if j.get("jobId")],
    ).fetchall()
    conn.close()

    completed = sum(1 for r in rows if r[0] in ("done", "error"))
    job_info["completed"] = completed

    for j in job_info["jobs"]:
        j["project"] = job_info.get("project", "")
        j["databank"] = "Results"
        j["deposit"] = job_info.get("deposit", 10000)
        if j.get("jobId"):
            status_row = conn.execute(
                "SELECT status, result, error FROM jobs WHERE id = ?", (j["jobId"],)
            ).fetchone()
            if status_row:
                j["status"] = status_row[0]
                if status_row[1]:
                    try:
                        j["result"] = json.loads(status_row[1])
                    except Exception:
                        pass
    # Re-close since we already closed above
    _portfolio_backtest_jobs[portfolio_key] = job_info

    return {
        "ok": True,
        "portfolioKey": portfolio_key,
        "jobs": job_info["jobs"],
        "total": job_info["total"],
        "completed": completed,
        "progress": round(completed / max(job_info["total"], 1), 2),
    }


@app.get("/stats")
def get_stats(
    project: str = Query(...),
    databank: str = Query(...),
    strategy_name: str = Query(...),
):
    """Proxy to SQX resultsPlugins/stats with required parameters.

    SQX's stats API requires resultKey, direction, sampleType, plType parameters.
    BotPulse uses: resultKey="Portfolio", direction="0", sampleType="127", plType="10".
    """
    params = urllib.parse.urlencode({
        "projectName": project,
        "databankName": databank,
        "strategyName": strategy_name,
        "resultKey": "Portfolio",
        "direction": "0",
        "sampleType": "127",
        "plType": "10",
    })
    port = _get_sqx_port()
    url = f"http://{settings.sqx_host}:{port}/resultsPlugins/stats"
    try:
        req = urllib.request.Request(
            url,
            data=params.encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status == 200:
                result = json.loads(resp.read().decode("utf-8"))
                # SQX returns { stats: {...}, success: "ok" } or { error: "..." }
                if result.get("success") == "ok" and "stats" in result:
                    return {"stats": result["stats"]}
                print(f"[SQX] /stats returned: {result.get('error', 'no stats')}")
                return {"stats": {}}
            return None
    except Exception as e:
        print(f"[SQX proxy GET] /stats: {e}")
        return None


@app.get("/equity")
def get_equity(
    project: str = Query(...),
    databank: str = Query(...),
    strategy_name: str = Query(...),
    deposit: str = Query("10000"),
):
    """Return equity curves for both SQX and MT5.

    SQX equity: fetched from resultsPlugins/orders via SQX REST API
    MT5 equity: parsed from the backtest deal-export CSV (BotPulse pattern)
    """
    deposit_val = float(deposit)
    safe_name = re.sub(r'\s+', '_', strategy_name).replace("\\", "_").replace("/", "_").strip()

    mt5_equity = None
    sqx_equity = None

    # ── MT5 Equity: parse deal-export CSV ─────────────────────────
    # MT5 CSV is UTF-16 LE with BOM. Format (BotPulse pattern):
    #   Col 8 = entry type (in/out), Col 12 = profit
    #   Equity = deposit + cumulative profit on "out" entries
    mt5_data_dir = _find_mt5_data_dir(settings.terminal_path)
    csv_path = None

    # Search in Tester Agent directories (handles truncated long names)
    tester_dir = mt5_data_dir / "Tester" if mt5_data_dir else None
    csv_path = _find_trade_csv(tester_dir, safe_name)

    # Fallback: check Reports folder (preserved CSV from completed backtests)
    if not csv_path:
        reports_dir = mt5_data_dir / "Reports" if mt5_data_dir else None
        if reports_dir and reports_dir.exists():
            for f in reports_dir.iterdir():
                if f.suffix.lower() == '.csv' and safe_name.lower() in f.name.lower():
                    csv_path = f
                    break

    if csv_path and csv_path.exists():
        try:
            buf = csv_path.read_bytes()
            is_utf16 = buf[:2] == b'\xff\xfe'
            txt = buf[2:].decode('utf-16-le') if is_utf16 else buf.decode('utf-8')

            curve = []
            equity = deposit_val
            in_deals = False

            for line in txt.split('\n'):
                if '- List of deals' in line:
                    in_deals = True
                    continue
                if line.startswith('-') and in_deals:
                    # Next section started
                    break
                if not in_deals or not line.strip():
                    continue

                parts = line.split(';')
                if len(parts) < 14 or not parts[2]:
                    # Skip balance row / empty symbol
                    continue

                profit = float(parts[12]) if parts[12] else 0
                equity += profit

                # Record equity at each "out" (close) deal
                if parts[8] == 'out':
                    curve.append({"index": len(curve), "equity": round(equity, 2)})

            if curve:
                # "points" is what the plugin's chart code reads: [[x, y], ...]
                mt5_equity = {
                    "curve": curve,
                    "points": [[p["index"], p["equity"]] for p in curve],
                }
        except Exception as e:
            print(f"[EQUITY] Error parsing MT5 CSV: {e}")

    # ── SQX Equity: fetch from resultsPlugins/orders ──────────────
    # SQX returns per-trade data with Balance column. We reconstruct the
    # equity curve as deposit + cumulative ProfitLoss over closed deals.
    try:
        sqx_port = _get_sqx_port()
        base = f"http://{settings.sqx_host}:{sqx_port}"
        body = (
            f"projectName={urllib.parse.quote(project)}"
            f"&databankName={urllib.parse.quote(databank)}"
            f"&strategyName={urllib.parse.quote(strategy_name)}"
        )
        body_buf = body.encode('utf-8')
        req = urllib.request.Request(
            f"{base}/resultsPlugins/orders",
            data=body_buf,
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            orders_data = json.loads(resp.read().decode())

        orders = orders_data.get('orders', [])
        sorted_orders = sorted(orders, key=lambda o: o.get('CloseTime', 0) or 0)

        sqx_curve = [[0, deposit_val]]
        bal = deposit_val
        for o in sorted_orders:
            # Skip deposit/withdrawal/balance pseudo-rows
            if o.get('Type') in (9, 10, 11):
                continue
            # Prefer SQX Balance column; fall back to cumulative PL
            bal_val = o.get('Balance')
            if bal_val is not None:
                bal = float(bal_val)
            else:
                pl = float(o.get('ProfitLoss', 0) or 0)
                bal += pl
            sqx_curve.append([len(sqx_curve), round(bal, 2)])

        sqx_equity = {"curve": sqx_curve, "points": sqx_curve}
    except Exception as e:
        print(f"[EQUITY] SQX orders fetch failed: {e}")

    if sqx_equity is None and mt5_equity is None:
        return {
            "deposit": deposit,
            "sqx": None,
            "mt5": None,
            "error": "No equity data available. Run a backtest first to generate MT5 CSV data.",
        }

    return {
        "deposit": deposit,
        "sqx": sqx_equity,
        "mt5": mt5_equity,
    }


# ── Settings ────────────────────────────────────────────────────────

_SETTINGS_FILE = Path(__file__).resolve().parent.parent / "bridge_settings.json"


def _load_persisted_settings() -> None:
    """Merge persisted overrides from bridge_settings.json into settings."""
    if _SETTINGS_FILE.exists():
        try:
            data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
            for key, attr in [
                ("terminalPath", "terminal_path"),
                ("sqxDataDir", "sqx_data_dir"),
                ("symbolMapping", "symbol_mapping"),
            ]:
                if key in data and data[key]:
                    setattr(settings, attr, data[key])
        except Exception:
            pass


# Load persisted overrides at startup
_load_persisted_settings()


@app.get("/settings/json")
def get_settings_json():
    return {
        "terminalPath": settings.terminal_path,
        "sqxDataDir": settings.sqx_data_dir,
        "sqxHost": settings.sqx_host,
        "sqxPort": _get_sqx_port(),
        "symbolMapping": settings.symbol_mapping,
    }


@app.post("/settings/json")
async def update_settings_json(payload: dict[str, Any]):
    """Persist bridge settings overrides and apply them immediately."""
    overrides: dict[str, str] = {}
    for key, attr in [
        ("terminalPath", "terminal_path"),
        ("sqxDataDir", "sqx_data_dir"),
        ("symbolMapping", "symbol_mapping"),
    ]:
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            setattr(settings, attr, val.strip())
            overrides[key] = val.strip()

    # Merge with existing persisted file so partial updates don't lose other keys
    existing: dict[str, str] = {}
    if _SETTINGS_FILE.exists():
        try:
            existing = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    existing.update(overrides)
    _SETTINGS_FILE.write_text(
        json.dumps(existing, indent=2), encoding="utf-8"
    )

    return {"ok": True, "saved": list(overrides.keys())}


# ── Symbol Sync ─────────────────────────────────────────────────────


@app.get("/mt5-symbols/live")
def mt5_symbols_live():
    result = symbol_service.query_live_symbols(terminal_path=settings.terminal_path)
    if result.get("ok"):
        return {
            "ok": True, "symbols": result.get("symbols", []),
            "count": result.get("count", 0), "server": result.get("server"),
        }
    mapping = settings.symbol_mapping_dict
    symbols = list(mapping.keys())
    for mt5_name in mapping.values():
        if mt5_name not in symbols:
            symbols.append(mt5_name)
    return {
        "ok": False, "error": result.get("error", "MT5 unavailable"),
        "symbols": symbols, "count": len(symbols), "fallback": True,
    }


@app.get("/mt5-symbols")
def mt5_symbols_legacy():
    """Legacy alias for /mt5-symbols/live (old plugin compatibility)."""
    return mt5_symbols_live()


# ── Backtest Settings Extraction ────────────────────────────────────


def _read_sqx_last_settings(project: str, databank: str, strategy_name: str) -> str | None:
    """Read lastSettings.xml from a .sqx strategy file on disk.

    Strategy names in SQX may contain spaces (e.g. "P0005-XAUUSD-H1- EOD-XU...").
    We match by normalizing whitespace: compare strategy_name with spaces removed
    against the filename stem with spaces removed.
    """
    import zipfile
    sqx_dir = Path(settings.sqx_data_dir) / "projects" / project / "databanks" / databank
    if not sqx_dir.is_dir():
        return None
    name_norm = strategy_name.replace(" ", "").replace(" ", "")
    candidates = list(sqx_dir.glob("*.sqx"))
    for f in candidates:
        stem_norm = f.stem.replace(" ", "").replace(" ", "")
        if stem_norm == name_norm or stem_norm.startswith(name_norm):
            try:
                with zipfile.ZipFile(f) as z:
                    if "lastSettings.xml" in z.namelist():
                        return z.read("lastSettings.xml").decode("utf-8", errors="replace")
            except Exception:
                pass
    return None


@app.get("/backtest-settings")
def get_backtest_settings(
    project: str = Query(...),
    databank: str = Query(...),
    strategy_name: str = Query(...),
):
    # 1) Try SQX's resultsPlugins/settings endpoint
    raw_xml = sqx_client.get_strategy_settings(
        project=project, databank=databank, strategy_name=strategy_name,
        sqx_host=settings.sqx_host, sqx_port=None,
    )
    # 2) Fall back to parsing lastSettings.xml from the .sqx file on disk
    if raw_xml is None:
        raw_xml = _read_sqx_last_settings(project, databank, strategy_name)
    if raw_xml is None:
        return {"ok": False, "error": "Failed to retrieve strategy settings from SQX or disk"}

    parsed = sqx_client.parse_backtest_settings(raw_xml)
    raw = parsed.symbol or ""
    resolved = _resolve_mt5_symbol(raw)
    return {
        "ok": True, "symbol": resolved,
        "fromDate": parsed.from_date, "toDate": parsed.to_date,
        "timeframe": parsed.timeframe, "initialCapital": parsed.initial_capital,
    }


def _canonicalize_backtest_params(project: str, databank: str, strategy_name: str) -> dict:
    """Fetch strategy settings from SQX and return canonical backtest params.

    Used by the /backtest endpoint to override wrong form values (e.g. plugin
    sending XAUUSD/H1 for a NAS100/M30 strategy).
    """
    raw_xml = sqx_client.get_strategy_settings(
        project=project, databank=databank, strategy_name=strategy_name,
        sqx_host=settings.sqx_host, sqx_port=None,
    )
    if raw_xml is None:
        return {}
    parsed = sqx_client.parse_backtest_settings(raw_xml)
    raw = parsed.symbol or ""
    resolved = _resolve_mt5_symbol(raw)

    result = {}
    if parsed.symbol:
        result["symbol"] = resolved
    if parsed.timeframe:
        result["period"] = parsed.timeframe
    if parsed.from_date:
        result["from_date"] = parsed.from_date
    if parsed.to_date:
        result["to_date"] = parsed.to_date
    if parsed.initial_capital:
        result["deposit"] = float(parsed.initial_capital)
    return result


# ── Compile MQ5 from SQX (via SQX HTTP API) ────────────────────────
#
# BotPulse approach (reverse-engineered):
#   1. Call SQX HTTP API: sourcecode/print with project/databank/strategy
#   2. SQX returns real MQ5 source code (not stubs)
#   3. Write MQ5 to MQL5\Experts\SQXBridge\
#   4. Compile with MetaEditor: /compile:path.mq5 /log:path.log
#   5. Parse log for "Result: X errors, Y warnings"
#
# This replaces the old approach of extracting MQ5 from .sqx ZIP files,
# which only generated stub code with HasStrategyLogic() == false.


@app.post("/compile")
async def compile_strategy(body: dict[str, Any]):
    """Compile MQ5 source for a strategy via SQX's HTTP API.

    Request body:
        { "project": "...", "databank": "...", "strategyName": "..." }

    Returns:
        { "success": bool, "expertRelativePath": str, "ex5Path": str,
          "errors": int, "warnings": int|None, "log": str }
    """
    project = body.get("project", "")
    databank = body.get("databank", "")
    strategy_name = body.get("strategyName", "")

    if not strategy_name:
        return {"success": False, "errors": 1, "log": "Missing strategyName"}

    # Sanitize strategy name for file system
    # Replace ALL whitespace (spaces, non-breaking spaces U+00A0, tabs, etc.) with underscores
    safe_name = re.sub(r'\s+', '_', strategy_name).replace("\\", "_").replace("/", "_").strip()

    # Step 1: Get real MQ5 source code from SQX via HTTP API
    # (Same mechanism BotPulse uses — calls SQX's sourcecode/print endpoint)
    mq5_source = sqx_client.get_source_code(
        project=project,
        databank=databank,
        strategy_name=strategy_name,
        sqx_host=settings.sqx_host,
        sqx_port=None,  # auto-detect
    )
    if not mq5_source:
        return {
            "success": False,
            "errors": 1,
            "log": (
                f"Failed to get MQ5 source code from SQX for "
                f"'{strategy_name}'. Is SQX running on {settings.sqx_host}?"
            ),
        }

    # Step 2: Determine the MT5 data directory and write MQ5 to Experts/SQXBridge/
    # BotPulse uses: MQL5\Experts\SQXBridge\<safe_name>.mq5
    terminal_dir = Path(settings.terminal_path).parent
    # terminal_dir IS the data directory (C:\Terminal\WORKBENCH-01 for portable mode)
    data_dir = terminal_dir / "MQL5" / "Experts" / "SQXBridge"
    data_dir.mkdir(parents=True, exist_ok=True)

    mq5_file = data_dir / f"{safe_name}.mq5"
    mq5_file.write_text(mq5_source, encoding="utf-8")

    # Also write log file path for MetaEditor
    log_file = data_dir / f"{safe_name}.compile.log"

    # Step 3: Compile with MetaEditor
    metaeditor = Path(settings.metaeditor_path)
    if not metaeditor.exists():
        return {"success": False, "errors": 1, "log": f"MetaEditor not found: {metaeditor}"}

    try:
        import subprocess

        # MetaEditor: /compile:"path" /log:"path"
        compile_args = [
            str(metaeditor),
            f"/compile:{mq5_file}",
            f"/log:{log_file}",
        ]
        result = subprocess.run(
            compile_args,
            capture_output=True,
            text=True,
            timeout=120,
        )

        ex5_file = mq5_file.with_suffix(".ex5")

        # Read compile log
        log_text = ""
        if log_file.exists():
            try:
                log_text = log_file.read_text(encoding="utf-16le", errors="replace")
                if log_text.startswith("\ufeff"):
                    log_text = log_text[1:]
            except Exception:
                pass

        # Parse compile log for error/warning counts
        # BotPulse pattern: "Result: 0 errors?, X warnings?"
        log_match = re.search(
            r"Result:\s*(\d+)\s*errors?,\s*(\d+)\s*warnings?",
            log_text, re.IGNORECASE,
        )
        errors = int(log_match.group(1)) if log_match else -1
        warnings = int(log_match.group(2)) if log_match else None

        # Treat 0 errors + .ex5 created as success
        ex5_updated = ex5_file.exists()
        success = errors == 0 and ex5_updated

        if success:
            return {
                "success": True,
                "expertRelativePath": f"SQXBridge\\{safe_name}",
                "ex5Path": str(ex5_file),
                "errors": 0,
                "warnings": warnings,
                "log": log_text,
            }
        else:
            return {
                "success": False,
                "errors": errors if errors >= 0 else 1,
                "warnings": warnings,
                "log": log_text or result.stderr or result.stdout or "Compilation failed",
            }
    except subprocess.TimeoutExpired:
        return {"success": False, "errors": 1, "log": "Compilation timed out after 120s"}
    except Exception as exc:
        return {"success": False, "errors": 1, "log": str(exc)}


# ── Tick Model Map (BotPulse values) ───────────────────────────────
# every_tick_real=4, every_tick=0, ohlc_1min=1, open_prices=2, math_calculations=3
_TICK_MODEL_MAP = {
    "every_tick_real": 4,
    "every_tick": 0,
    "ohlc_1min": 1,
    "open_prices": 2,
    "math_calculations": 3,
}

# ── MT5 Data Directory Detection (BotPulse pattern) ────────────────
# BotPulse detects the MT5 data dir by scanning AppData\Roaming\MetaQuotes\Terminal
# and matching origin.txt to the install dir.

_mt5_data_dir_cache: Path | None = None
_mt5_data_dir_mode: str | None = None  # "portable" or "appdata"


def _find_mt5_data_dir(terminal_install_path: str) -> Path | None:
    """Find the MT5 data directory.

    Handles two modes:
    1. **Portable mode**: origin.txt exists in the install dir itself.
       The install directory IS the data directory.
       Reports go to: {install_dir}\\Reports\\
       Tester INI goes to: {install_dir}\\Tester\\{name}\\

    2. **Standard (AppData) mode**: origin.txt exists in
       {AppData}\\Roaming\\MetaQuotes\\Terminal\\{id}\\
       The data directory is that AppData folder.
       Reports go to: {data_dir}\\Reports\\
       Tester INI goes to: {data_dir}\\Tester\\{id}\\
    """
    global _mt5_data_dir_cache, _mt5_data_dir_mode
    if _mt5_data_dir_cache is not None:
        return _mt5_data_dir_cache

    # Use full terminal install path (e.g. C:\Terminal\WORKBENCH-01)
    install_path = Path(terminal_install_path).parent

    # 1. Check for portable mode: origin.txt in install dir itself
    portable_origin = install_path / "origin.txt"
    if portable_origin.exists():
        _mt5_data_dir_cache = install_path
        _mt5_data_dir_mode = "portable"
        print(f"[MT5] Data dir detected (portable): {_mt5_data_dir_cache}")
        return _mt5_data_dir_cache

    # 2. Standard mode: scan AppData\Roaming\MetaQuotes\Terminal
    terminal_root = Path.home() / "AppData" / "Roaming" / "MetaQuotes" / "Terminal"
    if not terminal_root.is_dir():
        return None

    for entry in terminal_root.iterdir():
        if not entry.is_dir():
            continue
        origin_file = entry / "origin.txt"
        if not origin_file.exists():
            continue
        try:
            origin = origin_file.read_text(encoding="utf-16le", errors="replace").strip()
            # Remove BOM if present
            if origin.startswith("\ufeff"):
                origin = origin[1:]
            # Compare full paths (case-insensitive)
            if origin.lower() == str(install_path).lower():
                _mt5_data_dir_cache = entry
                _mt5_data_dir_mode = "appdata"
                print(f"[MT5] Data dir detected (appdata): {_mt5_data_dir_cache} (matches {install_path})")
                return _mt5_data_dir_cache
        except Exception:
            pass

    print(f"[MT5] Could not detect MT5 data dir for '{install_path}'")
    return None


# ── Kill Stale MT5 Processes (BotPulse pattern) ──────────────────────

def _kill_stale_mt5_processes(terminal_path: str) -> None:
    """Kill any existing MT5 terminal process running the same terminal.
    
    BotPulse calls killStaleTesterProcess() before each backtest to avoid
    the new instance connecting to an existing one's port instead of running
    as a standalone tester.
    """
    import psutil
    
    exe_name = Path(terminal_path).name
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if proc.info['name'] and exe_name.lower() in proc.info['name'].lower():
                pid = proc.info['pid']
                # Don't kill ourselves
                if pid == os.getpid():
                    continue
                print(f"[MT5] Killing stale process: PID {pid} ({exe_name})")
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


# ── Async Backtest Execution ────────────────────────────────────────

async def _run_backtest_job(job: BacktestJob):
    """Run backtest in background for a job.

    Mirrors BotPulse's buildIni + runTesterExe + collectNativeReport:
    - INI: Expert=relative path, Period=string, Model=numeric, Leverage=plain
    - Reports stored in MT5 instance's Reports folder
    - Activity watchdog (5min inactivity, 6h hard cap, 5min post-sim)
    """
    import subprocess
    import time

    job.status = "testing"
    _save_job(job)

    # Sanitize strategy name for filenames (handle non-breaking spaces)
    safe_name = re.sub(r'\s+', '_', job.strategy_name).replace("\\", "_").replace("/", "_").strip()

    # Find MT5 data directory
    install_path = Path(job.terminal_path).parent
    mt5_data_dir = _find_mt5_data_dir(job.terminal_path)
    if not mt5_data_dir:
        job.status = "error"
        job.error = "Could not detect MT5 data directory. Run MT5 at least once and login."
        _save_job(job)
        return

    # Generate unique job ID for this backtest (INI name + report name)
    import uuid
    job_id = f"{safe_name}_{int(time.time())}"

    # Ensure Reports folder exists
    # Portable: {install_dir}\Reports\
    # Appdata:  {data_dir}\Reports\
    if _mt5_data_dir_mode == "portable":
        reports_dir = install_path / "Reports"
    else:
        reports_dir = mt5_data_dir / "Reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Build INI matching BotPulse's buildIni() exactly
    model_num = _TICK_MODEL_MAP.get(job.tick_model, 2)
    forward_mode = 1 if job.forward_mode else 0

    expert_path = (job.expert_relative_path or f"SQXBridge\\{safe_name}").replace("/", "\\")

    # Apply symbol mapping (e.g. NAS100 -> US100.cash) so MT5 recognizes the
    # instrument. Without this MT5 exits immediately with 0xC450001A.
    test_symbol = _resolve_mt5_symbol(job.symbol)

    ini_lines = [
        "[Tester]",
        f"Expert={expert_path}",
        f"Symbol={test_symbol}",
        f"Period={job.period}",
        "Optimization=0",
        f"Model={model_num}",
        f"FromDate={job.from_date}",
        f"ToDate={job.to_date}",
        f"ForwardMode={forward_mode}",
    ]
    if forward_mode and job.forward_date:
        ini_lines.append(f"ForwardDate={job.forward_date}")
    # Use absolute path for Report= so MT5 writes directly into Reports folder
    # (In portable mode, a bare name writes to install root instead)
    report_path_abs = str(reports_dir / job_id)

    ini_lines += [
        f"Deposit={job.deposit}",
        f"Currency={job.currency}",
        f"Leverage={job.leverage}",
        # Absolute path without extension => MT5 writes the .htm straight
        # into the specified folder (Reports) instead of install root.
        f"Report={report_path_abs}",
        "ReplaceReport=1",
        "ShutdownTerminal=1",
    ]

    # Write INI to Experts directory (BotPulse pattern)
    # MT5 Tester reads INI from: {data_dir}\MQL5\Experts\SQXBridge\{jobId}.ini
    experts_dir = mt5_data_dir / "MQL5" / "Experts" / "SQXBridge"
    experts_dir.mkdir(parents=True, exist_ok=True)
    ini_path = experts_dir / f"{job_id}.ini"

    # Also copy INI to Tester directory for compatibility
    tester_dir = mt5_data_dir / "Tester" / mt5_data_dir.name
    tester_dir.mkdir(parents=True, exist_ok=True)
    tester_ini_path = tester_dir / f"{job_id}.ini"
    ini_path.write_text("\r\n".join(ini_lines) + "\r\n", encoding="utf-8")

    # Log to file for reliability across async task boundaries
    try:
        log_path = Path(__file__).resolve().parent.parent / "backtest.log"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[BACKTEST] INI written: {ini_path}\n")
            f.write(f"[BACKTEST] MT5 data dir: {mt5_data_dir}\n")
            f.write(f"[BACKTEST] Reports dir: {reports_dir}\n")
    except Exception:
        pass
    print(f"[BACKTEST] INI written: {ini_path}", flush=True)

    # Kill any stale MT5 instance so the new one runs standalone
    _kill_stale_mt5_processes(job.terminal_path)
    time.sleep(5)  # longer pause to let ports/resources release

    # Run blocking backtest in a separate thread to avoid blocking the event loop
    import threading
    log_path = Path(__file__).resolve().parent.parent / "backtest.log"
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[BACKTEST] Starting thread for job {job.job_id}\n")
    except Exception:
        pass
    t = threading.Thread(target=_run_backtest_with_retry, args=(job, ini_path, mt5_data_dir, reports_dir, experts_dir, safe_name, expert_path), daemon=True)
    t.start()
    return  # Thread handles status/result updates


def _run_backtest_with_retry(job, ini_path, mt5_data_dir, reports_dir, experts_dir, safe_name, expert_path):
    """Run backtest with retry logic."""
    import subprocess
    from pathlib import Path

    log_path = Path(__file__).resolve().parent.parent / "backtest.log"
    max_retries = 3

    for attempt in range(1, max_retries + 1):
        try:
            _run_backtest_inner(job, ini_path, mt5_data_dir, reports_dir, experts_dir, safe_name, expert_path, log_path)
            return  # Success
        except Exception as e:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[BACKTEST] Attempt {attempt}/{max_retries} failed: {e}\n")
            if attempt < max_retries:
                time.sleep(10)  # wait before retry


def _run_backtest_sync(job, ini_path, mt5_data_dir, reports_dir, experts_dir, safe_name, expert_path):
    """Synchronous backtest runner (called from thread)."""
    import subprocess
    from pathlib import Path

    log_path = Path(__file__).resolve().parent.parent / "backtest.log"

    try:
        _run_backtest_inner(job, ini_path, mt5_data_dir, reports_dir, experts_dir, safe_name, expert_path, log_path)
    except Exception as e:
        try:
            job.status = "error"
            job.error = str(e)
            _save_job(job)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[BACKTEST] Sync error: {e}\n")
        except Exception:
            pass


def _run_backtest_inner(job, ini_path, mt5_data_dir, reports_dir, experts_dir, safe_name, expert_path, log_path):
    """Inner backtest logic (called from thread)."""
    """Synchronous backtest runner (called from thread)."""
    import subprocess
    from pathlib import Path

    log_path = Path(__file__).resolve().parent.parent / "backtest.log"

    # Launch MT5 — CRITICAL: must use /portable flag (BotPulse pattern)
    # Without /portable, MT5 uses AppData directory and can't find the INI
    tester_path = Path(job.terminal_path).parent / "terminal64.exe"
    
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[BACKTEST] Launching: {tester_path} /portable /config:{ini_path}\n")

    # Wait before launch to ensure port release
    time.sleep(3)

    proc = subprocess.Popen(
        [str(tester_path), "/portable", f"/config:{ini_path}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"[BACKTEST] terminal64.exe /portable started with PID {proc.pid}")

    # Wait for MT5 to initialize before polling
    time.sleep(10)

    # Activity monitoring (BotPulse pattern: 5 min inactivity, 6h hard cap)
    started_at = time.time()
    hard_cap = 6 * 60 * 60  # 6 hours
    post_sim_timeout = 30  # 30 sec after sim end is enough for report saving
    reached_end_at = None

    # Report-based completion detection (BotPulse pattern):
    # MT5 writes the .htm report once the simulation ends, but with
    # /portable the terminal does NOT always close itself even with
    # ShutdownTerminal=1. A report whose size stops growing is a fully
    # written report => simulation is finished, so stop waiting for exit.
    report_stem = ini_path.stem
    last_report_size = -1
    stable_polls = 0
    report_stable_needed = 8  # ~16 s of unchanged size

    while True:
        elapsed = time.time() - started_at

        # Hard cap
        if elapsed > hard_cap:
            proc.kill()
            job.status = "error"
            job.error = f"Backtest hard cap exceeded ({hard_cap // 60} minutes)"
            _save_job(job)
            return

        # Check if process finished
        proc.poll()
        if proc.returncode is not None:
            if not reached_end_at:
                reached_end_at = time.time()

            # Wait post_sim_timeout for report saving
            if time.time() - reached_end_at < post_sim_timeout:
                time.sleep(2)
                continue
            break

        # Size-stability check on the report file (install root or Reports)
        cur_report_size = -1
        for cand in (mt5_data_dir / f"{report_stem}.htm",
                     mt5_data_dir / f"{report_stem}.html",
                     reports_dir / f"{report_stem}.htm",
                     reports_dir / f"{report_stem}.html"):
            try:
                if cand.exists():
                    cur_report_size = cand.stat().st_size
                    break
            except OSError:
                pass

        if cur_report_size > 0:
            if cur_report_size == last_report_size:
                stable_polls += 1
                if stable_polls >= report_stable_needed:
                    with open(log_path, "a", encoding="utf-8") as f:
                        f.write(f"[BACKTEST] Report stable ({cur_report_size} bytes), "
                                f"sim finished after {int(elapsed)}s — stopping terminal\n")
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    time.sleep(3)  # let file handles release before copying
                    break
            else:
                stable_polls = 0
        last_report_size = cur_report_size

        # Poll for process completion
        time.sleep(2)

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[BACKTEST] terminal64.exe process exited with code {proc.returncode}\n")

        # ── Collect Report ──────────────────────────────────────────
        # MT5 with /portable writes reports to install root (BotPulse pattern).
        # The INI "Report=" value equals job_id (= ini_path.stem), so the exact
        # filename is always {job_id}.htm|.html — prefer that over prefix
        # matching, which can pick up stale reports from previous runs.
        report_candidates = [
            mt5_data_dir,                         # install root (MT5 /portable)
            reports_dir,                          # {data_dir}/Reports/
            mt5_data_dir / "reports",             # {data_dir}/reports/<date>/
        ]
        # Also check Tester Agent directories
        tester_dir = mt5_data_dir / "Tester"
        if tester_dir.exists():
            for agent in tester_dir.iterdir():
                if agent.name.startswith("Agent-") and agent.is_dir():
                    report_candidates.append(agent)

        # 1) Exact match on the job stem (authoritative)
        report_html = None
        for search_dir in report_candidates:
            for ext in (".htm", ".html"):
                cand = search_dir / f"{report_stem}{ext}"
                try:
                    if cand.exists() and cand.stat().st_size > 0:
                        report_html = cand
                        break
                except OSError:
                    pass
            if report_html is not None:
                break

        # 2) Fallback: strategy-name prefix, but ONLY files written after this
        #    job started (ignores stale reports from earlier runs) and prefer
        #    the most recently modified one.
        if report_html is None:
            report_name_prefix = f"{safe_name}_"
            for search_dir in report_candidates:
                try:
                    for html_file in search_dir.iterdir():
                        if (html_file.name.startswith(report_name_prefix)
                                and html_file.suffix.lower() in ('.htm', '.html')):
                            st = html_file.stat()
                            if st.st_mtime < started_at or st.st_size == 0:
                                continue  # stale or empty
                            if report_html is None or st.st_mtime > report_html.stat().st_mtime:
                                report_html = html_file
                except Exception:
                    pass

        if report_html is None:
            f.write(f"[BACKTEST] Report NOT FOUND (expected {report_stem}.htm)\n")
        else:
            f.write(f"[BACKTEST] Report found: {report_html} "
                    f"(mtime {time.strftime('%H:%M:%S', time.localtime(report_html.stat().st_mtime))})\n")

        report_data = None
        if report_html is not None and report_html.exists():
            # Copy report to Reports folder for consistent access
            # (skip when it is already there / when Report= pointed there)
            dest_report = reports_dir / report_html.name
            if report_html.resolve() != dest_report.resolve():
                if not dest_report.exists() or dest_report.stat().st_size != report_html.stat().st_size:
                    try:
                        import shutil
                        shutil.copy2(report_html, dest_report)
                        f.write(f"[BACKTEST] Report copied to: {dest_report}\n")
                        report_html = dest_report
                    except Exception as e:
                        f.write(f"[BACKTEST] Copy report error: {e}\n")
            try:
                # MT5 HTML reports are UTF-16 LE. Read it for stats parsing,
                # but do NOT store the full HTML in the job result: the plugin
                # never uses it and it is re-sent on every 3 s status poll.
                try:
                    html_content = report_html.read_text(encoding="utf-16", errors="replace")
                except Exception:
                    html_content = report_html.read_text(encoding="utf-8", errors="replace")
                report_data = {"path": str(report_html), "size": len(html_content)}
                f.write(f"[BACKTEST] Report saved: {len(html_content)} chars\n")
            except Exception as e:
                f.write(f"[BACKTEST] Error reading report: {e}\n")

        # Check for trades CSV (BotPulse pattern: search Tester Agent dirs)
        # Handles MT5's long-name truncation via _find_trade_csv().
        expert_base = Path(expert_path).name
        csv_path = _find_trade_csv(mt5_data_dir / "Tester", expert_base)
        if csv_path:
            f.write(f"[BACKTEST] Trades CSV found: {csv_path}\n")
            # Preserve CSV to Reports folder so equity endpoint can read it later
            try:
                import shutil
                reports_dir = mt5_data_dir / "Reports"
                reports_dir.mkdir(parents=True, exist_ok=True)
                csv_dest = reports_dir / f"{safe_name}.csv"
                shutil.copy2(csv_path, csv_dest)
                f.write(f"[BACKTEST] CSV copied to: {csv_dest}\n")
                # Also update csv_path to the preserved copy
                csv_path = csv_dest
            except Exception as e:
                f.write(f"[BACKTEST] Copy CSV error: {e}\n")
        else:
            # Also check install root
            alt_csv = mt5_data_dir / "MQL5" / "Files" / f"{safe_name}.csv"
            if alt_csv.exists():
                csv_path = alt_csv
                f.write(f"[BACKTEST] Trades CSV (alt): {csv_path}\n")

        # Parse MT5 stats from HTML report (BotPulse pattern)
        mt5_stats = None
        if report_html and report_html.exists():
            try:
                try:
                    report_txt = report_html.read_text(encoding="utf-16", errors="replace")
                except Exception:
                    report_txt = report_html.read_text(encoding="utf-8", errors="replace")
                mt5_stats = parse_mt5_report_stats(report_txt)
                if mt5_stats:
                    print(f"[BACKTEST] MT5 stats: {mt5_stats}")
            except Exception as e:
                print(f"[BACKTEST] Error parsing MT5 stats: {e}")

        # Fallback: derive stats from CSV if HTML parsing returned nothing
        if not mt5_stats and csv_path and csv_path.exists():
            try:
                buf = csv_path.read_bytes()
                is_utf16 = buf[:2] == b'\xff\xfe'
                txt = buf[2:].decode('utf-16-le') if is_utf16 else buf.decode('utf-8')
                total_trades = 0
                net_profit = 0.0
                profits = []
                losses = []
                in_deals = False
                for line in txt.split('\n'):
                    if '- List of deals' in line:
                        in_deals = True
                        continue
                    if line.startswith('-') and in_deals:
                        break
                    if not in_deals or not line.strip():
                        continue
                    parts = line.split(';')
                    if len(parts) < 14 or not parts[2]:
                        continue
                    if parts[8] == 'out':
                        profit = float(parts[12]) if parts[12] else 0
                        total_trades += 1
                        net_profit += profit
                        if profit > 0:
                            profits.append(profit)
                        elif profit < 0:
                            losses.append(abs(profit))
                if total_trades > 0:
                    mt5_stats = {
                        "NetProfit": net_profit,
                        "NumberOfTrades": total_trades,
                        "AvgLoss": round(sum(losses) / len(losses), 2) if losses else 0,
                    }
                    # Try to derive more stats from SQX if available
                    print(f"[BACKTEST] Derived stats from CSV: {mt5_stats}")
            except Exception as e:
                print(f"[BACKTEST] Error deriving CSV stats: {e}")

        # Ensure stats is never null — always provide at least basic stats
        if not mt5_stats:
            mt5_stats = {}

        # Build MT5 equity curve from CSV if available
        mt5_equity = None
        if csv_path and csv_path.exists():
            try:
                buf = csv_path.read_bytes()
                is_utf16 = buf[:2] == b'\xff\xfe'
                txt = buf[2:].decode('utf-16-le') if is_utf16 else buf.decode('utf-8')
                curve = []
                equity = float(job.deposit) if hasattr(job, 'deposit') else 10000.0
                in_deals = False
                for line in txt.split('\n'):
                    if '- List of deals' in line:
                        in_deals = True
                        continue
                    if line.startswith('-') and in_deals:
                        break
                    if not in_deals or not line.strip():
                        continue
                    parts = line.split(';')
                    if len(parts) < 14 or not parts[2]:
                        continue
                    profit = float(parts[12]) if parts[12] else 0
                    equity += profit
                    if parts[8] == 'out':
                        curve.append({"index": len(curve), "equity": round(equity, 2)})
                if curve:
                    mt5_equity = {"curve": curve}
            except Exception as e:
                print(f"[BACKTEST] Error parsing MT5 equity: {e}")

        job.result = {
            "ok": csv_path is not None or report_html is not None,
            "strategy": job.strategy_name,
            "symbol": job.symbol,
            "period": job.period,
            "report": report_data,
            "reportPath": str(report_html) if report_html is not None else None,
            "csvPath": str(csv_path) if csv_path else None,
            # Plugin contract: SQX-MT5-Backtest-Bridge reads result.stats
            "stats": mt5_stats,
            "mt5_stats": mt5_stats,
            "mt5_equity": mt5_equity,
        }
        job.status = "done"
        _save_job(job)
        f.write(f"[BACKTEST] Job done: ok={csv_path is not None}\n")


# ── Retry stuck jobs ───────────────────────────────────────────────


@app.post("/backtest/retry")
def retry_stuck_jobs():
    """Reset all 'testing' jobs to 'pending' so they can be re-submitted."""
    count = 0
    jobs = _load_jobs()
    for job in jobs:
        if job.status == "testing":
            job.status = "pending"
            job.error = None
            job.result = None
            count += 1
    _save_jobs(jobs)
    return {"reset": count}


@app.post("/backtest")
async def submit_backtest(body: dict[str, Any]):
    """Submit a backtest job.

    Request body:
        {
            "project": "...", "databank": "...", "strategyName": "...",
            "expertRelativePath": "...", "ex5Path": "...",
            "symbol": "XAUUSD", "period": "H1",
            "fromDate": "2022.01.01", "toDate": "2024.01.01",
            "forwardMode": false, "forwardDate": null,
            "tickModel": "every_tick_real",
            "deposit": 10000, "currency": "USD", "leverage": 100
        }

    Returns: { "jobId": "..." }
    """
    strategy_name = body.get("strategyName", "")
    symbol = body.get("symbol", "EURUSD")
    period = body.get("period", "H1")
    from_date = body.get("fromDate", "2022.01.01")
    to_date = body.get("toDate", "2024.01.01")
    deposit = body.get("deposit", 10000)
    currency = body.get("currency", "USD")
    leverage = body.get("leverage", 100)
    project = body.get("project", "")
    databank = body.get("databank", "")
    expert_relative_path = body.get("expertRelativePath", "")
    ex5_path = body.get("ex5Path", "")

    if not strategy_name:
        return {"error": "Missing strategyName"}

    # Canonicalize params from SQX strategy settings — overrides any wrong
    # form values (e.g. plugin defaulting to XAUUSD/H1 for a NAS100/M30 strat)
    canonical = _canonicalize_backtest_params(project, databank, strategy_name)
    if canonical:
        print(f"[BACKTEST] Canonicalized: {canonical}")
        if canonical.get("symbol"):
            symbol = canonical["symbol"]
        if canonical.get("period"):
            period = canonical["period"]
        if canonical.get("from_date"):
            from_date = canonical["from_date"]
        if canonical.get("to_date"):
            to_date = canonical["to_date"]
        if canonical.get("deposit"):
            deposit = canonical["deposit"]

    job_id = str(uuid.uuid4())
    job = BacktestJob(
        job_id=job_id, project=project, databank=databank,
        strategy_name=strategy_name, symbol=symbol, period=period,
        from_date=from_date, to_date=to_date,
        tick_model=body.get("tickModel", "open_prices"),
        deposit=float(deposit), currency=currency, leverage=int(leverage),
        terminal_path=settings.terminal_path,
        forward_mode=body.get("forwardMode", False),
        forward_date=body.get("forwardDate"),
        expert_relative_path=expert_relative_path,
        ex5_path=ex5_path,
    )
    job.status = "pending"

    async with _jobs_lock:
        _jobs[job_id] = job

    _save_job(job)

    # Start backtest in background
    asyncio.create_task(_run_backtest_job(job))

    return {"jobId": job_id}


@app.get("/backtest/{job_id}/status")
async def get_backtest_status(job_id: str):
    """Poll backtest job status.

    Returns:
        { "status": "pending"|"testing"|"done"|"error",
          "result": {...} when done,
          "error": "..." when error }
    """
    # Read from DB for consistency with sync backtest runners
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT status, result, error FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return {"status": "error", "error": "Job not found"}

    result = {"status": row[0]}
    if row[1]:
        try:
            result["result"] = json.loads(row[1])
        except Exception:
            pass
    if row[2]:
        result["error"] = row[2]
    return result


# ── Local Jobs History ──────────────────────────────────────────────


@app.get("/local-jobs")
def get_local_jobs(
    project: str = Query(None),
    databank: str = Query(None),
):
    """Get backtest history.

    Returns list of jobs with id, strategyName, symbol, period,
    createdAt, status, reportKey.
    """
    return {"jobs": _get_jobs(project=project, databank=databank)}


# ── View Report ─────────────────────────────────────────────────────


@app.get("/view-report")
def view_report(
    report_key: str = Query(...),
    which: str = Query("mt5"),
):
    """Serve the MT5 HTML report directly (plugin opens it via window.open).

    reportKey = strategyName_symbol_period. Newest matching job wins, and the
    UTF-16 LE report is decoded so browsers render it as normal HTML.
    """
    from fastapi.responses import HTMLResponse, JSONResponse

    # 1) Resolve via stored job result — newest first
    conn = _get_db()
    rows = conn.execute(
        "SELECT strategy_name, result FROM jobs "
        "WHERE strategy_name || '_' || symbol || '_' || period = ? "
        "ORDER BY created_at DESC",
        (report_key,),
    ).fetchall()
    if not rows:
        # Fallback: strategy name may contain NBSP/whitespace mangled by the UI
        key_stem = report_key.rsplit("_", 2)[0] if report_key.count("_") >= 2 else report_key
        norm = lambda s: re.sub(r"\s+", " ", s).strip()
        all_rows = conn.execute(
            "SELECT strategy_name, result FROM jobs ORDER BY created_at DESC LIMIT 300"
        ).fetchall()
        rows = [r for r in all_rows if norm(r[0]) == norm(key_stem)]
    conn.close()

    report_path: Path | None = None
    for _strat, res_json in rows:
        if not res_json:
            continue
        try:
            res = json.loads(res_json)
        except Exception:
            continue
        rp = res.get("reportPath")
        if rp and Path(rp).exists():
            report_path = Path(rp)
            break

    # 2) Fallback: newest .htm in Reports folder / install root matching prefix
    if report_path is None:
        prefix = re.sub(r"[^A-Za-z0-9._-]", "_", report_key)
        try:
            install_dir = Path(settings.terminal_path).parent
            for d in (install_dir / "Reports", install_dir):
                for p in sorted(d.glob("*.htm"), key=lambda x: x.stat().st_mtime, reverse=True):
                    if p.name.startswith(prefix[:40]):
                        report_path = p
                        break
                if report_path:
                    break
        except Exception:
            pass

    if report_path is None:
        return JSONResponse(
            {"error": "Report not found", "reportKey": report_key}, status_code=404
        )

    # MT5 writes reports as UTF-16 LE with BOM — decode so the browser
    # receives well-formed HTML rather than raw UTF-16 bytes.
    try:
        html = report_path.read_text(encoding="utf-16", errors="replace")
    except Exception:
        try:
            html = report_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return JSONResponse(
                {"error": f"Cannot read report: {e}", "reportPath": str(report_path)},
                status_code=500,
            )

    return HTMLResponse(content=html, media_type="text/html; charset=utf-8")


# ── Main ─────────────────────────────────────────────────────────────


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "server:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )

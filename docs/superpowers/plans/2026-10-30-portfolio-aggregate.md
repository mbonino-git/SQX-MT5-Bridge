# Consolidated Backtest Results View

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the separate single-strategy "SQX vs MT5" section and portfolio results with one unified "Results" section that works for both: a strategy table where you click rows to see per-strategy comparisons + equity, plus an aggregate stats table and merged equity chart at the bottom.

**Architecture:** Add a `/results` endpoint that takes either `strategy_name` (single) or `portfolio_key` (portfolio) and returns stats comparison + equity data. The frontend replaces the separate sections with a single Results view that always shows: strategy table → click to expand → aggregate stats + equity.

**Tech Stack:** Python 3, FastAPI, Vue 3

**Spec:** N/A — direct feature request.

## Global Constraints

- Use the existing `_portfolio_backtest_jobs` dict for portfolio state
- Follow existing stats keys from SQX: NetProfit, NumberOfTrades, ProfitFactor, PctDrawdown, WinningPct, AvgLoss, MaxConsecWins, MaxConsecLoss
- Equity merge: align all strategies by trade sequence (trade index N across strategies)
- Frontend uses existing CSS classes: `batch-row-selected`, `equity-chart`, `compare`
- No new dependencies
- Single strategy mode: aggregate = that one strategy's data (same as current "4. SQX vs MT5")
- Portfolio mode: aggregate = sum of completed strategies

## Review Focus

1. Empty portfolio (0 strategies) — endpoint should return sensible empty structure
2. Strategies with different deposit amounts — aggregate should handle per-strategy deposits
3. Strategies that failed — aggregate should only include completed/done strategies
4. ProfitFactor aggregation — summing PFs doesn't work; use combined GrossProfit/GrossLoss or harmonic mean
5. Equity merge with different trade counts — pad shorter curves with last value

---

### Task 1: Add `/results` endpoint (unified single + portfolio)

**Files:**
- Modify: `sqx_mt5_bridge/server.py` — add new endpoint after `get_equity` (around line 1040)

**Interfaces:**
- Consumes: `_portfolio_backtest_jobs`, existing stats/equity logic, `get_stats()` helper
- Produces: `GET /results?strategy_name=...` (single) or `GET /results?portfolio_key=...` (portfolio) → same return format

Return format (unified):
```python
{
    "ok": True,
    "mode": "single" | "portfolio",
    "aggregate": {
        "stats": { "NetProfit": ..., "NumberOfTrades": ..., ... },
        "comparison": [
            {"key": "NetProfit", "label": "Net Profit", "sqxDisplay": "1234", "mt5Display": "1200", "diffDisplay": "-2.7%", "diffClass": "diff-ok"},
            # ... all 8 metrics
        ],
        "completed": N,
        "total": M,
    },
    "equity": {
        "sqx": {"points": [[0, initial], [1, v1], ...]},
        "mt5": {"points": [[0, initial], [1, v1], ...]},
    },
}
```

- [ ] **Step 1: Write the endpoint skeleton in server.py**

Add `@app.get("/results")` after `get_equity` (~line 1040). Supports two query modes:

```python
@app.get("/results")
def get_results(
    strategy_name: str = Query(None, description="Single strategy name"),
    project: str = Query(None, description="Project name"),
    databank: str = Query(None, description="Databank name"),
    portfolio_key: str = Query(None, description="Portfolio backtest key"),
):
```

- [ ] **Step 2: Single-strategy path**

When `strategy_name` is provided:
1. Fetch SQX stats via existing `get_stats(project, databank, strategy_name)`
2. Fetch MT5 stats from the most recent backtest result in the database for that strategy, or from the `_portfolio_backtest_jobs` if this was a portfolio backtest result
3. Build `comparison` list using existing `diffRow()` logic (recreate in the endpoint)
4. Build equity from existing `get_equity()` logic (reuse the function)
5. Return in the unified format with `mode: "single"`

- [ ] **Step 3: Portfolio path**

When `portfolio_key` is provided:
1. Look up the portfolio job in `_portfolio_backtest_jobs`
2. For each job with `status == "done"`, extract `result` dict which contains `stats` (MT5) and `comparison` (SQX)
3. Aggregate metrics:
   - `NetProfit`: sum of MT5 NetProfit
   - `NumberOfTrades`: sum of MT5 NumberOfTrades
   - `ProfitFactor`: weighted by absolute NetProfit, or use `sum(gross_profit) / sum(abs(gross_loss))` if available
   - `PctDrawdown`: maximum PctDrawdown (worst-case)
   - `WinningPct`: total winning / total trades
   - `AvgLoss`: weighted average by trade count
   - `MaxConsecWins`: max across strategies
   - `MaxConsecLoss`: max across strategies
4. Merge equity curves: align by trade index, pad shorter curves, sum values
5. Return in the unified format with `mode: "portfolio"`, `completed` and `total` counts

- [ ] **Step 4: Return format and edge cases**

Handle:
- `strategy_name` provided but not found → `{"ok": False, "error": "..."}`
- `portfolio_key` not found → `{"ok": False, "error": "..."}`
- No completed strategies in portfolio → return aggregate with zeroes and empty equity
- Missing SQX stats for a strategy → skip in aggregate, log warning

- [ ] **Step 5: Verify syntax and restart bridge**

Run: `python -c "import ast; ast.parse(open('sqx_mt5_bridge/server.py').read()); print('Syntax OK')"`

Then restart the bridge: kill the running Python process on port 8090 and start it again.

- [ ] **Step 6: Commit**

```bash
git add sqx_mt5_bridge/server.py
git commit -m "feat: add /results endpoint for unified single and portfolio results view"
```

### Task 2: Frontend — Unified Results section (replaces both "SQX vs MT5" and portfolio detail)

**Files:**
- Modify: `sqx_plugin_html/index.html` — remove old sections, add unified "Results" section

**Interfaces:**
- Consumes: existing state variables (`phase`, `comparison`, `batchResults`, `portfolioResults`, `portfolioPortfolioKey`)
- Produces: Single "Results" section that works for both single strategy and portfolio modes

**Layout** (unified for both modes):

```
RESULTS
  ┌ RESULTS TABLE (1 row for single, N for portfolio) ──┐
  └─────────────────────────────────────────────────────┘

  INDIVIDUAL STRATEGY DETAIL (click row to expand)
  ┌ COMPARISON TABLE ───────────────┐ ┌ EQUITY CHARTS ─────┐
  └─────────────────────────────────┘ └────────────────────┘

  AGGREGATE
  ┌ STATS TABLE ────────────────────┐ ┌ EQUITY CHARTS ─────┐
  └─────────────────────────────────┘ └────────────────────┘
```

For single strategy mode: the table has 1 row, the "individual detail" shows that strategy's comparison, and the "aggregate" section shows the same data.

For portfolio mode: the table has N rows, clicking shows per-strategy detail, and aggregate shows combined stats + merged equity.

- [ ] **Step 1: Add unified results state refs**

Add for aggregate:
```javascript
const resultsAggregate = ref(null);
const resultsAggregateLoading = ref(false);
```

- [ ] **Step 2: Remove old sections**

Remove the old "4. Comparison" section (lines ~713-750) and replace it with the unified "Results" section.

For single strategy: currently shows `comparison` table + equity charts. This becomes the "individual detail" portion.

For portfolio: currently shows the strategy table (lines 539-598) with expand rows. The table stays, but the detail section and new aggregate section are unified.

- [ ] **Step 3: Write the unified Results HTML section**

Replace the old sections with a single card containing:
1. Results table (single strategy row OR portfolio strategy table with checkboxes)
2. Individual detail section (comparison table + equity charts for the selected strategy)
3. Aggregate section (stats comparison table + merged equity charts)

The individual detail section shows:
- For single mode: the strategy's comparison table + equity charts
- For portfolio mode: only visible when `portfolioSelectedIdx !== null`

The aggregate section shows:
- For single mode: the same comparison + equity (same data, redundant but consistent)
- For portfolio mode: summed stats + merged equity curves

- [ ] **Step 4: Wire up aggregate fetching for both modes**

For single strategy: when `phase === 'done'`, call `/results?strategy_name=...&project=...&databank=...` to get the aggregate.

For portfolio: when all portfolio results are done, call `/results?portfolio_key=...` to get the aggregated view.

- [ ] **Step 5: Draw aggregate equity charts**

Add `_drawAggregateEquity(equityData)` function. After fetching aggregate, draw the charts targeting `results-aggregate-sqx` and `results-aggregate-mt5`.

- [ ] **Step 6: Update return to expose new refs**

In the `return { ... }` at the bottom of the Vue component, add:
```javascript
resultsAggregate, resultsAggregateLoading,
```

- [ ] **Step 7: Verify and commit**

Run: `python -c "import ast; ast.parse(open('sqx_mt5_bridge/server.py').read()); print('Python Syntax OK')"`

```bash
git add sqx_plugin_html/index.html
git commit -m "feat: unified results section for single and portfolio backtests"
```

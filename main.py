from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import math
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="StockLens Pro API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def safe_float(val, default=0):
    try:
        f = float(val)
        return 0 if math.isnan(f) or math.isinf(f) else f
    except Exception:
        return default

def safe_round(val, digits=2, default=0):
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return round(f, digits)
    except Exception:
        return default

def crore(val):
    """Convert raw number to Crore (1e7), rounded to 2 decimal places."""
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return 0
        return round(f / 1e7, 2)
    except Exception:
        return 0


# ─────────────────────────────────────────────
# ROOT
# ─────────────────────────────────────────────

@app.get("/")
def home():
    return {"status": "StockLens Pro API v2.0 running"}


# ─────────────────────────────────────────────
# MAIN STOCK ENDPOINT
# ─────────────────────────────────────────────

@app.get("/stock/{symbol}")
def get_stock(symbol: str):
    symbol = symbol.strip().upper()

    # Basic input guard
    if not symbol.isalpha() or len(symbol) > 20:
        raise HTTPException(status_code=400, detail="Invalid symbol")

    ticker = yf.Ticker(f"{symbol}.NS")

    try:
        info = ticker.info
    except Exception as e:
        logger.error(f"[{symbol}] info fetch failed: {e}")
        raise HTTPException(status_code=502, detail="Could not reach data source")

    if not info or info.get("regularMarketPrice") is None and info.get("currentPrice") is None:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found on NSE")

    price = safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
    eps   = safe_float(info.get("trailingEps"))
    bv    = safe_float(info.get("bookValue"))
    pe    = safe_float(info.get("trailingPE"))
    fwd_pe = safe_float(info.get("forwardPE"))

    # ── Graham Number ──────────────────────────────
    graham = 0
    if eps > 0 and bv > 0:
        graham = safe_round(math.sqrt(22.5 * eps * bv))

    # ── ROE (%) ────────────────────────────────────
    # yfinance returns as decimal e.g. 0.15 = 15%
    roe_raw = info.get("returnOnEquity")
    roe = safe_round(safe_float(roe_raw) * 100, 2) if roe_raw is not None else None

    # ── ROCE — compute from income_stmt + balance_sheet ───
    roce = None
    try:
        inc  = ticker.income_stmt
        bals = ticker.balance_sheet
        if inc is not None and not inc.empty and bals is not None and not bals.empty:
            col = inc.columns[0]   # most recent annual
            ebit = 0
            for k in ["EBIT", "Operating Income"]:
                if k in inc.index:
                    ebit = safe_float(inc.loc[k, col])
                    break

            # Capital Employed = Total Assets - Current Liabilities
            ta = 0
            cl = 0
            for k in ["Total Assets"]:
                if k in bals.index:
                    ta = safe_float(bals.loc[k, bals.columns[0]])
                    break
            for k in ["Current Liabilities", "Total Current Liabilities Net Minority Interest"]:
                if k in bals.index:
                    cl = safe_float(bals.loc[k, bals.columns[0]])
                    break
            ce = ta - cl
            if ce > 0:
                roce = safe_round((ebit / ce) * 100, 2)
    except Exception as e:
        logger.warning(f"[{symbol}] ROCE calculation failed: {e}")

    # ── Dividend Yield ──────────────────────────────
    # yfinance returns as decimal fraction e.g. 0.004 = 0.4%
    # DO NOT multiply by 100 again — just store as-is and let frontend multiply
    div_yield_raw = info.get("dividendYield")
    div_yield = safe_float(div_yield_raw)  # e.g. 0.004

    # ── Quarterly Income ───────────────────────────
    quarterly_financials = []
    try:
        qf = ticker.quarterly_income_stmt
        if qf is not None and not qf.empty:
            for col in list(qf.columns)[:8]:
                rev = 0
                prof = 0
                for k in ["Total Revenue", "Revenue"]:
                    if k in qf.index:
                        rev = safe_float(qf.loc[k, col])
                        break
                for k in ["Net Income", "Net Income Common Stockholders"]:
                    if k in qf.index:
                        prof = safe_float(qf.loc[k, col])
                        break
                quarterly_financials.append({
                    "quarter": str(col)[:7],
                    "revenue": crore(rev),
                    "profit": crore(prof)
                })
    except Exception as e:
        logger.warning(f"[{symbol}] quarterly_income_stmt failed: {e}")

    # ── Annual Income ──────────────────────────────
    annual_financials = []
    try:
        fin = ticker.income_stmt
        if fin is not None and not fin.empty:
            for col in list(fin.columns)[:6]:
                rev = 0
                prof = 0
                for k in ["Total Revenue", "Revenue"]:
                    if k in fin.index:
                        rev = safe_float(fin.loc[k, col])
                        break
                for k in ["Net Income", "Net Income Common Stockholders"]:
                    if k in fin.index:
                        prof = safe_float(fin.loc[k, col])
                        break
                annual_financials.append({
                    "year": str(col)[:4],
                    "revenue": crore(rev),
                    "profit": crore(prof)
                })
    except Exception as e:
        logger.warning(f"[{symbol}] income_stmt failed: {e}")

    # ── Quarterly Cash Flow ────────────────────────
    cashflow_quarterly = []
    try:
        qcf = ticker.quarterly_cashflow
        if qcf is not None and not qcf.empty:
            for col in list(qcf.columns)[:8]:
                ocf  = 0
                capex = 0
                for k in ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"]:
                    if k in qcf.index:
                        ocf = safe_float(qcf.loc[k, col])
                        break
                for k in ["Capital Expenditure", "Purchase Of Plant And Equipment"]:
                    if k in qcf.index:
                        capex = safe_float(qcf.loc[k, col])
                        break
                fcf = ocf + capex  # capex is negative in yfinance
                cashflow_quarterly.append({
                    "quarter": str(col)[:7],
                    "operating_cf": crore(ocf),
                    "capex": crore(abs(capex)),
                    "free_cf": crore(fcf)
                })
    except Exception as e:
        logger.warning(f"[{symbol}] quarterly_cashflow failed: {e}")

    # ── Annual Cash Flow ───────────────────────────
    cashflow_annual = []
    try:
        acf = ticker.cashflow
        if acf is not None and not acf.empty:
            for col in list(acf.columns)[:6]:
                ocf  = 0
                capex = 0
                for k in ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"]:
                    if k in acf.index:
                        ocf = safe_float(acf.loc[k, col])
                        break
                for k in ["Capital Expenditure", "Purchase Of Plant And Equipment"]:
                    if k in acf.index:
                        capex = safe_float(acf.loc[k, col])
                        break
                fcf = ocf + capex
                cashflow_annual.append({
                    "year": str(col)[:4],
                    "operating_cf": crore(ocf),
                    "capex": crore(abs(capex)),
                    "free_cf": crore(fcf)
                })
    except Exception as e:
        logger.warning(f"[{symbol}] cashflow failed: {e}")

    # ── Balance Sheet Highlights ───────────────────
    balance = {}
    try:
        bs = ticker.quarterly_balance_sheet
        if bs is not None and not bs.empty:
            col = bs.columns[0]
            cash = 0
            debt = 0
            for k in ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"]:
                if k in bs.index:
                    cash = safe_float(bs.loc[k, col])
                    break
            for k in ["Total Debt", "Long Term Debt"]:
                if k in bs.index:
                    debt = safe_float(bs.loc[k, col])
                    break
            balance = {
                "cash": crore(cash),
                "total_debt": crore(debt)
            }
    except Exception as e:
        logger.warning(f"[{symbol}] balance_sheet failed: {e}")

    # ── EPS Quarterly ──────────────────────────────
    # Compute from net_income / shares if quarterly_earnings unavailable
    eps_quarters = []
    try:
        qf = ticker.quarterly_income_stmt
        shares = safe_float(info.get("sharesOutstanding", 0))
        if qf is not None and not qf.empty and shares > 0:
            for col in list(qf.columns)[:8]:
                ni = 0
                for k in ["Net Income", "Net Income Common Stockholders"]:
                    if k in qf.index:
                        ni = safe_float(qf.loc[k, col])
                        break
                eps_q = safe_round(ni / shares, 2)
                eps_quarters.append({
                    "quarter": str(col)[:7],
                    "eps": eps_q
                })
    except Exception as e:
        logger.warning(f"[{symbol}] EPS quarters calc failed: {e}")

    # ── 1-Year Price History ───────────────────────
    price_history = []
    try:
        hist = ticker.history(period="1y", interval="1d")
        if not hist.empty:
            for idx, row in hist.iterrows():
                price_history.append({
                    "date": str(idx.date()),
                    "close": safe_round(row["Close"], 2),
                    "volume": int(row["Volume"]) if row["Volume"] else 0
                })
    except Exception as e:
        logger.warning(f"[{symbol}] price history failed: {e}")

    # ── Analyst Recommendations ────────────────────
    analyst = {"strong_buy": 0, "buy": 0, "hold": 0, "sell": 0, "strong_sell": 0, "total": 0}
    try:
        rec = ticker.recommendations
        if rec is not None and not rec.empty:
            # Get last 3 months
            recent = rec.tail(90) if len(rec) > 90 else rec
            for _, row in recent.iterrows():
                period_str = str(row.get("period", ""))
                # Only use current period data
                if "0m" in period_str or "-1m" in period_str or "-2m" in period_str:
                    analyst["strong_buy"]  += int(row.get("strongBuy",  0) or 0)
                    analyst["buy"]         += int(row.get("buy",         0) or 0)
                    analyst["hold"]        += int(row.get("hold",        0) or 0)
                    analyst["sell"]        += int(row.get("sell",        0) or 0)
                    analyst["strong_sell"] += int(row.get("strongSell",  0) or 0)

        # Fallback: use recommendations_summary
        if all(v == 0 for v in analyst.values()):
            rs = ticker.recommendations_summary
            if rs is not None and not rs.empty:
                row = rs.iloc[0]
                analyst["strong_buy"]  = int(row.get("strongBuy",  0) or 0)
                analyst["buy"]         = int(row.get("buy",         0) or 0)
                analyst["hold"]        = int(row.get("hold",        0) or 0)
                analyst["sell"]        = int(row.get("sell",        0) or 0)
                analyst["strong_sell"] = int(row.get("strongSell",  0) or 0)

        analyst["total"] = sum([
            analyst["strong_buy"], analyst["buy"], analyst["hold"],
            analyst["sell"], analyst["strong_sell"]
        ])
    except Exception as e:
        logger.warning(f"[{symbol}] recommendations failed: {e}")

    # ── Institutional / FII Holders ────────────────
    top_holders = []
    try:
        inst = ticker.institutional_holders
        if inst is not None and not inst.empty:
            for _, row in inst.head(8).iterrows():
                pct = safe_float(row.get("pctHeld") or row.get("% Out") or 0)
                top_holders.append({
                    "name": str(row.get("Holder", row.get("Name", "Unknown"))),
                    "pct": safe_round(pct * 100, 2)
                })
    except Exception as e:
        logger.warning(f"[{symbol}] institutional_holders failed: {e}")

    # ── Current Ratio ──────────────────────────────
    current_ratio = None
    try:
        bs = ticker.quarterly_balance_sheet
        if bs is not None and not bs.empty:
            col = bs.columns[0]
            ca = cl_val = 0
            for k in ["Current Assets", "Total Current Assets"]:
                if k in bs.index:
                    ca = safe_float(bs.loc[k, col])
                    break
            for k in ["Current Liabilities", "Total Current Liabilities Net Minority Interest"]:
                if k in bs.index:
                    cl_val = safe_float(bs.loc[k, col])
                    break
            if cl_val > 0:
                current_ratio = safe_round(ca / cl_val, 2)
    except Exception as e:
        logger.warning(f"[{symbol}] current_ratio failed: {e}")

    # ──────────────────────────────────────────────
    # RESPONSE
    # ──────────────────────────────────────────────
    return {
        "symbol": symbol,
        "name": info.get("longName", ""),
        "sector": info.get("sector", ""),
        "industry": info.get("industry", ""),

        # Pricing
        "price": price,
        "week_high": safe_float(info.get("fiftyTwoWeekHigh")),
        "week_low": safe_float(info.get("fiftyTwoWeekLow")),
        "market_cap": safe_float(info.get("marketCap")),

        # Valuation
        "pe": safe_round(pe),
        "forward_pe": safe_round(fwd_pe),
        "pb_ratio": safe_round(safe_float(info.get("priceToBook"))),
        "ps_ratio": safe_round(safe_float(info.get("priceToSalesTrailing12Months"))),
        "peg_ratio": safe_round(safe_float(info.get("pegRatio"))),
        "ev_ebitda": safe_round(safe_float(info.get("enterpriseToEbitda"))),

        # Per Share
        "eps": safe_round(eps),
        "book_value": safe_round(bv),
        "revenue_per_share": safe_round(safe_float(info.get("revenuePerShare"))),

        # Profitability
        "roe": roe,                   # % or None
        "roce": roce,                 # % or None
        "profit_margin": safe_round(safe_float(info.get("profitMargins")) * 100, 2),
        "operating_margin": safe_round(safe_float(info.get("operatingMargins")) * 100, 2),
        "gross_margin": safe_round(safe_float(info.get("grossMargins")) * 100, 2),

        # Leverage & Liquidity
        "debt_equity": safe_round(safe_float(info.get("debtToEquity"))),
        "current_ratio": current_ratio,

        # Yield & Growth
        "dividend_yield": div_yield,      # raw decimal e.g. 0.004
        "revenue_growth": safe_round(safe_float(info.get("revenueGrowth")) * 100, 2),    # %
        "earnings_growth": safe_round(safe_float(info.get("earningsGrowth")) * 100, 2),  # %

        # Holdings
        "promoter_holding": safe_round(safe_float(info.get("heldPercentInsiders")) * 100, 2),
        "fii_holding": safe_round(safe_float(info.get("heldPercentInstitutions")) * 100, 2),

        # Fair Value
        "fair_value": {
            "graham": graham,
            "pe_method": safe_round(eps * fwd_pe) if eps and fwd_pe else 0
        },

        # Financials
        "quarterly_financials": quarterly_financials,   # reversed (latest first)
        "annual_financials": annual_financials,
        "cashflow_quarterly": cashflow_quarterly,
        "cashflow_annual": cashflow_annual,
        "eps_quarters": eps_quarters,                   # computed from NI / shares

        # Balance Sheet
        "balance": balance,

        # Price History
        "price_history": price_history,                 # 1y daily OHLCV

        # Analyst
        "analyst": analyst,
        "top_holders": top_holders,
    }

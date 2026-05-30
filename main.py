from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
from yahooquery import Ticker as YQTicker
import pandas as pd
import math
import logging
import requests

# Setup custom session for yfinance to bypass blocks
yf_session = requests.Session()
yf_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="StockLens Pro API", version="2.1")

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
    return {"status": "StockLens Pro API v2.1 running"}

# ─────────────────────────────────────────────
# SEARCH ENDPOINT
# ─────────────────────────────────────────────

@app.get("/search/{query}")
def search_stocks(query: str):
    query = query.strip()
    if not query:
        return []
    
    url = f"https://query2.finance.yahoo.com/v1/finance/search?q={query}&quotesCount=10&newsCount=0"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        data = response.json()
        quotes = data.get("quotes", [])
        
        results = []
        for q in quotes:
            symbol = q.get("symbol", "")
            quote_type = q.get("quoteType", "")
            
            # Only include NSE/BSE EQUITIES (ignore mutual funds, ETFs, etc.)
            if quote_type == "EQUITY" and (symbol.endswith(".NS") or symbol.endswith(".BO")):
                clean_symbol = symbol.replace(".NS", "").replace(".BO", "")
                name = q.get("longname") or q.get("shortname") or clean_symbol
                
                # Explicitly exclude ETFs which Yahoo sometimes classifies as EQUITY
                if "ETF" not in clean_symbol.upper() and "ETF" not in name.upper():
                    results.append({
                        "symbol": clean_symbol,
                        "name": name,
                        "exchange": q.get("exchange", "")
                    })
                
        return results[:5]  # return top 5
    except Exception as e:
        logger.error(f"Search failed: {e}")
        return []

# ─────────────────────────────────────────────
# MAIN STOCK ENDPOINT
# ─────────────────────────────────────────────

@app.get("/stock/{symbol}")
def get_stock(symbol: str):
    symbol = symbol.strip().upper()
    if not symbol.replace("-", "").replace("&", "").isalnum() or len(symbol) > 20:
        raise HTTPException(status_code=400, detail="Invalid symbol")

    t = YQTicker(f"{symbol}.NS")
    
    try:
        sum_det = t.summary_detail.get(f"{symbol}.NS", {})
        if isinstance(sum_det, str) or not sum_det:
            raise HTTPException(status_code=404, detail="Symbol not found")
            
        key_stats = t.key_stats.get(f"{symbol}.NS", {})
        fin_data = t.financial_data.get(f"{symbol}.NS", {})
        price_obj = t.price.get(f"{symbol}.NS", {})
        
        price = safe_float(sum_det.get("regularMarketPrice") or fin_data.get("currentPrice"))
        if price == 0:
            raise HTTPException(status_code=404, detail="Symbol not found")
            
        eps = safe_float(key_stats.get("trailingEps"))
        bv = safe_float(key_stats.get("bookValue"))
        pe = safe_float(sum_det.get("trailingPE"))
        fwd_pe = safe_float(sum_det.get("forwardPE"))
        
        graham = 0
        if eps > 0 and bv > 0:
            graham = safe_round(math.sqrt(22.5 * eps * bv))
            
        roe_raw = fin_data.get("returnOnEquity")
        roe = safe_round(safe_float(roe_raw) * 100, 2) if roe_raw is not None else None
        
        # We will use yfinance just for history, as the v8 chart endpoint is usually unblocked
        price_history = []
        try:
            yt = yf.Ticker(f"{symbol}.NS", session=yf_session)
            hist = yt.history(period="1y", interval="1d")
            if not hist.empty:
                for idx, row in hist.iterrows():
                    price_history.append({
                        "date": str(idx.date()),
                        "close": safe_round(row["Close"], 2),
                        "volume": int(row["Volume"]) if row["Volume"] else 0
                    })
        except:
            pass

        return {
            "symbol": symbol,
            "name": price_obj.get("longName", ""),
            "sector": price_obj.get("sector", ""),
            "industry": price_obj.get("industry", ""),
            "price": price,
            "market_cap": safe_float(price_obj.get("marketCap")),
            "pe": safe_round(pe),
            "forward_pe": safe_round(fwd_pe),
            "eps": safe_round(eps),
            "book_value": safe_round(bv),
            "roe": roe,
            "dividend_yield": safe_float(sum_det.get("dividendYield")),
            "fair_value": {
                "graham": graham,
                "pe_method": safe_round(eps * fwd_pe) if eps and fwd_pe else 0
            },
            "price_history": price_history,
            "quarterly_financials": [],
            "annual_financials": [],
            "cashflow_quarterly": [],
            "cashflow_annual": [],
            "eps_quarters": [],
            "balance": {},
            "analyst": {"strong_buy":0, "buy":0, "hold":0, "sell":0, "strong_sell":0, "total":0},
            "top_holders": []
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[{symbol}] error: {e}")
        raise HTTPException(status_code=502, detail="Could not reach data source")

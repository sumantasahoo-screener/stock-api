from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
from yahooquery import Ticker as YQTicker
import pandas as pd
import math
from bs4 import BeautifulSoup
import requests
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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# HELPERS
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# ROOT
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.get("/")
def home():
    return {"status": "StockLens Pro API v2.1 running"}

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# SEARCH ENDPOINT
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# MAIN STOCK ENDPOINT
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.get("/stock/{symbol}")
def get_stock(symbol: str):
    symbol = symbol.strip().upper()
    if not symbol.replace("-", "").replace("&", "").isalnum() or len(symbol) > 20:
        raise HTTPException(status_code=400, detail="Invalid symbol")

    try:
        # Fetch fundamentals from Screener.in
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        r = requests.get(f"https://www.screener.in/company/{symbol}/consolidated/", headers=headers, timeout=10)
        
        # If consolidated fails or doesn't exist, try standalone
        if r.status_code == 404 or "Looks like the page you are looking for does not exist" in r.text:
            r = requests.get(f"https://www.screener.in/company/{symbol}/", headers=headers, timeout=10)
            
        if r.status_code != 200:
            raise HTTPException(status_code=404, detail="Symbol not found")
            
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # Get Name
        name_elem = soup.find('h1', class_='margin-0')
        name = name_elem.text.strip() if name_elem else symbol
        
        # Extract Top Ratios
        ratios = {}
        ratio_div = soup.find('div', class_='company-ratios')
        if ratio_div:
            for li in ratio_div.find_all('li'):
                try:
                    k = li.find('span', class_='name').text.strip()
                    v = li.find('span', class_='number').text.strip().replace(',', '')
                    ratios[k] = safe_float(v)
                except:
                    pass

        price = ratios.get("Current Price", 0)
        mc = ratios.get("Market Cap", 0)
        pe = ratios.get("Stock P/E", 0)
        bv = ratios.get("Book Value", 0)
        div_yield = ratios.get("Dividend Yield", 0)
        roce = ratios.get("ROCE", 0)
        roe = ratios.get("ROE", 0)
        
        # Calculate EPS
        eps = 0
        if pe > 0:
            eps = price / pe
            
        # Graham Number
        graham = 0
        if eps > 0 and bv > 0:
            graham = safe_round(math.sqrt(22.5 * eps * bv))
            
        # Try fetching 1 year history from yfinance if it works
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
            "name": name,
            "sector": "",
            "industry": "",
            "price": price,
            "market_cap": mc * 10000000 if mc > 0 else 0, # Frontend expects absolute, not crores
            "pe": safe_round(pe),
            "forward_pe": 0,
            "eps": safe_round(eps),
            "book_value": safe_round(bv),
            "roe": roe,
            "roce": roce,
            "dividend_yield": div_yield / 100 if div_yield else 0, # Frontend expects decimal
            "fair_value": {
                "graham": graham,
                "pe_method": 0
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

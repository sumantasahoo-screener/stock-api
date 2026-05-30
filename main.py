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

def _parse_screener_table(section_id, soup, max_cols=8):
    """Parse a Screener.in table section and return headers + rows."""
    sec = soup.find('section', id=section_id)
    if not sec:
        return [], []
    table = sec.find('table')
    if not table:
        return [], []
    thead = table.find('thead')
    headers = [th.text.strip() for th in thead.find_all('th')] if thead else []
    rows = []
    tbody = table.find('tbody')
    if tbody:
        for tr in tbody.find_all('tr'):
            cells = [td.text.strip().replace('\xa0', ' ').replace(',', '') for td in tr.find_all('td')]
            rows.append(cells)
    return headers[:max_cols], rows

def _clean_num(s):
    """Clean a number string from Screener: remove commas, %, +, spaces."""
    if not s:
        return 0
    s = s.replace(',', '').replace('%', '').replace('+', '').strip()
    return safe_float(s)


@app.get("/stock/{symbol}")
def get_stock(symbol: str):
    symbol = symbol.strip().upper()
    if not symbol.replace("-", "").replace("&", "").isalnum() or len(symbol) > 20:
        raise HTTPException(status_code=400, detail="Invalid symbol")

    try:
        # Fetch fundamentals from Screener.in
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        r = requests.get(f"https://www.screener.in/company/{symbol}/consolidated/", headers=headers, timeout=15)
        
        # If consolidated fails or doesn't exist, try standalone
        if r.status_code == 404 or "Looks like the page you are looking for does not exist" in r.text:
            r = requests.get(f"https://www.screener.in/company/{symbol}/", headers=headers, timeout=15)
            
        if r.status_code != 200:
            raise HTTPException(status_code=404, detail="Symbol not found")
            
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # ── Company Name ──
        name_elem = soup.find('h1', class_='margin-0')
        name = name_elem.text.strip() if name_elem else symbol
        
        # ── Top Ratios ──
        ratios = {}
        ratio_div = soup.find('div', class_='company-ratios')
        week_high = 0
        week_low = 0
        if ratio_div:
            for li in ratio_div.find_all('li'):
                try:
                    k = li.find('span', class_='name').text.strip()
                    numbers = li.find_all('span', class_='number')
                    if k == "High / Low" and len(numbers) >= 2:
                        week_high = safe_float(numbers[0].text.strip().replace(',', ''))
                        week_low = safe_float(numbers[1].text.strip().replace(',', ''))
                    elif numbers:
                        v_text = numbers[0].text.strip().replace(',', '')
                        ratios[k] = safe_float(v_text)
                except:
                    pass

        price = ratios.get("Current Price", 0)
        mc = ratios.get("Market Cap", 0)
        pe = ratios.get("Stock P/E", 0)
        bv = ratios.get("Book Value", 0)
        div_yield = ratios.get("Dividend Yield", 0)
        roce = ratios.get("ROCE", 0)
        roe = ratios.get("ROE", 0)
        face_value = ratios.get("Face Value", 1)
        
        # ── EPS ──
        eps = 0
        if pe > 0 and price > 0:
            eps = safe_round(price / pe, 2)
            
        # ── P/B Ratio ──
        pb_ratio = safe_round(price / bv, 2) if bv > 0 else 0
            
        # ── Graham Number ──
        graham = 0
        if eps > 0 and bv > 0:
            graham = safe_round(math.sqrt(22.5 * eps * bv))

        # ── Extra data from Yahoo APIs (sector, forward PE, margins etc) ──
        sector = ""
        industry = ""
        forward_pe = 0
        peg_ratio = 0
        ev_ebitda = 0
        ps_ratio = 0
        operating_margin = 0
        gross_margin = 0
        current_ratio = 0
        revenue_per_share = 0
        
        # Method 1: Yahoo Search API for sector/industry (this works on Render)
        try:
            search_url = f"https://query2.finance.yahoo.com/v1/finance/search?q={symbol}.NS&quotesCount=1&newsCount=0"
            sr = requests.get(search_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
            if sr.status_code == 200:
                sq = sr.json().get("quotes", [])
                if sq:
                    sector = sq[0].get("sectorDisp", "") or sq[0].get("sector", "")
                    industry = sq[0].get("industryDisp", "") or sq[0].get("industry", "")
        except:
            pass
        
        # Method 2: yahooquery for financial metrics (wrapped in try/except)
        try:
            yqt = YQTicker(f"{symbol}.NS")
            
            kstats = yqt.key_stats.get(f"{symbol}.NS", {})
            if isinstance(kstats, dict):
                forward_pe = safe_round(safe_float(kstats.get("forwardPE", 0)))
                peg_ratio = safe_round(safe_float(kstats.get("pegRatio", 0)))
                ev_ebitda = safe_round(safe_float(kstats.get("enterpriseToEbitda", 0)))
                ps_ratio = safe_round(safe_float(kstats.get("priceToSalesTrailing12Months", 0)))
            
            fdata = yqt.financial_data.get(f"{symbol}.NS", {})
            if isinstance(fdata, dict):
                operating_margin = safe_round(safe_float(fdata.get("operatingMargins", 0)) * 100, 2)
                gross_margin = safe_round(safe_float(fdata.get("grossMargins", 0)) * 100, 2)
                current_ratio = safe_round(safe_float(fdata.get("currentRatio", 0)))
                revenue_per_share = safe_round(safe_float(fdata.get("revenuePerShare", 0)))
                
            # Also try to get sector from profile if search didn't work
            if not sector:
                profile = yqt.asset_profile.get(f"{symbol}.NS", {})
                if isinstance(profile, dict):
                    sector = profile.get("sector", "")
                    industry = profile.get("industry", "")
        except Exception as e:
            logger.warning(f"[{symbol}] yahooquery extras failed: {e}")

        # ── Shareholding Pattern ──
        promoter_holding = 0
        fii_holding = 0
        dii_holding = 0
        public_holding = 0
        sh_headers, sh_rows = _parse_screener_table('shareholding', soup)
        for row in sh_rows:
            if not row:
                continue
            label = row[0].lower().replace(' ', '')
            # Take the LAST column (most recent quarter)
            val = _clean_num(row[-1]) if len(row) > 1 else 0
            if 'promoter' in label:
                promoter_holding = val
            elif 'fii' in label or 'foreign' in label:
                fii_holding = val
            elif 'dii' in label or 'domestic' in label:
                dii_holding = val
            elif 'public' in label:
                public_holding = val
        
        # ── Quarterly Results ──
        quarterly_financials = []
        qr_headers, qr_rows = _parse_screener_table('quarters', soup)
        if qr_headers and qr_rows:
            # Find Revenue and Net Profit rows
            rev_row = None
            prof_row = None
            for row in qr_rows:
                if not row:
                    continue
                label = row[0].lower().replace(' ', '')
                if 'revenue' in label or 'sales' in label:
                    rev_row = row
                if 'netprofit' in label or 'profit+' in label:
                    prof_row = row
            
            # If no explicit net profit, look for last numeric row
            if not prof_row:
                for row in qr_rows:
                    if row and 'netprofit' in row[0].lower().replace(' ', ''):
                        prof_row = row
                        break
            
            # Use column headers (skip first empty header)
            for i, qtr in enumerate(qr_headers[1:], 1):
                if not qtr:
                    continue
                rev = _clean_num(rev_row[i]) if rev_row and i < len(rev_row) else 0
                prof = _clean_num(prof_row[i]) if prof_row and i < len(prof_row) else 0
                quarterly_financials.append({
                    "quarter": qtr,
                    "revenue": rev,
                    "profit": prof
                })
            # Reverse so oldest first (frontend reverses again)
            quarterly_financials = quarterly_financials[:8]
        
        # ── Annual Profit & Loss ──
        annual_financials = []
        pl_headers, pl_rows = _parse_screener_table('profit-loss', soup)
        if pl_headers and pl_rows:
            rev_row = None
            prof_row = None
            for row in pl_rows:
                if not row:
                    continue
                label = row[0].lower().replace(' ', '')
                if 'revenue' in label or 'sales' in label:
                    rev_row = row
                if 'netprofit' in label:
                    prof_row = row
            
            for i, yr in enumerate(pl_headers[1:], 1):
                if not yr:
                    continue
                rev = _clean_num(rev_row[i]) if rev_row and i < len(rev_row) else 0
                prof = _clean_num(prof_row[i]) if prof_row and i < len(prof_row) else 0
                annual_financials.append({
                    "year": yr.replace("Mar ", ""),
                    "revenue": rev,
                    "profit": prof
                })
            annual_financials = annual_financials[-6:]  # Last 6 years
        
        # ── Cash Flow ──
        cashflow_annual = []
        cf_headers, cf_rows = _parse_screener_table('cash-flow', soup)
        if cf_headers and cf_rows:
            ocf_row = None
            icf_row = None
            fcf_row = None
            for row in cf_rows:
                if not row:
                    continue
                label = row[0].lower().replace(' ', '')
                if 'operating' in label or 'cashfromoperating' in label:
                    ocf_row = row
                elif 'investing' in label:
                    icf_row = row
                elif 'freecash' in label:
                    fcf_row = row
            
            for i, yr in enumerate(cf_headers[1:], 1):
                if not yr:
                    continue
                ocf = _clean_num(ocf_row[i]) if ocf_row and i < len(ocf_row) else 0
                capex = abs(_clean_num(icf_row[i])) if icf_row and i < len(icf_row) else 0
                fcf = _clean_num(fcf_row[i]) if fcf_row and i < len(fcf_row) else 0
                cashflow_annual.append({
                    "year": yr.replace("Mar ", ""),
                    "operating_cf": ocf,
                    "capex": capex,
                    "free_cf": fcf
                })
            cashflow_annual = cashflow_annual[-6:]
        
        # ── Balance Sheet (latest) ──
        balance = {}
        bs_headers, bs_rows = _parse_screener_table('balance-sheet', soup)
        if bs_rows:
            for row in bs_rows:
                if not row:
                    continue
                label = row[0].lower().replace(' ', '')
                val = _clean_num(row[-1]) if len(row) > 1 else 0
                if 'totalassets' in label:
                    balance['total_assets'] = val
                elif 'totalliabilities' in label:
                    balance['total_liabilities'] = val
                elif 'reserves' in label:
                    balance['reserves'] = val
                elif 'borrowing' in label:
                    balance['total_debt'] = balance.get('total_debt', 0) + val
                elif 'investment' in label:
                    balance['investments'] = val
            # Don't count deposits as debt (banks)
            balance.setdefault('cash', 0)
            balance.setdefault('total_debt', 0)

        # ── EPS Quarters (calculate from Net Profit / shares) ──
        eps_quarters = []
        if qr_headers and qr_rows:
            prof_row_eps = None
            for row in qr_rows:
                if row and 'netprofit' in row[0].lower().replace(' ', ''):
                    prof_row_eps = row
                    break
            # Also try "EPS in Rs" row if it exists
            eps_row_direct = None
            for row in qr_rows:
                if row and 'eps' in row[0].lower():
                    eps_row_direct = row
                    break
            
            if eps_row_direct:
                for i, qtr in enumerate(qr_headers[1:], 1):
                    if not qtr or i >= len(eps_row_direct):
                        continue
                    eps_val = _clean_num(eps_row_direct[i])
                    eps_quarters.append({"quarter": qtr, "eps": safe_round(eps_val, 2)})
            elif prof_row_eps and pe > 0 and price > 0:
                # Estimate shares outstanding from Market Cap
                shares = (mc * 1e7) / price if price > 0 else 0
                if shares > 0:
                    for i, qtr in enumerate(qr_headers[1:], 1):
                        if not qtr or i >= len(prof_row_eps):
                            continue
                        ni = _clean_num(prof_row_eps[i]) * 1e7  # Convert crore to absolute
                        qeps = safe_round(ni / shares, 2)
                        eps_quarters.append({"quarter": qtr, "eps": qeps})
            eps_quarters = eps_quarters[:8]
        
        # ── Price History (Yahoo v8 chart API — usually not blocked) ──
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

        # ── Profit Margin (Net Profit / Revenue from latest annual) ──
        profit_margin = 0
        operating_margin = 0
        if annual_financials:
            latest = annual_financials[-1]
            if latest["revenue"] > 0 and latest["profit"] != 0:
                profit_margin = safe_round((latest["profit"] / latest["revenue"]) * 100, 2)

        # ── Revenue / Earnings Growth YoY ──
        revenue_growth = 0
        earnings_growth = 0
        if len(annual_financials) >= 2:
            prev = annual_financials[-2]
            curr = annual_financials[-1]
            if prev["revenue"] > 0:
                revenue_growth = safe_round(((curr["revenue"] - prev["revenue"]) / prev["revenue"]) * 100, 2)
            if prev["profit"] != 0:
                earnings_growth = safe_round(((curr["profit"] - prev["profit"]) / abs(prev["profit"])) * 100, 2)

        # ── Debt to Equity ──
        debt_equity = 0
        if bs_rows:
            total_debt = balance.get('total_debt', 0)
            equity = 0
            for row in bs_rows:
                if row and 'reserves' in row[0].lower():
                    equity = _clean_num(row[-1])
                    break
            if equity > 0:
                debt_equity = safe_round(total_debt / equity * 100, 2)

        # ── Forward PE Fair Value ──
        pe_method = safe_round(eps * forward_pe) if eps and forward_pe else 0

        return {
            "symbol":   symbol,
            "name":     name,
            "sector":   sector,
            "industry": industry,

            # Pricing
            "price":      price,
            "week_high":  week_high,
            "week_low":   week_low,
            "market_cap": mc * 1e7 if mc > 0 else 0,

            # Valuation
            "pe":         safe_round(pe),
            "forward_pe": forward_pe,
            "pb_ratio":   pb_ratio,
            "ps_ratio":   ps_ratio,
            "peg_ratio":  peg_ratio,
            "ev_ebitda":  ev_ebitda,

            # Per Share
            "eps":               safe_round(eps),
            "book_value":        safe_round(bv),
            "revenue_per_share": revenue_per_share,

            # Profitability
            "roe":              roe,
            "roce":             roce,
            "profit_margin":    profit_margin,
            "operating_margin": operating_margin,
            "gross_margin":     gross_margin,

            # Leverage & Liquidity
            "debt_equity":   debt_equity,
            "current_ratio": current_ratio,

            # Yield & Growth
            "dividend_yield":  div_yield / 100 if div_yield else 0,
            "revenue_growth":  revenue_growth,
            "earnings_growth": earnings_growth,

            # Holdings
            "promoter_holding": promoter_holding,
            "fii_holding":      fii_holding,

            # Fair Value
            "fair_value": {
                "graham":    graham,
                "pe_method": pe_method
            },

            # Financials
            "quarterly_financials": quarterly_financials,
            "annual_financials":    annual_financials,
            "cashflow_quarterly":   [],
            "cashflow_annual":      cashflow_annual,
            "eps_quarters":         eps_quarters,

            # Balance Sheet
            "balance": balance,

            # Price History (1Y daily)
            "price_history": price_history,

            # Analyst
            "analyst":     {"strong_buy":0, "buy":0, "hold":0, "sell":0, "strong_sell":0, "total":0},
            "top_holders": [],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[{symbol}] error: {e}")
        raise HTTPException(status_code=502, detail="Could not reach data source")

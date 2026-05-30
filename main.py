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

def _fetch_yahoo_data_with_crumb(symbol):
    """Custom scraper to fetch Yahoo Finance data bypassing yfinance/yahooquery blocks"""
    data = {
        "forward_pe": 0, "peg_ratio": 0, "ev_ebitda": 0, "ps_ratio": 0,
        "operating_margin": 0, "gross_margin": 0, "current_ratio": 0, "revenue_per_share": 0,
        "analyst": {"strong_buy":0, "buy":0, "hold":0, "sell":0, "strong_sell":0, "total":0},
        "top_holders": []
    }
    try:
        s = requests.Session()
        s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"})
        
        # 1. Get cookies
        s.get('https://fc.yahoo.com', timeout=5)
        # 2. Get crumb
        crumb = s.get('https://query1.finance.yahoo.com/v1/test/getcrumb', timeout=5).text
        if not crumb or '<html>' in crumb:
            return data
            
        # 3. Fetch data
        modules = "institutionOwnership,fundOwnership,recommendationTrend,defaultKeyStatistics,financialData"
        url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}.NS?modules={modules}&crumb={crumb}"
        r = s.get(url, timeout=5)
        
        if r.status_code == 200:
            res = r.json().get('quoteSummary', {}).get('result', [])
            if res:
                res = res[0]
                
                # Financial Data
                fd = res.get('financialData', {})
                data["operating_margin"] = safe_round(safe_float(fd.get('operatingMargins', {}).get('raw', 0)) * 100, 2)
                data["gross_margin"] = safe_round(safe_float(fd.get('grossMargins', {}).get('raw', 0)) * 100, 2)
                data["current_ratio"] = safe_round(safe_float(fd.get('currentRatio', {}).get('raw', 0)))
                data["revenue_per_share"] = safe_round(safe_float(fd.get('revenuePerShare', {}).get('raw', 0)))
                
                # Key Stats
                ks = res.get('defaultKeyStatistics', {})
                data["forward_pe"] = safe_round(safe_float(ks.get('forwardPE', {}).get('raw', 0)))
                data["peg_ratio"] = safe_round(safe_float(ks.get('pegRatio', {}).get('raw', 0)))
                data["ev_ebitda"] = safe_round(safe_float(ks.get('enterpriseToEbitda', {}).get('raw', 0)))
                data["ps_ratio"] = safe_round(safe_float(ks.get('priceToSalesTrailing12Months', {}).get('raw', 0)))
                
                # Analyst Recs
                trends = res.get('recommendationTrend', {}).get('trend', [])
                if trends:
                    t = trends[0]
                    data["analyst"] = {
                        "strong_buy": t.get('strongBuy', 0),
                        "buy": t.get('buy', 0),
                        "hold": t.get('hold', 0),
                        "sell": t.get('sell', 0),
                        "strong_sell": t.get('strongSell', 0),
                        "total": t.get('strongBuy', 0) + t.get('buy', 0) + t.get('hold', 0) + t.get('sell', 0) + t.get('strongSell', 0)
                    }
                    
                # Holders
                owners = res.get('institutionOwnership', {}).get('ownershipList', [])
                if not owners:
                    owners = res.get('fundOwnership', {}).get('ownershipList', [])
                
                for o in owners[:5]:
                    data["top_holders"].append({
                        "name": o.get('organization', ''),
                        "shares": o.get('position', {}).get('raw', 0),
                        "value": o.get('value', {}).get('raw', 0),
                        "pct": safe_round(safe_float(o.get('pctHeld', {}).get('raw', 0)) * 100, 2)
                    })
    except Exception as e:
        logger.warning(f"Custom Yahoo fetch failed for {symbol}: {e}")
        
    return data

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

        # ── Extra data from Yahoo APIs (sector, industry, plus custom scraper) ──
        sector = ""
        industry = ""
        
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
            
        # Method 2: Custom crumb scraper for the rest
        y_data = _fetch_yahoo_data_with_crumb(symbol)
        forward_pe = y_data["forward_pe"]
        peg_ratio = y_data["peg_ratio"]
        ev_ebitda = y_data["ev_ebitda"]
        ps_ratio = y_data["ps_ratio"]
        operating_margin = y_data["operating_margin"]
        gross_margin = y_data["gross_margin"]
        current_ratio = y_data["current_ratio"]
        revenue_per_share = y_data["revenue_per_share"]
        analyst_recs = y_data["analyst"]
        top_holders = y_data["top_holders"]

        # ── Shareholding Pattern & Top Holders ──
        promoter_holding = 0
        fii_holding = 0
        dii_holding = 0
        public_holding = 0
        if not top_holders:
            top_holders = []
            
        try:
        # Try both possible section IDs for shareholding
            sh_headers, sh_rows = _parse_screener_table('shareholding', soup)
            if not sh_rows:
                sh_headers, sh_rows = _parse_screener_table('shareholding-summary', soup)
            main_categories = ['promoters', 'flls', 'fii', 'foreign', 'dlls', 'dii', 'domestic', 'public', 'government', 'no.ofshareholders']
            for row in sh_rows:
                if not row:
                    continue
                raw_label = row[0]
                label = raw_label.lower().replace(' ', '').replace('+', '')
                # Take the latest non-zero column (right-to-left scan)
                val = 0
                if len(row) > 1:
                    for col in reversed(row[1:]):
                        v = _clean_num(col)
                        if v > 0:
                            val = v
                            break
                
                if 'promoter' in label:
                    promoter_holding = val
                elif 'fii' in label or 'foreign' in label or 'flls' in label:
                    fii_holding = val
                elif 'dii' in label or 'domestic' in label or 'dlls' in label:
                    dii_holding = val
                elif 'public' in label:
                    public_holding = val
                elif label not in main_categories and val > 0.1:
                    # It's a specific top holder (Screener hidden row)
                    top_holders.append({
                        "name": raw_label.replace('+', '').strip(),
                        "shares": 0,
                        "value": 0,
                        "pct": val
                    })
            
            # ── Screener Sub-holders API Fallback (AJAX) ──
            if not top_holders:
                # Try multiple attribute names Screener uses for company ID
                cid = None
                for attr in ['data-company-id', 'data-id']:
                    elem = soup.find(True, {attr: True})
                    if elem:
                        cid = elem[attr]
                        break
                # Also try the main company div
                if not cid:
                    company_div = soup.find('div', class_='company-info')
                    if company_div and company_div.get('data-company-id'):
                        cid = company_div['data-company-id']
                
                if cid:
                    for q_type in ["Promoters", "FIIs", "DIIs", "Institutions"]:
                        try:
                            sub_r = requests.get(
                                f"https://www.screener.in/api/company/{cid}/sub-shareholders/?q={q_type}",
                                headers=headers, timeout=5
                            )
                            if sub_r.status_code == 200 and sub_r.text.strip():
                                sub_soup = BeautifulSoup(sub_r.text, 'html.parser')
                                for tr in sub_soup.find_all('tr'):
                                    tds = tr.find_all('td')
                                    if len(tds) >= 2:
                                        h_name = tds[0].text.strip()
                                        # Right-to-left scan for latest non-zero value
                                        sub_val = 0
                                        for td in reversed(tds[1:]):
                                            v = _clean_num(td.text)
                                            if v > 0:
                                                sub_val = v
                                                break
                                        if sub_val > 0.1 and "others" not in h_name.lower() and "total" not in h_name.lower():
                                            top_holders.append({
                                                "name": h_name.replace('+', '').strip(),
                                                "shares": 0,
                                                "value": 0,
                                                "pct": sub_val
                                            })
                        except Exception as e:
                            logger.warning(f"[{symbol}] Sub-shareholders {q_type} failed: {e}")

            # Sort and limit top holders
            if top_holders and len(top_holders) > 0 and "pct" in top_holders[0]:
                top_holders = sorted(top_holders, key=lambda x: x["pct"], reverse=True)[:5]
        except Exception as e:
            logger.warning(f"[{symbol}] Shareholding parsing error: {e}")
        
        # ── Quarterly Results ──
        quarterly_financials = []
        try:
            qr_headers, qr_rows = _parse_screener_table('quarters', soup)
            if qr_headers and qr_rows:
                rev_row = None
                prof_row = None
                for row in qr_rows:
                    if not row: continue
                    label = row[0].lower().replace(' ', '')
                    if 'revenue' in label or 'sales' in label or 'interest' in label or 'financing' in label:
                        if not rev_row: rev_row = row
                    if 'netprofit' in label or 'profit+' in label:
                        prof_row = row
                
                if not prof_row:
                    for row in qr_rows:
                        if row and 'netprofit' in row[0].lower().replace(' ', ''):
                            prof_row = row
                            break
                
                for i, qtr in enumerate(qr_headers[1:], 1):
                    if not qtr: continue
                    rev = _clean_num(rev_row[i]) if rev_row and i < len(rev_row) else 0
                    prof = _clean_num(prof_row[i]) if prof_row and i < len(prof_row) else 0
                    quarterly_financials.append({"quarter": qtr, "revenue": rev, "profit": prof})
                quarterly_financials = quarterly_financials[:8]
        except Exception as e:
            logger.warning(f"[{symbol}] Quarterly parsing error: {e}")
        
        # ── Annual Profit & Loss ──
        annual_financials = []
        try:
            pl_headers, pl_rows = _parse_screener_table('profit-loss', soup)
            if pl_headers and pl_rows:
                rev_row = None
                prof_row = None
                for row in pl_rows:
                    if not row: continue
                    label = row[0].lower().replace(' ', '')
                    if 'revenue' in label or 'sales' in label or 'interest' in label or 'financing' in label:
                        if not rev_row: rev_row = row
                    if 'netprofit' in label:
                        prof_row = row
                
                for i, yr in enumerate(pl_headers[1:], 1):
                    if not yr: continue
                    rev = _clean_num(rev_row[i]) if rev_row and i < len(rev_row) else 0
                    prof = _clean_num(prof_row[i]) if prof_row and i < len(prof_row) else 0
                    annual_financials.append({"year": yr.replace("Mar ", ""), "revenue": rev, "profit": prof})
                annual_financials = annual_financials[-6:]
        except Exception as e:
            logger.warning(f"[{symbol}] Annual P&L parsing error: {e}")
        
        # ── Cash Flow ──
        cashflow_annual = []
        try:
            cf_headers, cf_rows = _parse_screener_table('cash-flow', soup)
            if cf_headers and cf_rows:
                ocf_row = icf_row = fcf_row = None
                for row in cf_rows:
                    if not row: continue
                    label = row[0].lower().replace(' ', '')
                    if 'operating' in label or 'cashfromoperating' in label: ocf_row = row
                    elif 'investing' in label: icf_row = row
                    elif 'freecash' in label: fcf_row = row
                
                for i, yr in enumerate(cf_headers[1:], 1):
                    if not yr: continue
                    ocf = _clean_num(ocf_row[i]) if ocf_row and i < len(ocf_row) else 0
                    capex = abs(_clean_num(icf_row[i])) if icf_row and i < len(icf_row) else 0
                    fcf = _clean_num(fcf_row[i]) if fcf_row and i < len(fcf_row) else 0
                    cashflow_annual.append({"year": yr.replace("Mar ", ""), "operating_cf": ocf, "capex": capex, "free_cf": fcf})
                cashflow_annual = cashflow_annual[-6:]
        except Exception as e:
            logger.warning(f"[{symbol}] Cash flow parsing error: {e}")
        
        # ── Balance Sheet (latest) ──
        balance = {'cash': 0, 'total_debt': 0}
        bs_rows = []
        try:
            bs_headers, bs_rows = _parse_screener_table('balance-sheet', soup)
            if bs_rows:
                for row in bs_rows:
                    if not row: continue
                    label = row[0].lower().replace(' ', '').replace('+', '')
                    val = _clean_num(row[-1]) if len(row) > 1 else 0
                    if 'totalassets' in label: balance['total_assets'] = val
                    elif 'totalliabilities' in label: balance['total_liabilities'] = val
                    elif 'reserves' in label: balance['reserves'] = val
                    elif 'borrowing' in label: balance['total_debt'] = balance.get('total_debt', 0) + val
                    elif 'investment' in label: balance['investments'] = val
                    elif 'cash' in label: balance['cash'] = balance.get('cash', 0) + val
                        
            # Estimate cash from cash flow if missing
            if balance.get('cash', 0) == 0 and len(cashflow_annual) > 0:
                balance['cash'] = cashflow_annual[-1].get("net_cf", 0) * 10
        except Exception as e:
            logger.warning(f"[{symbol}] Balance sheet parsing error: {e}")

        # ── EPS Quarters ──
        eps_quarters = []
        try:
            qr_headers, qr_rows = _parse_screener_table('quarters', soup)
            if qr_headers and qr_rows:
                prof_row_eps = eps_row_direct = None
                for row in qr_rows:
                    if row and 'netprofit' in row[0].lower().replace(' ', ''): prof_row_eps = row
                    if row and 'eps' in row[0].lower(): eps_row_direct = row
                
                if eps_row_direct:
                    for i, qtr in enumerate(qr_headers[1:], 1):
                        if not qtr or i >= len(eps_row_direct): continue
                        eps_val = _clean_num(eps_row_direct[i])
                        eps_quarters.append({"quarter": qtr, "eps": safe_round(eps_val, 2)})
                elif prof_row_eps and pe > 0 and price > 0:
                    shares = (mc * 1e7) / price if price > 0 else 0
                    if shares > 0:
                        for i, qtr in enumerate(qr_headers[1:], 1):
                            if not qtr or i >= len(prof_row_eps): continue
                            ni = _clean_num(prof_row_eps[i]) * 1e7
                            qeps = safe_round(ni / shares, 2)
                            eps_quarters.append({"quarter": qtr, "eps": qeps})
                eps_quarters = eps_quarters[:8]
        except Exception as e:
            logger.warning(f"[{symbol}] EPS Quarters parsing error: {e}")
        
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

        # ── Manual calculation fallback for missing fields ──
        pe_method = 0
        try:
            if len(annual_financials) > 0:
                latest_annual = annual_financials[-1]
                latest_rev = latest_annual["revenue"] * 10000000 # Convert to absolute
                latest_profit = latest_annual["profit"] * 10000000
                
                if latest_rev > 0:
                    if ps_ratio == 0:
                        ps_ratio = safe_round((mc * 10000000) / latest_rev, 2)
                    
                    if revenue_per_share == 0 and price > 0:
                        shares_out = (mc * 10000000) / price
                        if shares_out > 0:
                            revenue_per_share = safe_round(latest_rev / shares_out, 2)
                            
                # EV / EBITDA calculation
                if ev_ebitda == 0 and latest_profit > 0:
                    ev = (mc * 10000000) + balance.get('total_debt', 0)*10000000 - balance.get('cash', 0)*10000000
                    ebitda = latest_profit * 1.4 # Rough proxy for EBITDA from Net Profit
                    if ebitda != 0:
                        ev_ebitda = safe_round(ev / ebitda, 2)
            
            if peg_ratio == 0 and earnings_growth > 0:
                peg_ratio = safe_round(pe / earnings_growth, 2)
                
            if operating_margin == 0 and profit_margin > 0:
                operating_margin = safe_round(profit_margin * 1.3, 2) # Rough estimate

            # ── TradingView Analyst Recommendations Fallback ──
            if analyst_recs.get("total", 0) == 0:
                try:
                    tv_url = "https://scanner.tradingview.com/india/scan"
                    payload = {"symbols": {"tickers": [f"NSE:{symbol}", f"BSE:{symbol}"]}, "columns": ["Recommend.All"]}
                    tv_res = requests.post(tv_url, json=payload, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
                    if tv_res.status_code == 200:
                        tv_data = tv_res.json().get("data", [])
                        if tv_data:
                            rec_score = safe_float(tv_data[0].get("d", [0])[0])
                            # Map -1 to +1 score to count out of 10
                            if rec_score > 0.5: analyst_recs["strong_buy"] = 10
                            elif rec_score > 0.1: analyst_recs["buy"] = 10
                            elif rec_score > -0.1: analyst_recs["hold"] = 10
                            elif rec_score > -0.5: analyst_recs["sell"] = 10
                            else: analyst_recs["strong_sell"] = 10
                            analyst_recs["total"] = 10
                except:
                    pass

            # ── Forward PE Fair Value ──
            if forward_pe == 0:
                # Estimate forward PE based on current PE and YoY growth
                forward_pe = safe_round(pe * (1 - min(earnings_growth, 50)/100), 2) if earnings_growth > 0 else pe
            
            pe_method = safe_round(eps * forward_pe) if eps and forward_pe else 0
        except Exception as e:
            logger.warning(f"[{symbol}] Fallback calculation error: {e}")

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
            "analyst":     analyst_recs,
            "top_holders": top_holders,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[{symbol}] error: {e}")
        raise HTTPException(status_code=502, detail="Could not reach data source")

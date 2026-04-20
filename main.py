from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import math
import requests
from bs4 import BeautifulSoup

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def home():
    return {"status": "working"}

def scrape_screener(symbol):
    try:
        url = f"https://www.screener.in/company/{symbol}/consolidated/"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")

        # Quarterly Results
        quarters = []
        table = soup.find("section", {"id": "quarters"})
        if table:
            headers_row = table.find("thead").find_all("th")
            qtrs = [th.text.strip() for th in headers_row[1:]]
            rows = table.find("tbody").find_all("tr")
            data = {}
            for row in rows:
                cols = row.find_all("td")
                if cols:
                    key = cols[0].text.strip()
                    vals = [c.text.strip().replace(",","") for c in cols[1:]]
                    data[key] = vals
            for i, q in enumerate(qtrs[:8]):
                quarters.append({
                    "quarter": q,
                    "revenue": data.get("Sales", [None]*8)[i],
                    "profit": data.get("Net Profit", [None]*8)[i],
                    "eps": data.get("EPS in Rs", [None]*8)[i],
                })

        # Annual Data
        annual = []
        atbl = soup.find("section", {"id": "profit-loss"})
        if atbl:
            ah = atbl.find("thead").find_all("th")
            years = [th.text.strip() for th in ah[1:]]
            rows = atbl.find("tbody").find_all("tr")
            adata = {}
            for row in rows:
                cols = row.find_all("td")
                if cols:
                    key = cols[0].text.strip()
                    vals = [c.text.strip().replace(",","") for c in cols[1:]]
                    adata[key] = vals
            for i, y in enumerate(years[:6]):
                annual.append({
                    "year": y,
                    "revenue": adata.get("Sales", [None]*6)[i],
                    "profit": adata.get("Net Profit", [None]*6)[i],
                })

        return {"quarters": quarters, "annual": annual}
    except:
        return {"quarters": [], "annual": []}

@app.get("/stock/{symbol}")
def get_stock(symbol: str):
    ticker = yf.Ticker(f"{symbol}.NS")
    info = ticker.info

    price = info.get("currentPrice", 0)
    eps = info.get("trailingEps", 0)
    book_value = info.get("bookValue", 0)
    pe = info.get("trailingPE", 0)
    industry_pe = info.get("forwardPE", 0)

    graham = 0
    if eps and book_value and eps > 0 and book_value > 0:
        graham = round(math.sqrt(22.5 * eps * book_value), 2)
    pe_fair = round(eps * industry_pe, 2) if (eps and industry_pe) else 0

    screener = scrape_screener(symbol)

    return {
        "symbol": symbol,
        "name": info.get("longName", ""),
        "sector": info.get("sector", ""),
        "industry": info.get("industry", ""),
        "price": price,
        "pe": pe,
        "eps": eps,
        "book_value": book_value,
        "roe": info.get("returnOnEquity", 0),
        "roce": info.get("returnOnAssets", 0),
        "debt_equity": info.get("debtToEquity", 0),
        "market_cap": info.get("marketCap", 0),
        "week_high": info.get("fiftyTwoWeekHigh", 0),
        "week_low": info.get("fiftyTwoWeekLow", 0),
        "promoter_holding": info.get("heldPercentInsiders", 0),
        "fii_holding": info.get("heldPercentInstitutions", 0),
        "dividend_yield": info.get("dividendYield", 0),
        "pb_ratio": info.get("priceToBook", 0),
        "fair_value": {
            "graham": graham,
            "pe_method": pe_fair
        },
        "quarters": screener["quarters"],
        "annual": screener["annual"]
    }

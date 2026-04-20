from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import math

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

    return {
        "symbol": symbol,
        "name": info.get("longName", ""),
        "sector": info.get("sector", ""),
        "price": price,
        "pe": pe,
        "eps": eps,
        "book_value": book_value,
        "roe": info.get("returnOnEquity", 0),
        "debt_equity": info.get("debtToEquity", 0),
        "market_cap": info.get("marketCap", 0),
        "week_high": info.get("fiftyTwoWeekHigh", 0),
        "week_low": info.get("fiftyTwoWeekLow", 0),
        "promoter_holding": info.get("heldPercentInsiders", 0),
        "fair_value": {
            "graham": graham,
            "pe_method": pe_fair
        }
    }

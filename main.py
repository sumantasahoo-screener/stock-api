from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import math

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/")
def home():
    return {"status": "working"}

@app.get("/stock/{symbol}")
def get_stock(symbol: str):
    ticker = yf.Ticker(f"{symbol}.NS")
    info = ticker.info

    price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
    eps = info.get("trailingEps", 0)
    book_value = info.get("bookValue", 0)
    pe = info.get("trailingPE", 0)
    fwd_pe = info.get("forwardPE", 0)

    graham = 0
    if eps and book_value and eps > 0 and book_value > 0:
        graham = round(math.sqrt(22.5 * eps * book_value), 2)
    pe_fair = round(eps * fwd_pe, 2) if (eps and fwd_pe) else 0

    # Quarterly EPS from earnings history
    quarters = []
    try:
        eq = ticker.quarterly_earnings
        if eq is not None and not eq.empty:
            for i, (idx, row) in enumerate(eq.iterrows()):
                if i >= 8: break
                quarters.append({
                    "quarter": str(idx),
                    "eps": round(float(row.get("Earnings", 0)), 2),
                    "revenue": round(float(row.get("Revenue", 0)) / 1e7, 2)
                })
    except:
        pass

    # Annual financials
    annual = []
    try:
        fin = ticker.financials
        if fin is not None and not fin.empty:
            for col in fin.columns[:6]:
                rev = fin.loc["Total Revenue", col] if "Total Revenue" in fin.index else 0
                prof = fin.loc["Net Income", col] if "Net Income" in fin.index else 0
                annual.append({
                    "year": str(col)[:4],
                    "revenue": round(float(rev) / 1e7, 2),
                    "profit": round(float(prof) / 1e7, 2)
                })
    except:
        pass

    # Quarterly financials
    qfin = []
    try:
        qf = ticker.quarterly_financials
        if qf is not None and not qf.empty:
            for col in qf.columns[:8]:
                rev = qf.loc["Total Revenue", col] if "Total Revenue" in qf.index else 0
                prof = qf.loc["Net Income", col] if "Net Income" in qf.index else 0
                qfin.append({
                    "quarter": str(col)[:7],
                    "revenue": round(float(rev) / 1e7, 2),
                    "profit": round(float(prof) / 1e7, 2)
                })
    except:
        pass

    return {
        "symbol": symbol,
        "name": info.get("longName", ""),
        "sector": info.get("sector", ""),
        "industry": info.get("industry", ""),
        "price": price,
        "pe": pe,
        "forward_pe": fwd_pe,
        "eps": eps,
        "book_value": book_value,
        "pb_ratio": info.get("priceToBook", 0),
        "roe": info.get("returnOnEquity", 0),
        "roce": info.get("returnOnAssets", 0),
        "debt_equity": info.get("debtToEquity", 0),
        "current_ratio": info.get("currentRatio", 0),
        "market_cap": info.get("marketCap", 0),
        "week_high": info.get("fiftyTwoWeekHigh", 0),
        "week_low": info.get("fiftyTwoWeekLow", 0),
        "promoter_holding": info.get("heldPercentInsiders", 0),
        "fii_holding": info.get("heldPercentInstitutions", 0),
        "dividend_yield": info.get("dividendYield", 0),
        "revenue_growth": info.get("revenueGrowth", 0),
        "earnings_growth": info.get("earningsGrowth", 0),
        "fair_value": {"graham": graham, "pe_method": pe_fair},
        "quarters": qfin,
        "annual": annual,
        "eps_quarters": quarters
    }

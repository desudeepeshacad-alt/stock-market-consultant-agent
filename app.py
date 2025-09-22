import pandas as pd
import yfinance as yf
from flask import Flask, render_template, request, jsonify
from collections import defaultdict

# --- Initialize Flask App ---
app = Flask(__name__)

# --- In-Memory Usage & Billing Tracker ---
# NOTE: In a real-world application, this would be a database.
usage_tracker = {
    "portfolios_analyzed": 0,
    "advice_generated": 0,
    "total_bill": 0.0
}
COST_PER_PORTFOLIO = 2.00
COST_PER_ADVICE = 0.25

# --- 1. Live Data Service (PathwayClient) ---
class PathwayClient:
    @staticmethod
    def _calculate_rsi(data: pd.Series, window: int = 14) -> int:
        if data.empty or len(data) < window + 1: return 50
        delta = data.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
        if loss.iloc[-1] == 0: return 100
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        final_rsi = rsi.iloc[-1]
        if pd.isna(final_rsi): return 50
        return int(final_rsi)

    def fetch_live_stock_data(self, tickers: list[str]) -> dict:
        print(f"\n[Pathway] Connecting to live market feed for: {tickers}...")
        live_data = {}
        try:
            session = yf.Ticker("MSFT").session
            ticker_data = yf.Tickers(tickers, session=session)
            history = yf.download(tickers, period="3mo", progress=False, session=session)
            for ticker_str in tickers:
                ticker = ticker_data.tickers[ticker_str]
                info = ticker.info
                if not info or 'currentPrice' not in info or info.get('currentPrice') is None:
                    print(f"[Pathway] WARNING: Could not fetch live info for {ticker_str}.")
                    continue
                try:
                    ticker_history = history[('Close', ticker_str)] if len(tickers) > 1 else history['Close']
                except KeyError:
                    print(f"[Pathway] WARNING: Could not fetch historical data for {ticker_str}.")
                    continue
                rsi = self._calculate_rsi(ticker_history)
                live_data[ticker_str] = {
                    "price": info.get('currentPrice', 0),
                    "change_percent": ((info.get('currentPrice', 0) - info.get('previousClose', 1)) / info.get('previousClose', 1)) * 100,
                    "sector": info.get('sector', 'N/A'),
                    "50d_ma": info.get('fiftyDayAverage', 0),
                    "200d_ma": info.get('twoHundredDayAverage', 0),
                    "rsi": rsi,
                    "volume": info.get('volume', 0),
                    "avg_vol": info.get('averageVolume', 0)
                }
            print("[Pathway] Live data received successfully.")
            return live_data
        except Exception as e:
            print(f"[Pathway] ERROR: Failed to fetch live data. Error: {e}")
            return {}

# --- 2. Upgraded Analysis Engine ---
class AnalysisEngine:
    def generate_advice(self, portfolio: list[dict], live_data: dict, risk_profile: str) -> list[str]:
        advice_list = []
        for stock in portfolio:
            ticker = stock["ticker"]
            if ticker not in live_data: continue
            
            data = live_data[ticker]
            pnl_percent = ((data["price"] - stock["avg_price"]) / stock["avg_price"]) * 100
            score = 0
            reasons = []

            if data.get("price", 0) < data.get("50d_ma", 0):
                score -= 2
                reasons.append("it's trading below its 50-Day trendline")
            if data.get("rsi", 100) > 70:
                score -= 1
                reasons.append("it's in the overbought zone (RSI > 70)")
            elif data.get("rsi", 0) < 30:
                score += 1
                reasons.append("it's in the oversold zone (RSI < 30)")
            if data.get("change_percent", 0) < -2.0 and data.get("volume", 0) > data.get("avg_vol", 0) * 1.5:
                score -= 2
                reasons.append("it's falling on high volume")
            elif data.get("change_percent", 0) < -2.0:
                score -= 1
                reasons.append("it's facing selling pressure today")

            advice, final_reason = self._get_final_advice(score, pnl_percent, risk_profile, reasons, data)
            
            status_icon = "🟢" if pnl_percent > 2 else "🔴" if pnl_percent < -2 else "🔵"
            advice_text = f"{status_icon} **{ticker}**\n"
            advice_text += f"   - Your P/L: {pnl_percent:.2f}%\n"
            advice_text += f"   - **ADVICE: {advice}**\n"
            advice_text += f"   - **Reason:** {final_reason}"
            advice_list.append(advice_text)
        return advice_list

    def _get_final_advice(self, score: int, pnl: float, risk: str, reasons: list[str], live_stock_data: dict) -> tuple[str, str]:
        reason_str = ", and ".join(reasons) if reasons else "the current indicators are neutral."

        if risk == "Conservative": score -= 1
        if risk == "Aggressive": score += 1
        
        is_healthy_long_term = live_stock_data.get('price', 0) > live_stock_data.get('200d_ma', 0)
        is_not_overbought = live_stock_data.get('rsi', 100) < 65

        if score >= 1 and is_healthy_long_term and is_not_overbought and pnl < 15:
            return "Consider buying more (Averaging)", "The stock shows positive short-term signals while being in a healthy long-term uptrend and not overbought."

        if score <= -3:
            return "Strongly consider selling", reason_str
        elif score <= -1:
            return "Consider reducing position", reason_str
        elif score >= 2 and pnl < 0:
            return "Consider holding for recovery", reason_str
        elif score >= 2:
            return "Hold for potential upside", reason_str
        else:
            return "Hold and Monitor", reason_str

    def analyse_diversification(self, portfolio: list[dict], live_data: dict) -> str:
        sector_values = defaultdict(float)
        total_value = 0
        for stock in portfolio:
            ticker = stock['ticker']
            if ticker in live_data:
                current_value = stock['quantity'] * live_data[ticker]['price']
                sector = live_data[ticker]['sector']
                sector_values[sector] += current_value
                total_value += current_value
        if total_value == 0: return "Could not calculate diversification due to missing data."
        highly_concentrated_sectors = []
        for sector, value in sector_values.items():
            percentage = (value / total_value) * 100
            if percentage > 40.0:
                highly_concentrated_sectors.append(f"**{sector}** ({percentage:.1f}%)")
        if highly_concentrated_sectors:
            return f"⚠️ **Diversification Warning:** Your portfolio is heavily concentrated in: {', '.join(highly_concentrated_sectors)}. Consider diversifying into other sectors to reduce risk."
        else:
            return "✅ **Good Diversification:** Your portfolio appears to be well-diversified across different sectors."

# --- Instantiate our core components ---
pathway = PathwayClient()
engine = AnalysisEngine()

# --- 3. Flask Routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyse', methods=['POST'])
def analyse_portfolio():
    try:
        data = request.get_json()
        portfolio_data = data.get('portfolio')
        if not portfolio_data:
            return jsonify({"error": "Portfolio data is missing."}), 400

        # Update Usage and Billing
        num_advice_items = len(portfolio_data)
        current_bill = COST_PER_PORTFOLIO + (num_advice_items * COST_PER_ADVICE)
        usage_tracker["portfolios_analyzed"] += 1
        usage_tracker["advice_generated"] += num_advice_items
        usage_tracker["total_bill"] += current_bill
        
        tickers_to_fetch = [stock['ticker'] for stock in portfolio_data]
        live_market_data = pathway.fetch_live_stock_data(tickers_to_fetch)
        if not live_market_data:
            return jsonify({"error": "Could not fetch live market data for the provided tickers."}), 500

        # Generate Analysis
        table_results, analysis_portfolio = [], []
        for stock in portfolio_data:
            ticker = stock['ticker']
            if ticker in live_market_data:
                live_info = live_market_data[ticker]
                investment = stock['quantity'] * stock['averagePrice']
                currentValue = stock['quantity'] * live_info['price']
                table_results.append({**stock, "investment": investment, "currentPrice": live_info['price'], "currentValue": currentValue, "pnl": currentValue - investment, "change_percent": live_info['change_percent']})
                analysis_portfolio.append({"ticker": ticker, "quantity": stock['quantity'], "avg_price": stock['averagePrice']})

        generated_advice = engine.generate_advice(analysis_portfolio, live_market_data, "Moderate")
        diversification_advice = engine.analyse_diversification(analysis_portfolio, live_market_data)
        
        return jsonify({
            "table_data": table_results,
            "advice": generated_advice,
            "diversification_advice": diversification_advice,
            "usage_stats": {
                "portfolios_analyzed": usage_tracker["portfolios_analyzed"],
                "total_bill": f'{usage_tracker["total_bill"]:.2f}'
            }
        })

    except Exception as e:
        print(f"An error occurred: {e}")
        return jsonify({"error": "An internal server error occurred."}), 500

# --- 4. Main Execution Block ---
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
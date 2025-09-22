import os
import requests
import pandas as pd
from flask import Flask, render_template, request, jsonify
from collections import defaultdict

# --- Initialize Flask App ---
app = Flask(__name__)

# --- In-Memory Usage & Billing Tracker ---
usage_tracker = {"portfolios_analyzed": 0, "advice_generated": 0, "total_bill": 0.0}
COST_PER_PORTFOLIO = 2.00
COST_PER_ADVICE = 0.25

# --- 1. MODIFIED Live Data Service (Now using Alpha Vantage) ---
class PathwayClient:
    def __init__(self):
        # IMPORTANT: Reads the API key from the environment variables you set on Render
        self.api_key = os.environ.get('ALPHA_VANTAGE_API_KEY')
        if not self.api_key:
            raise ValueError("ALPHA_VANTAGE_API_KEY environment variable not set.")
        self.base_url = 'https://www.alphavantage.co/query'

    def fetch_live_stock_data(self, tickers: list[str]) -> dict:
        print(f"\n[Pathway] Connecting to Alpha Vantage for: {tickers}...")
        live_data = {}
        
        # Alpha Vantage's free tier is limited, so we fetch one ticker at a time.
        for ticker_str in tickers:
            try:
                # API Call 1: Get the global quote (price, change, etc.)
                quote_params = {'function': 'GLOBAL_QUOTE', 'symbol': ticker_str, 'apikey': self.api_key}
                quote_response = requests.get(self.base_url, params=quote_params)
                quote_response.raise_for_status()
                quote_data = quote_response.json().get('Global Quote', {})

                if not quote_data:
                    print(f"[Pathway] WARNING: No quote data found for {ticker_str}. It might be an invalid ticker.")
                    continue

                # API Call 2: Get the company overview (for sector info)
                overview_params = {'function': 'OVERVIEW', 'symbol': ticker_str, 'apikey': self.api_key}
                overview_response = requests.get(self.base_url, params=overview_params)
                overview_response.raise_for_status()
                overview_data = overview_response.json()

                # Extract and format the data
                change_percent_str = quote_data.get('10. change percent', '0%').replace('%', '')
                
                live_data[ticker_str] = {
                    "price": float(quote_data.get('05. price', 0)),
                    "change_percent": float(change_percent_str),
                    "sector": overview_data.get('Sector', 'N/A'),
                }
                print(f"[Pathway] Successfully fetched data for {ticker_str}.")
            except requests.exceptions.RequestException as e:
                print(f"[Pathway] ERROR: Network or API error for {ticker_str}. Error: {e}")
            except (KeyError, ValueError) as e:
                print(f"[Pathway] ERROR: Could not parse data for {ticker_str}. It might be an invalid ticker or an API limit issue. Error: {e}")
        
        return live_data

# --- 2. SIMPLIFIED Analysis Engine ---
class AnalysisEngine:
    def generate_advice(self, portfolio: list[dict], live_data: dict, risk_profile: str) -> list[str]:
        advice_list = []
        for stock in portfolio:
            ticker = stock["ticker"]
            if ticker not in live_data: continue
            
            data = live_data[ticker]
            pnl_percent = ((data["price"] - stock["avg_price"]) / stock["avg_price"]) * 100
            
            # NOTE: Advice logic is simplified due to Alpha Vantage free tier limitations.
            # It no longer uses RSI or Moving Averages.
            advice, final_reason = self._get_final_advice(pnl_percent, data.get('change_percent', 0))
            
            status_icon = "🟢" if pnl_percent > 2 else "🔴" if pnl_percent < -2 else "🔵"
            advice_text = f"{status_icon} **{ticker}**\n"
            advice_text += f"   - Your P/L: {pnl_percent:.2f}%\n"
            advice_text += f"   - Day's Change: {data.get('change_percent', 0):.2f}%\n"
            advice_text += f"   - **ADVICE: {advice}**\n"
            advice_text += f"   - **Reason:** {final_reason}"
            advice_list.append(advice_text)
        return advice_list

    def _get_final_advice(self, pnl: float, change_percent: float) -> tuple[str, str]:
        if change_percent > 2.0 and pnl > 5.0:
            return "Hold for potential upside", "The stock is performing well today and you have a good profit."
        elif change_percent < -2.0 and pnl > 0:
            return "Consider taking some profit", "The stock is facing selling pressure today; locking in gains could be wise."
        elif change_percent < -2.0 and pnl < 0:
            return "Hold and Monitor", "The stock is down today; avoid selling in a panic."
        elif pnl < -15.0:
            return "Review Position", "Your position has a significant loss. Re-evaluate the investment."
        else:
            return "Hold and Monitor", "The current indicators are neutral."

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
            return f"⚠️ **Diversification Warning:** Your portfolio is heavily concentrated in: {', '.join(highly_concentrated_sectors)}."
        else:
            return "✅ **Good Diversification:** Your portfolio appears to be well-diversified."

# --- Instantiate Core Components ---
try:
    pathway = PathwayClient()
    engine = AnalysisEngine()
except ValueError as e:
    print(f"FATAL ERROR: {e}")
    pathway = None
    engine = None

# --- 3. Flask Routes (Modified to handle initialization error) ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyse', methods=['POST'])
def analyse_portfolio():
    if not pathway or not engine:
        return jsonify({"error": "Server is not configured. Missing API Key."}), 503

    try:
        data = request.get_json()
        portfolio_data = data.get('portfolio')
        if not portfolio_data: return jsonify({"error": "Portfolio data is missing."}), 400

        num_advice_items = len(portfolio_data)
        current_bill = COST_PER_PORTFOLIO + (num_advice_items * COST_PER_ADVICE)
        usage_tracker["portfolios_analyzed"] += 1
        usage_tracker["advice_generated"] += num_advice_items
        usage_tracker["total_bill"] += current_bill
        
        tickers_to_fetch = [stock['ticker'] for stock in portfolio_data]
        live_market_data = pathway.fetch_live_stock_data(tickers_to_fetch)

        if not live_market_data:
            return jsonify({"error": "Could not fetch market data. Check ticker symbols or API limits."}), 500

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
            "usage_stats": {"portfolios_analyzed": usage_tracker["portfolios_analyzed"], "total_bill": f'{usage_tracker["total_bill"]:.2f}'}
        })
    except Exception as e:
        print(f"An error occurred during analysis: {e}")
        return jsonify({"error": "An internal server error occurred."}), 500

# --- 4. Main Execution Block ---
if __name__ == '__main__':
    if pathway:
        app.run(debug=True, host='0.0.0.0')
    else:
        print("Application cannot start due to missing API key.")
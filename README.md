# Tickaro — Telegram Trading Intelligence Bot

Telegram-native market intelligence bot. The MVP focuses on prices, charts, news, watchlists, alerts, scanner, daily brief, and account/usage controls.

## MVP stack

- Python + aiogram
- FastAPI
- yfinance for stocks/indices/history
- biquote for supported FX/Gold/Crypto/Index CFD quotes and streaming
- GDELT + RSS for news
- pandas + NumPy for indicators
- mplfinance/Matplotlib for charts
- Redis for cache/hot state when configured
- PostgreSQL for production persistence; SQLite is the local default
- Railway for hosting

## Run locally

1. Create and activate a Python virtual environment.
2. Install dependencies: `pip install -r requirements.txt`
3. Copy `.env.example` to `.env`.
4. Set `BOT_TOKEN` to the token from BotFather.
5. Run: `python main.py`

The application exposes `GET /health` for hosting health checks.

## Commands

- `/start`
- `/help`
- `/account`
- `/price SYMBOL`
- `/chart SYMBOL [1d|5d|1mo|3mo|6mo|1y] [advanced]`
- `/news SYMBOL`
- `/why SYMBOL`
- `/watchlist`
- `/add SYMBOL`
- `/remove SYMBOL`
- `/alerts`
- `/alert SYMBOL CONDITION VALUE`
- `/remove_alert ID`
- `/market`
- `/brief`
- `/scanner [top_gainers|top_losers|volume_spike|overbought|oversold]`

Smart alert example: `/alert NVDA smart`

Advanced chart example: `/chart NVDA 3mo advanced`

## Free MVP limits

- 1 watchlist
- 10 tickers
- 3 active alerts
- 50 price lookups/day
- 10 charts/day
- 30 news requests/day
- 5 scanner scans/day
- 1 daily brief/day
- 3 why-did-it-move requests/day
- 3 active smart alerts
- Basic indicators included
- Advanced indicators: 3/day

## Tests

Run the unit test suite with:

`pytest -q`

CI also compiles the project and runs the tests on pushes and pull requests targeting `main`.

## Deployment

For Railway production, set `BOT_TOKEN`, `DATABASE_URL`, and `REDIS_URL` as environment variables. PostgreSQL and Redis are external services attached to the application; secrets are not stored in Git.

External data providers can fail or return stale data. The application uses provider adapters so sources can be replaced later. Before production launch, verify current provider behaviour, limits, and data quality.

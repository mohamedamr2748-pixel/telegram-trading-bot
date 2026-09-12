import os


os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("BIQUOTE_ENABLED", "true")
os.environ.setdefault("YFINANCE_ENABLED", "true")

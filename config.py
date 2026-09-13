from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str = ""
    database_url: str = "sqlite+aiosqlite:///./bot.db"
    redis_url: str | None = None
    default_timezone: str = "UTC"
    gdelt_base_url: str = "https://api.gdeltproject.org/api/v2/doc/doc"
    rss_feeds: str = ""
    scanner_universe: str = "AAPL,MSFT,NVDA,AMZN,META,TSLA,GOOGL,GOOG,AVGO,AMD,PLTR,COIN,INTC,JPM,SPY,QQQ,IWM"
    yfinance_enabled: bool = True
    biquote_enabled: bool = True
    google_finance_enabled: bool = False
    google_finance_base_url: str = "https://api.crawlora.net/api/v1/google/finance"
    google_finance_api_key: str = ""
    market_poll_seconds: int = 30
    alert_poll_seconds: int = 15
    news_poll_seconds: int = 120
    port: int = 8080
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    @property
    def scanner_symbols(self) -> list[str]:
        return [s.strip().upper() for s in self.scanner_universe.split(",") if s.strip()]

    @property
    def rss_urls(self) -> list[str]:
        return [u.strip() for u in self.rss_feeds.split(",") if u.strip()]


settings = Settings()

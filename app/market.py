from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
import pandas as pd
import yfinance as yf

from app.domain import MarketQuote, to_float
from config import settings


class MarketProvider(ABC):
    name = "base"

    @abstractmethod
    async def get_quote(self, symbol: str) -> MarketQuote:
        raise NotImplementedError

    @abstractmethod
    async def get_history(self, symbol: str, period: str = "1mo", interval: str = "1d") -> pd.DataFrame:
        raise NotImplementedError


class GoogleFinanceProvider(MarketProvider):
    """Google Finance public-page data exposed through Crawlora's Google Finance API."""

    name = "google_finance"

    _WINDOWS = {
        "1d": "1D",
        "5d": "5D",
        "1mo": "1M",
        "3mo": "3M",
        "6mo": "6M",
        "ytd": "YTD",
        "1y": "1Y",
        "5y": "5Y",
        "max": "MAX",
    }

    def __init__(self) -> None:
        self._symbol_cache: dict[str, str] = {}

    @property
    def enabled(self) -> bool:
        return settings.google_finance_enabled and bool(settings.google_finance_api_key.strip())

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": settings.google_finance_api_key.strip()}

    async def _request(self, path: str, params: dict[str, str] | None = None) -> dict:
        if not self.enabled:
            raise RuntimeError("Google Finance provider is not configured")
        url = f"{settings.google_finance_base_url.rstrip('/')}/{path.lstrip('/')}"
        async with httpx.AsyncClient(timeout=20, headers=self._headers()) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Google Finance returned an invalid response")
        if payload.get("code") not in (None, 200):
            raise ValueError(str(payload.get("msg") or "Google Finance request failed"))
        return payload.get("data") if isinstance(payload.get("data"), dict) else payload

    @staticmethod
    def _find_identifier(value: object) -> str | None:
        if isinstance(value, dict):
            for key in ("identifier", "quote", "symbol"):
                candidate = value.get(key)
                if isinstance(candidate, str) and ":" in candidate:
                    return candidate.upper()
            for child in value.values():
                found = GoogleFinanceProvider._find_identifier(child)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = GoogleFinanceProvider._find_identifier(child)
                if found:
                    return found
        return None

    async def resolve_symbol(self, symbol: str) -> str:
        raw = symbol.strip().upper()
        if ":" in raw or ("-" in raw and raw.split("-")[0].isalpha()):
            return raw
        cached = self._symbol_cache.get(raw)
        if cached:
            return cached
        data = await self._request("search", {"q": raw})
        identifier = self._find_identifier(data)
        if not identifier:
            raise ValueError(f"Could not resolve {symbol} on Google Finance")
        self._symbol_cache[raw] = identifier
        return identifier

    @staticmethod
    def _first_numeric(data: dict, *paths: tuple[str, ...]) -> float | None:
        for path in paths:
            current: object = data
            for key in path:
                if not isinstance(current, dict):
                    current = None
                    break
                current = current.get(key)
            if current not in (None, ""):
                try:
                    return float(current)
                except (TypeError, ValueError):
                    continue
        return None

    async def get_quote(self, symbol: str) -> MarketQuote:
        identifier = await self.resolve_symbol(symbol)
        data = await self._request(f"quote/{quote(identifier, safe=':,-.')}")

        instrument = data.get("instrument") if isinstance(data.get("instrument"), dict) else data
        tickers = instrument.get("tickers") if isinstance(instrument, dict) else None
        if not isinstance(tickers, list):
            tickers = data.get("tickers") if isinstance(data.get("tickers"), list) else []
        last_ticker = tickers[-1] if tickers and isinstance(tickers[-1], dict) else {}

        price = self._first_numeric(instrument, ("price",), ("current_price",)) or self._first_numeric(last_ticker, ("price",))
        if price is None or price <= 0:
            raise ValueError(f"Google Finance returned no valid price for {identifier}")

        previous = self._first_numeric(
            instrument,
            ("previous_close",),
            ("key_stats", "previous_close"),
        )
        change = self._first_numeric(instrument, ("change",))
        change_pct = self._first_numeric(instrument, ("change_percent",))
        if change is None and previous:
            change = price - previous
        if change_pct is None and previous:
            change_pct = change / previous * 100 if change is not None else None

        timestamp = datetime.now(timezone.utc)
        raw_unix = instrument.get("last_update_unix") if isinstance(instrument, dict) else None
        if raw_unix:
            try:
                timestamp = datetime.fromtimestamp(float(raw_unix), tz=timezone.utc)
            except (TypeError, ValueError, OverflowError):
                pass
        raw_time = last_ticker.get("time") if isinstance(last_ticker, dict) else None
        if isinstance(raw_time, str):
            try:
                timestamp = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
            except ValueError:
                pass

        return MarketQuote(
            symbol=identifier,
            asset_class=str(instrument.get("type") or "market").lower(),
            price=price,
            open=self._first_numeric(instrument, ("open",), ("priceopen",)),
            high=self._first_numeric(instrument, ("high",)),
            low=self._first_numeric(instrument, ("low",)),
            volume=self._first_numeric(instrument, ("volume",)) or 0.0,
            change=change,
            change_percent=change_pct,
            timestamp=timestamp,
            source=self.name,
            market_status=str(instrument.get("market_state") or instrument.get("market_status") or "unknown"),
        )

    async def get_history(self, symbol: str, period: str = "1mo", interval: str = "1d") -> pd.DataFrame:
        identifier = await self.resolve_symbol(symbol)
        window = self._WINDOWS.get(period.lower())
        if window is None:
            raise ValueError(f"Unsupported Google Finance chart window: {period}")
        data = await self._request(
            f"chart/{quote(identifier, safe=':,-.')}",
            {"window": window},
        )

        candidates: list[object] = []
        for key in ("tickers", "points", "chart", "series", "data"):
            value = data.get(key)
            if isinstance(value, list):
                candidates = value
                break
            if isinstance(value, dict):
                for nested_key in ("tickers", "points", "series"):
                    nested = value.get(nested_key)
                    if isinstance(nested, list):
                        candidates = nested
                        break
            if candidates:
                break

        rows: list[dict] = []
        for point in candidates:
            if not isinstance(point, dict):
                continue
            raw_time = point.get("time") or point.get("timestamp") or point.get("datetime")
            raw_price = point.get("price")
            if raw_price is None:
                raw_price = point.get("close") if point.get("close") is not None else point.get("value")
            if raw_time is None or raw_price in (None, ""):
                continue
            try:
                timestamp = pd.to_datetime(raw_time, utc=True)
                price = float(raw_price)
            except (TypeError, ValueError):
                continue
            volume = to_float(point.get("volume"), 0.0)
            rows.append({
                "Date": timestamp,
                "Open": price,
                "High": price,
                "Low": price,
                "Close": price,
                "Volume": volume,
            })

        if not rows:
            raise ValueError(f"No chart data returned for {identifier}")

        frame = pd.DataFrame(rows).set_index("Date").sort_index()
        frame = frame[~frame.index.duplicated(keep="last")]
        return frame


class YFinanceProvider(MarketProvider):
    name = "yfinance"

    @staticmethod
    def _classify(symbol: str) -> str:
        s = symbol.upper()
        if s.startswith("^"):
            return "index"
        if s.endswith("=F"):
            return "commodity"
        if s.endswith("-USD"):
            return "crypto"
        if s in {"BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "BNBUSD"}:
            return "crypto"
        if s in {"EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD"}:
            return "forex"
        if s in {"XAUUSD", "XAGUSD"}:
            return "metal"
        return "stock"

    async def get_quote(self, symbol: str) -> MarketQuote:
        def fetch() -> MarketQuote:
            ticker = yf.Ticker(symbol)
            try:
                info = ticker.fast_info
                price = to_float(getattr(info, "last_price", None))
                previous = to_float(getattr(info, "previous_close", None))
            except Exception:
                price = previous = 0.0
            if price <= 0:
                frame = ticker.history(period="2d", interval="1d", auto_adjust=False)
                if frame.empty:
                    raise ValueError(f"No market data found for {symbol}")
                last = frame.iloc[-1]
                price = to_float(last.get("Close"))
                previous = to_float(frame.iloc[-2].get("Close")) if len(frame) > 1 else price
                open_ = to_float(last.get("Open"))
                high = to_float(last.get("High"))
                low = to_float(last.get("Low"))
                volume = to_float(last.get("Volume"))
                ts = frame.index[-1].to_pydatetime()
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            else:
                open_ = high = low = volume = 0.0
                ts = datetime.now(timezone.utc)
            change = price - previous if previous else None
            change_pct = (change / previous * 100) if previous else None
            return MarketQuote(
                symbol=symbol.upper(),
                asset_class=self._classify(symbol),
                price=price,
                open=open_,
                high=high,
                low=low,
                volume=volume,
                change=change,
                change_percent=change_pct,
                timestamp=ts,
                source=self.name,
                market_status="open" if ts.date() == datetime.now(timezone.utc).date() else "unknown",
            )

        return await asyncio.to_thread(fetch)

    async def get_history(self, symbol: str, period: str = "1mo", interval: str = "1d") -> pd.DataFrame:
        def fetch() -> pd.DataFrame:
            df = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=False)
            if df.empty:
                raise ValueError(f"No historical data found for {symbol}")
            return df

        return await asyncio.to_thread(fetch)


class BiQuoteProvider(MarketProvider):
    name = "biquote"
    base_url = "https://biquote.io/api"

    async def get_quote(self, symbol: str) -> MarketQuote:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self.base_url}/{symbol.upper()}",
                params={"allowStale": "true"},
            )
            response.raise_for_status()
            data = response.json()

        timestamp = datetime.now(timezone.utc)
        raw_timestamp = data.get("timestamp") or data.get("time")
        if isinstance(raw_timestamp, str):
            try:
                timestamp = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
            except ValueError:
                pass

        price = to_float(data.get("mid") or data.get("price"))
        if price <= 0:
            raise ValueError(f"No valid price returned for {symbol}")
        previous = to_float(data.get("previousClose"), 0.0)
        change = (price - previous) if previous else None
        change_pct = (change / previous * 100) if previous else None
        return MarketQuote(
            symbol=symbol.upper(),
            asset_class=str(data.get("type") or "market").lower(),
            price=price,
            open=to_float(data.get("open"), 0.0) or None,
            high=to_float(data.get("high"), 0.0) or None,
            low=to_float(data.get("low"), 0.0) or None,
            volume=to_float(data.get("volume")),
            change=change,
            change_percent=change_pct,
            timestamp=timestamp,
            source=self.name,
            market_status=str(data.get("marketState") or "unknown"),
        )

    async def get_history(self, symbol: str, period: str = "1mo", interval: str = "1d") -> pd.DataFrame:
        raise NotImplementedError("Use Google Finance or yfinance for OHLC history")


class MarketService:
    def __init__(self) -> None:
        self.google = GoogleFinanceProvider()
        self.yf = YFinanceProvider()
        self.bq = BiQuoteProvider()

    @staticmethod
    def _prefer_biquote(symbol: str) -> bool:
        s = symbol.upper()
        return s in {
            "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD",
            "XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "BNBUSD",
            "USOIL", "UKOIL", "US30", "NAS100", "SPX500", "GER40", "UK100",
        }

    async def get_quote(self, symbol: str) -> MarketQuote:
        symbol = symbol.strip().upper()
        if settings.google_finance_enabled:
            if not self.google.enabled:
                raise RuntimeError("Google Finance is enabled but GOOGLE_FINANCE_API_KEY is missing")
            return await self.google.get_quote(symbol)

        errors: list[str] = []
        providers = [self.bq, self.yf] if self._prefer_biquote(symbol) and settings.biquote_enabled else [self.yf, self.bq]
        for provider in providers:
            try:
                if provider is self.yf and not settings.yfinance_enabled:
                    continue
                if provider is self.bq and not settings.biquote_enabled:
                    continue
                return await provider.get_quote(symbol)
            except Exception as exc:
                errors.append(f"{provider.name}: {exc}")
        raise RuntimeError("Market providers failed: " + " | ".join(errors))

    async def get_history(self, symbol: str, period: str = "1mo", interval: str = "1d") -> pd.DataFrame:
        if settings.google_finance_enabled:
            if not self.google.enabled:
                raise RuntimeError("Google Finance is enabled but GOOGLE_FINANCE_API_KEY is missing")
            return await self.google.get_history(symbol.strip().upper(), period, interval)
        return await self.yf.get_history(symbol.strip().upper(), period, interval)

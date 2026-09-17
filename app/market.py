from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from urllib.parse import quote
from datetime import time
from zoneinfo import ZoneInfo

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
    name = "google_finance"
    _WINDOWS = {
        "1d": "1D", "5d": "5D", "1mo": "1M", "3mo": "3M", "6mo": "6M",
        "ytd": "YTD", "1y": "1Y", "5y": "5Y", "max": "MAX",
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
            for key in ("identifier", "quote"):
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
        user_symbol = symbol.strip().upper()
        identifier = await self.resolve_symbol(user_symbol)
        data = await self._request(f"quote/{quote(identifier, safe=':,-.')}")
        instrument = data.get("instrument") if isinstance(data.get("instrument"), dict) else data
        tickers = instrument.get("tickers") if isinstance(instrument, dict) else None
        if not isinstance(tickers, list):
            tickers = data.get("tickers") if isinstance(data.get("tickers"), list) else []
        last_ticker = tickers[-1] if tickers and isinstance(tickers[-1], dict) else {}

        price = self._first_numeric(instrument, ("price",), ("current_price",)) or self._first_numeric(last_ticker, ("price",))
        if price is None or price <= 0:
            raise ValueError(f"Google Finance returned no valid price for {identifier}")
        previous = self._first_numeric(instrument, ("previous_close",), ("key_stats", "previous_close"), ("previousClose",))
        change = self._first_numeric(instrument, ("change",))
        change_pct = self._first_numeric(instrument, ("change_percent",), ("changePercent",))
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
            symbol=user_symbol,
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
            market_status=str(instrument.get("market_state") or instrument.get("market_status") or instrument.get("marketState") or "unknown"),
            previous_close=previous,
            year_high=self._first_numeric(instrument, ("year_high",), ("52_week_high",), ("fifty_two_week_high",), ("key_stats", "52_week_high")),
            year_low=self._first_numeric(instrument, ("year_low",), ("52_week_low",), ("fifty_two_week_low",), ("key_stats", "52_week_low")),
            market_cap=self._first_numeric(instrument, ("market_cap",), ("marketCap",), ("valuation", "market_cap")),
            pe_ratio=self._first_numeric(instrument, ("pe_ratio",), ("pe",), ("key_stats", "pe_ratio")),
            dividend_yield=self._first_numeric(instrument, ("dividend_yield",), ("dividendYield",), ("key_stats", "dividend_yield")),
            eps=self._first_numeric(instrument, ("eps",), ("earnings_per_share",), ("key_stats", "eps")),
            pre_market_price=self._first_numeric(instrument, ("pre_market_price",), ("preMarketPrice",), ("premarket_price",)),
            post_market_price=self._first_numeric(instrument, ("after_hours_price",), ("post_market_price",), ("postMarketPrice",)),
        )

    async def get_history(self, symbol: str, period: str = "1mo", interval: str = "1d") -> pd.DataFrame:
        identifier = await self.resolve_symbol(symbol)
        window = self._WINDOWS.get(period.lower())
        if window is None:
            raise ValueError(f"Unsupported Google Finance chart window: {period}")
        data = await self._request(f"chart/{quote(identifier, safe=':,-.')}", {"window": window})
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
                point_price = float(raw_price)
            except (TypeError, ValueError):
                continue
            volume = to_float(point.get("volume"), 0.0)
            rows.append({"Date": timestamp, "Open": point_price, "High": point_price, "Low": point_price, "Close": point_price, "Volume": volume})
        if not rows:
            raise ValueError(f"No chart data returned for {identifier}")
        frame = pd.DataFrame(rows).set_index("Date").sort_index()
        return frame[~frame.index.duplicated(keep="last")]


class YFinanceProvider(MarketProvider):
    name = "yfinance"

    _FOREX_YF_SYMBOLS = {
        "EURUSD": "EURUSD=X",
        "GBPUSD": "GBPUSD=X",
        "USDJPY": "USDJPY=X",
        "AUDUSD": "AUDUSD=X",
        "USDCAD": "USDCAD=X",
        "USDCHF": "USDCHF=X",
        "NZDUSD": "NZDUSD=X",
    }
    _INVERSE_FOREX = {
        "USDEUR": "EURUSD",
        "USDGBP": "GBPUSD",
        "JPYUSD": "USDJPY",
        "USDAUD": "AUDUSD",
        "AUUSD": "AUDUSD",
        "CADUSD": "USDCAD",
        "CHFUSD": "USDCHF",
        "USDNZD": "NZDUSD",
    }

    @classmethod
    def _normalize_pair(cls, symbol: str) -> tuple[str, bool]:
        normalized = symbol.strip().upper().replace("/", "").replace("-", "")
        if normalized in cls._FOREX_YF_SYMBOLS:
            return normalized, False
        inverse_base = cls._INVERSE_FOREX.get(normalized)
        if inverse_base:
            return inverse_base, True
        return symbol.strip().upper(), False

    @classmethod
    def _history_symbol(cls, symbol: str) -> str:
        normalized, _ = cls._normalize_pair(symbol)
        return cls._FOREX_YF_SYMBOLS.get(normalized, normalized)

    @staticmethod
    def _invert_quote(value: float | None) -> float | None:
        return (1.0 / value) if value and value > 0 else None

    @classmethod
    def _invert_history(cls, frame: pd.DataFrame) -> pd.DataFrame:
        inverted = frame.copy()
        original_high = frame["High"].copy() if "High" in frame else None
        original_low = frame["Low"].copy() if "Low" in frame else None
        if "Open" in inverted:
            inverted["Open"] = frame["Open"].apply(cls._invert_quote)
        if original_low is not None:
            inverted["High"] = original_low.apply(cls._invert_quote)
        if original_high is not None:
            inverted["Low"] = original_high.apply(cls._invert_quote)
        if "Close" in inverted:
            inverted["Close"] = frame["Close"].apply(cls._invert_quote)
        return inverted

    @staticmethod
    def _resample_stock_4h(frame: pd.DataFrame) -> pd.DataFrame:
        """Build 4H stock candles from regular-session 1H OHLCV data.

        Yahoo's stock 4H interval can produce inconsistent bars for the
        session-based chart. We instead use clean 1H regular-session data and
        aggregate it into 4H buckets anchored at the U.S. regular open.
        No extended-hours rows are included and no price data is fabricated.
        """
        if frame.empty:
            return frame

        work = frame.copy()
        work.index = pd.to_datetime(work.index, errors="coerce")
        work = work[work.index.notna()].sort_index()
        if work.index.tz is None:
            work.index = work.index.tz_localize("America/New_York")
        else:
            work.index = work.index.tz_convert("America/New_York")

        minutes = work.index.hour * 60 + work.index.minute
        regular = work[(minutes >= 9 * 60 + 30) & (minutes < 16 * 60)]
        if regular.empty:
            return regular

        agg: dict[str, str] = {}
        for column, function in (
            ("Open", "first"),
            ("High", "max"),
            ("Low", "min"),
            ("Close", "last"),
            ("Volume", "sum"),
        ):
            if column in regular.columns:
                agg[column] = function
        if "Close" not in agg:
            raise ValueError("No Close column available for 4H stock aggregation")

        four_hour = (
            regular.resample(
                "4h",
                origin="start_day",
                offset="9h30min",
                label="left",
                closed="left",
            )
            .agg(agg)
            .dropna(subset=["Close"])
        )
        four_hour.index = four_hour.index.tz_convert("UTC")
        return four_hour

    @staticmethod
    def _classify(symbol: str) -> str:
        s = symbol.upper().replace("/", "").replace("-", "")
        if s.startswith("^"):
            return "index"
        if s.endswith("=F"):
            return "commodity"
        if s.endswith("-USD"):
            return "crypto"
        if s in {"BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "BNBUSD"}:
            return "crypto"
        if s.endswith("=X") or s in {"EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "USDEUR", "USDGBP", "JPYUSD", "USDAUD", "AUUSD", "CADUSD", "CHFUSD", "USDNZD"}:
            return "forex"
        if s in {"XAUUSD", "XAGUSD"}:
            return "metal"
        return "stock"

    async def get_quote(self, symbol: str) -> MarketQuote:
        def fetch() -> MarketQuote:
            user_symbol = symbol.strip().upper()
            _, inverse = self._normalize_pair(user_symbol)
            ticker_symbol = self._history_symbol(user_symbol)
            ticker = yf.Ticker(ticker_symbol)
            try:
                info = ticker.fast_info
                price = to_float(getattr(info, "last_price", None))
                previous = to_float(getattr(info, "previous_close", None))
                open_ = to_float(getattr(info, "open", None)) or None
                high = to_float(getattr(info, "day_high", None)) or None
                low = to_float(getattr(info, "day_low", None)) or None
                volume = to_float(getattr(info, "last_volume", None), 0.0)
                year_high = to_float(getattr(info, "year_high", None)) or None
                year_low = to_float(getattr(info, "year_low", None)) or None
                market_cap = to_float(getattr(info, "market_cap", None)) or None
                post_market = to_float(getattr(info, "post_market_price", None)) or None
                pre_market = to_float(getattr(info, "pre_market_price", None)) or None
            except Exception:
                price = previous = 0.0
                open_ = high = low = volume = 0.0
                year_high = year_low = market_cap = post_market = pre_market = None
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
                ts = datetime.now(timezone.utc)

            pe_ratio = dividend_yield = eps = None
            try:
                info_dict = ticker.info
                year_high = year_high or to_float(info_dict.get("fiftyTwoWeekHigh"), 0.0) or None
                year_low = year_low or to_float(info_dict.get("fiftyTwoWeekLow"), 0.0) or None
                market_cap = market_cap or to_float(info_dict.get("marketCap"), 0.0) or None
                pe_ratio = to_float(info_dict.get("trailingPE"), 0.0) or None
                dividend_yield = to_float(info_dict.get("dividendYield"), 0.0) or None
                eps = to_float(info_dict.get("trailingEps"), 0.0) or None
                pre_market = pre_market or to_float(info_dict.get("preMarketPrice"), 0.0) or None
                post_market = post_market or to_float(info_dict.get("postMarketPrice"), 0.0) or None
                market_state = str(info_dict.get("marketState") or "unknown").lower()
            except Exception:
                market_state = "open" if ts.date() == datetime.now(timezone.utc).date() else "unknown"

            if inverse:
                price = self._invert_quote(price)
                previous = self._invert_quote(previous)
                open_ = self._invert_quote(open_)
                original_high, original_low = high, low
                high = self._invert_quote(original_low)
                low = self._invert_quote(original_high)
                year_high_original, year_low_original = year_high, year_low
                year_high = self._invert_quote(year_low_original)
                year_low = self._invert_quote(year_high_original)
                pre_market = self._invert_quote(pre_market)
                post_market = self._invert_quote(post_market)

            change = price - previous if previous else None
            change_pct = (change / previous * 100) if previous else None
            return MarketQuote(
                symbol=user_symbol, asset_class=self._classify(user_symbol), price=price,
                open=open_, high=high, low=low, volume=volume, change=change,
                change_percent=change_pct, timestamp=ts, source=self.name, market_status=market_state,
                previous_close=previous or None, year_high=year_high, year_low=year_low,
                market_cap=market_cap if not inverse else None, pe_ratio=pe_ratio if not inverse else None,
                dividend_yield=dividend_yield if not inverse else None, eps=eps if not inverse else None,
                pre_market_price=pre_market, post_market_price=post_market,
            )
        return await asyncio.to_thread(fetch)

    async def get_history(self, symbol: str, period: str = "1mo", interval: str = "1d") -> pd.DataFrame:
        def fetch() -> pd.DataFrame:
            _, inverse = self._normalize_pair(symbol)
            yf_symbol = self._history_symbol(symbol)
            ticker = yf.Ticker(yf_symbol)
            is_stock = self._classify(symbol) == "stock" and not inverse
            is_stock_4h = interval.strip().lower() == "4h" and is_stock
            requested_interval = "1h" if is_stock_4h else interval
            history_kwargs = {"period": period, "interval": requested_interval, "auto_adjust": False}
            # Standard /price intraday charts use regular-session candles only.
            # Quote data continues to expose pre/post-market prices separately.
            df = ticker.history(**history_kwargs)
            if is_stock_4h:
                df = self._resample_stock_4h(df)

            # Broad-market indices can intermittently return only one intraday
            # row for a direct 1D request. A single row renders as one dot, so
            # retry on a wider window and extract the latest available trading
            # date. This keeps the public chart at the requested 1D/15m view.
            if interval.endswith(("m", "h")) and self._classify(symbol) == "index" and len(df) < 2:
                fallback_kwargs = {"period": "5d", "interval": interval, "auto_adjust": False}
                try:
                    fallback = ticker.history(**fallback_kwargs)
                except Exception:
                    fallback = pd.DataFrame()
                if len(fallback) >= 2:
                    fallback = fallback.copy()
                    fallback.index = pd.to_datetime(fallback.index)
                    latest_day = fallback.index.max().date()
                    same_day = fallback.loc[fallback.index.date == latest_day]
                    if len(same_day) >= 2:
                        df = same_day
                    else:
                        df = fallback.tail(min(len(fallback), 32))

            if df.empty:
                raise ValueError(f"No historical data found for {symbol} (Yahoo symbol: {yf_symbol})")
            return self._invert_history(df) if inverse else df
        return await asyncio.to_thread(fetch)


class BiQuoteProvider(MarketProvider):
    name = "biquote"
    base_url = "https://biquote.io/api"

    async def get_quote(self, symbol: str) -> MarketQuote:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{self.base_url}/{symbol.upper()}", params={"allowStale": "true"})
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
            symbol=symbol.upper(), asset_class=str(data.get("type") or "market").lower(), price=price,
            open=to_float(data.get("open"), 0.0) or None, high=to_float(data.get("high"), 0.0) or None,
            low=to_float(data.get("low"), 0.0) or None, volume=to_float(data.get("volume")),
            change=change, change_percent=change_pct, timestamp=timestamp, source=self.name,
            market_status=str(data.get("marketState") or "unknown"), previous_close=previous or None,
            year_high=to_float(data.get("yearHigh"), 0.0) or None, year_low=to_float(data.get("yearLow"), 0.0) or None,
            market_cap=to_float(data.get("marketCap"), 0.0) or None, pe_ratio=to_float(data.get("peRatio"), 0.0) or None,
            dividend_yield=to_float(data.get("dividendYield"), 0.0) or None, eps=to_float(data.get("eps"), 0.0) or None,
            pre_market_price=to_float(data.get("preMarketPrice"), 0.0) or None,
            post_market_price=to_float(data.get("postMarketPrice"), 0.0) or None,
        )

    @staticmethod
    def _normalize_history_symbol(symbol: str) -> str:
        raw = symbol.strip().upper()
        compact = raw.replace("/", "").replace("-", "")
        aliases = {
            "BTCUSD": "BTCUSD",
            "ETHUSD": "ETHUSD",
            "SOLUSD": "SOLUSD",
            "XRPUSD": "XRPUSD",
            "BNBUSD": "BNBUSD",
            "BTCUSD": "BTCUSD",
            "GC=F": "XAUUSD",
            "XAUUSD": "XAUUSD",
            "SI=F": "XAGUSD",
            "XAGUSD": "XAGUSD",
            "CL=F": "USOIL",
            "BZ=F": "UKOIL",
            "^DJI": "US30",
            "^NDX": "NAS100",
            "^GSPC": "SPX500",
            "^GDAXI": "GER40",
            "^FTSE": "UK100",
        }
        return aliases.get(raw, aliases.get(compact, compact))

    @staticmethod
    def _bars_to_frame(bars: object, symbol: str) -> pd.DataFrame:
        if not isinstance(bars, list):
            raise ValueError(f"BiQuote returned no OHLC bars for {symbol}")

        rows: list[dict] = []
        for bar in bars:
            if not isinstance(bar, dict):
                continue
            raw_time = bar.get("openTime") or bar.get("timestamp") or bar.get("time")
            if raw_time in (None, ""):
                continue
            try:
                timestamp = pd.to_datetime(raw_time, utc=True)
                values = {
                    "Open": to_float(bar.get("open"), None),
                    "High": to_float(bar.get("high"), None),
                    "Low": to_float(bar.get("low"), None),
                    "Close": to_float(bar.get("close"), None),
                    "Volume": to_float(bar.get("volume"), to_float(bar.get("tickVolume"), 0.0)),
                }
            except (TypeError, ValueError):
                continue
            if any(values[column] is None for column in ("Open", "High", "Low", "Close")):
                continue
            rows.append({"Date": timestamp, **values})

        if not rows:
            raise ValueError(f"No valid 4H OHLC bars returned for {symbol}")

        frame = pd.DataFrame(rows).set_index("Date").sort_index()
        frame = frame[~frame.index.duplicated(keep="last")]
        return frame[["Open", "High", "Low", "Close", "Volume"]]

    async def get_history(self, symbol: str, period: str = "1mo", interval: str = "1d") -> pd.DataFrame:
        requested_interval = interval.strip().lower()
        if requested_interval != "4h":
            raise ValueError("BiQuote history currently supports only native 4H data")

        provider_symbol = self._normalize_history_symbol(symbol)
        # 120 display candles are needed by /price. BiQuote prepends the current
        # open candle, so this yields up to 121 rows and lets the dashboard keep
        # the latest 120 without resampling. The period argument is intentionally
        # ignored because BiQuote's OHLC endpoint is limit-based.
        params = {"interval": "4h", "limit": "120"}
        url = f"{self.base_url}/{quote(provider_symbol, safe='')}/ohlc"
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()

        if not isinstance(payload, dict):
            raise ValueError(f"BiQuote returned an invalid response for {symbol}")
        frame = self._bars_to_frame(payload.get("bars"), provider_symbol)
        if not frame.index.is_monotonic_increasing:
            frame = frame.sort_index()
        return frame


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
        normalized_symbol = symbol.strip().upper()
        normalized_interval = interval.strip().lower()

        # Native 4H is deliberately routed to BiQuote first. We keep yfinance
        # as a compatibility fallback so an unsupported symbol does not break
        # /price while BiQuote coverage is being expanded.
        if normalized_interval == "4h":
            errors: list[str] = []
            if settings.biquote_enabled:
                try:
                    return await self.bq.get_history(normalized_symbol, period, normalized_interval)
                except Exception as exc:
                    errors.append(f"{self.bq.name}: {exc}")
            if settings.yfinance_enabled:
                try:
                    return await self.yf.get_history(normalized_symbol, period, normalized_interval)
                except Exception as exc:
                    errors.append(f"{self.yf.name}: {exc}")
            raise RuntimeError("4H history providers failed: " + " | ".join(errors))

        if settings.google_finance_enabled:
            if not self.google.enabled:
                raise RuntimeError("Google Finance is enabled but GOOGLE_FINANCE_API_KEY is missing")
            return await self.google.get_history(normalized_symbol, period, interval)
        return await self.yf.get_history(normalized_symbol, period, interval)

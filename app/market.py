from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timezone

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
        raise NotImplementedError("Use yfinance for OHLC history")


class MarketService:
    def __init__(self) -> None:
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
        return await self.yf.get_history(symbol.strip().upper(), period, interval)

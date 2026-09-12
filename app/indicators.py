from __future__ import annotations

import numpy as np
import pandas as pd


def add_basic_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    close = out["Close"].astype(float)
    out["SMA20"] = close.rolling(20).mean()
    out["EMA20"] = close.ewm(span=20, adjust=False).mean()
    out["EMA50"] = close.ewm(span=50, adjust=False).mean()

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out["RSI14"] = 100 - (100 / (1 + rs))

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    out["MACD"] = ema12 - ema26
    out["MACD_SIGNAL"] = out["MACD"].ewm(span=9, adjust=False).mean()
    return out


def add_advanced_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = add_basic_indicators(df)
    close = out["Close"].astype(float)
    high = out["High"].astype(float)
    low = out["Low"].astype(float)

    mid = close.rolling(20).mean()
    std = close.rolling(20).std()
    out["BB_MID"] = mid
    out["BB_UPPER"] = mid + 2 * std
    out["BB_LOWER"] = mid - 2 * std

    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    out["ATR14"] = tr.rolling(14).mean()

    lowest = low.rolling(14).min()
    highest = high.rolling(14).max()
    denom = (highest - lowest).replace(0, np.nan)
    out["STOCH14"] = 100 * (close - lowest) / denom
    return out

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import MetaTrader5 as mt5
import numpy as np
import pandas as pd


@dataclass
class BotConfig:
    login: int
    password: str
    server: str
    symbol: str = "XAUUSD"
    risk_per_trade: float = 0.005
    max_spread_usd: float = 0.25
    atr_period: int = 14
    rsi_period: int = 14
    ema_fast: int = 20
    ema_mid: int = 50
    ema_slow: int = 200
    lot_step: float = 0.01
    min_lot: float = 0.01
    max_lot: float = 10.0
    magic: int = 26022026
    deviation: int = 20
    polling_seconds: int = 5

    # Time filter (UTC)
    enable_session_filter: bool = True
    session_start_utc: int = 13
    session_end_utc: int = 17

    # Optional news lockout hook (you can toggle externally)
    news_lockout: bool = False

    # Diagnostics
    status_log_seconds: int = 30


def connect(cfg: BotConfig) -> None:
    if not mt5.initialize(login=cfg.login, password=cfg.password, server=cfg.server):
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    if not mt5.symbol_select(cfg.symbol, True):
        raise RuntimeError(f"Cannot select symbol {cfg.symbol}")



def get_rates(symbol: str, timeframe: int, bars: int) -> pd.DataFrame:
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"No rates for {symbol} / timeframe={timeframe}")
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    return df



def add_indicators(df: pd.DataFrame, cfg: BotConfig) -> pd.DataFrame:
    out = df.copy()
    price = out["close"]
    out["ema20"] = price.ewm(span=cfg.ema_fast, adjust=False).mean()
    out["ema50"] = price.ewm(span=cfg.ema_mid, adjust=False).mean()
    out["ema200"] = price.ewm(span=cfg.ema_slow, adjust=False).mean()

    hlc3 = (out["high"] + out["low"] + out["close"]) / 3.0
    vol = out["tick_volume"].replace(0, np.nan)
    out["vwap"] = (hlc3 * vol).cumsum() / vol.cumsum()

    delta = out["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / cfg.rsi_period, min_periods=cfg.rsi_period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / cfg.rsi_period, min_periods=cfg.rsi_period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out["rsi"] = 100 - (100 / (1 + rs))

    prev_close = out["close"].shift(1)
    tr = pd.concat(
        [
            out["high"] - out["low"],
            (out["high"] - prev_close).abs(),
            (out["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["atr"] = tr.ewm(alpha=1 / cfg.atr_period, min_periods=cfg.atr_period, adjust=False).mean()
    return out



def in_session(cfg: BotConfig) -> bool:
    if not cfg.enable_session_filter:
        return True
    now = datetime.now(timezone.utc)
    return cfg.session_start_utc <= now.hour < cfg.session_end_utc



def trend_bias(df5: pd.DataFrame) -> Optional[str]:
    last = df5.iloc[-1]
    if last["close"] > last["vwap"] and last["ema20"] > last["ema50"] > last["ema200"]:
        return "long"
    if last["close"] < last["vwap"] and last["ema20"] < last["ema50"] < last["ema200"]:
        return "short"
    return None



def has_open_position(symbol: str, magic: int) -> bool:
    positions = mt5.positions_get(symbol=symbol)
    if not positions:
        return False
    return any(p.magic == magic for p in positions)



def calc_lot_size(cfg: BotConfig, entry: float, stop: float) -> float:
    info = mt5.account_info()
    if info is None:
        raise RuntimeError("Cannot read account info")

    risk_usd = info.balance * cfg.risk_per_trade
    stop_distance = abs(entry - stop)
    if stop_distance <= 0:
        return 0.0

    oz = risk_usd / stop_distance
    lots = oz / 100.0
    lots = max(cfg.min_lot, min(cfg.max_lot, lots))
    lots = round(lots / cfg.lot_step) * cfg.lot_step
    return float(lots)



def spread_value(symbol: str) -> Optional[float]:
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None
    return float(tick.ask - tick.bid)



def spread_ok(cfg: BotConfig) -> bool:
    spread = spread_value(cfg.symbol)
    return spread is not None and spread <= cfg.max_spread_usd



def entry_signal(df1: pd.DataFrame, bias: str) -> Optional[dict]:
    # use last CLOSED candle to reduce re-signals on forming candle
    last = df1.iloc[-2]
    prev = df1.iloc[-3]

    if bias == "long":
        cond = (
            last["close"] > last["ema50"]
            and abs(last["close"] - last["vwap"]) <= 0.35 * last["atr"]
            and last["rsi"] > 50
            and last["close"] > prev["high"]
        )
        if cond:
            stop = min(df1.iloc[-7:-2]["low"].min(), last["close"] - 1.2 * last["atr"])
            entry = last["close"]
            risk = entry - stop
            if risk > 0:
                return {"side": "long", "entry": entry, "sl": stop, "tp": entry + 1.5 * risk}

    if bias == "short":
        cond = (
            last["close"] < last["ema50"]
            and abs(last["close"] - last["vwap"]) <= 0.35 * last["atr"]
            and last["rsi"] < 50
            and last["close"] < prev["low"]
        )
        if cond:
            stop = max(df1.iloc[-7:-2]["high"].max(), last["close"] + 1.2 * last["atr"])
            entry = last["close"]
            risk = stop - entry
            if risk > 0:
                return {"side": "short", "entry": entry, "sl": stop, "tp": entry - 1.5 * risk}

    return None



def order_send(cfg: BotConfig, side: str, lot: float, sl: float, tp: float) -> None:
    tick = mt5.symbol_info_tick(cfg.symbol)
    if tick is None:
        raise RuntimeError("No tick data")

    symbol_info = mt5.symbol_info(cfg.symbol)
    if symbol_info is None:
        raise RuntimeError("No symbol info")

    if side == "long":
        order_type = mt5.ORDER_TYPE_BUY
        price = tick.ask
    else:
        order_type = mt5.ORDER_TYPE_SELL
        price = tick.bid

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": cfg.symbol,
        "volume": lot,
        "type": order_type,
        "price": price,
        "sl": round(sl, symbol_info.digits),
        "tp": round(tp, symbol_info.digits),
        "deviation": cfg.deviation,
        "magic": cfg.magic,
        "comment": "VEPS python bot",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_FOK,
    }
    result = mt5.order_send(request)
    if result is None:
        raise RuntimeError(f"order_send failed: {mt5.last_error()}")
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        raise RuntimeError(f"Trade not done. retcode={result.retcode}, comment={result.comment}")



def evaluate_once(cfg: BotConfig) -> tuple[bool, str]:
    if cfg.news_lockout:
        return False, "news_lockout=True"

    if not in_session(cfg):
        now = datetime.now(timezone.utc).strftime("%H:%M:%S")
        return False, f"out_of_session (now UTC={now}, window={cfg.session_start_utc:02d}-{cfg.session_end_utc:02d})"

    if not spread_ok(cfg):
        spread = spread_value(cfg.symbol)
        return False, f"spread_too_wide spread={spread} max={cfg.max_spread_usd}"

    if has_open_position(cfg.symbol, cfg.magic):
        return False, "existing_position_for_magic"

    df5 = add_indicators(get_rates(cfg.symbol, mt5.TIMEFRAME_M5, 320), cfg)
    bias = trend_bias(df5)
    if not bias:
        return False, "no_5m_bias"

    df1 = add_indicators(get_rates(cfg.symbol, mt5.TIMEFRAME_M1, 520), cfg)
    signal = entry_signal(df1, bias)
    if not signal:
        return False, f"no_1m_entry (bias={bias})"

    lot = calc_lot_size(cfg, signal["entry"], signal["sl"])
    if lot < cfg.min_lot:
        return False, f"lot_below_min lot={lot} min={cfg.min_lot}"

    order_send(cfg, signal["side"], lot, signal["sl"], signal["tp"])
    return True, (
        f"ORDER_OPENED side={signal['side']} lot={lot} entry={signal['entry']:.2f} "
        f"sl={signal['sl']:.2f} tp={signal['tp']:.2f}"
    )



def run(cfg: BotConfig) -> None:
    connect(cfg)
    account = mt5.account_info()
    print("Bot started...")
    print(
        f"account={account.login if account else 'unknown'} symbol={cfg.symbol} "
        f"session_filter={cfg.enable_session_filter} window={cfg.session_start_utc:02d}-{cfg.session_end_utc:02d} UTC"
    )

    last_status_ts = 0.0
    try:
        while True:
            try:
                opened, reason = evaluate_once(cfg)
                now_ts = time.time()
                if opened:
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {reason}")
                elif now_ts - last_status_ts >= cfg.status_log_seconds:
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] waiting: {reason}")
                    last_status_ts = now_ts
            except Exception as loop_err:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Loop error: {loop_err}")

            time.sleep(cfg.polling_seconds)
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    # Fill with your account details
    cfg = BotConfig(
        login=12345678,
        password="YOUR_PASSWORD",
        server="YOUR_BROKER_SERVER",
        # اگر می‌خواهی 24 ساعته چک کند: enable_session_filter=False
        # enable_session_filter=False,
    )
    run(cfg)

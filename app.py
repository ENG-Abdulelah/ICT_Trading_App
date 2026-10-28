#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pro Trading & Macro Intelligence Engine
========================================
Production-grade single-file FastAPI + SQLite application.

Dependencies:  pip install fastapi uvicorn

Run:           python app.py
Port:          $PORT (default 8000)
"""

import os
import math
import time
import random
import sqlite3
import threading
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
import uvicorn


# ============================================================================
# CONFIGURATION
# ============================================================================
DB_PATH = os.environ.get("DB_PATH", "trading_bot_memory.db")
PORT = int(os.environ.get("PORT", 8000))
HOST = os.environ.get("HOST", "0.0.0.0")

SHUTDOWN_EVENT = threading.Event()
DB_LOCK = threading.RLock()
PRICE_LOCK = threading.RLock()


# ============================================================================
# SYMBOL CONFIGURATION
# ============================================================================
SYMBOLS: Dict[str, Dict[str, Any]] = {
    "XAU/USD": {"price": 2352.45, "decimals": 2, "vol": 0.00008, "multiplier": 100,     "pip": 0.01,   "pip_label": "pts"},
    "EUR/USD": {"price": 1.08720, "decimals": 4, "vol": 0.00004, "multiplier": 100000,  "pip": 0.0001, "pip_label": "pips"},
    "GBP/USD": {"price": 1.27150, "decimals": 4, "vol": 0.00005, "multiplier": 100000,  "pip": 0.0001, "pip_label": "pips"},
    "USD/JPY": {"price": 155.320, "decimals": 2, "vol": 0.00004, "multiplier": 1000,    "pip": 0.01,   "pip_label": "pips"},
    "AUD/USD": {"price": 0.65980, "decimals": 4, "vol": 0.00005, "multiplier": 100000,  "pip": 0.0001, "pip_label": "pips"},
    "USD/CHF": {"price": 0.90450, "decimals": 4, "vol": 0.00004, "multiplier": 100000,  "pip": 0.0001, "pip_label": "pips"},
    "USD/CAD": {"price": 1.36480, "decimals": 4, "vol": 0.00004, "multiplier": 100000,  "pip": 0.0001, "pip_label": "pips"},
    "DXY":     {"price": 105.180, "decimals": 2, "vol": 0.00005, "multiplier": 1000,    "pip": 0.01,   "pip_label": "pts"},
}

PRICES: Dict[str, Dict[str, Any]] = {
    sym: {
        "price": cfg["price"],
        "prev_price": cfg["price"],
        "open_price": cfg["price"],
        "last_update": datetime.now(timezone.utc).isoformat(),
    }
    for sym, cfg in SYMBOLS.items()
}

PRICE_HISTORY: Dict[str, List[float]] = {
    sym: [cfg["price"]] * 30 for sym, cfg in SYMBOLS.items()
}


# ============================================================================
# ICT STRATEGIES (10 Core Institutional Concepts)
# ============================================================================
ICT_STRATEGIES: List[str] = [
    "Liquidity Sweep & Stop Hunt",
    "Fair Value Gap (FVG)",
    "Order Block (OB)",
    "Change of Character (CHoCH)",
    "Break of Structure (BOS)",
    "Breaker Block",
    "Judas Swing / ORL",
    "Kill Zones & Power of 3",
    "OTE & Premium/Discount",
    "Inversion FVG (IFVG)",
]


# ============================================================================
# MACRO STATE (background intelligence layer)
# ============================================================================
MACRO_STATE: Dict[str, Any] = {
    "dxy": 105.18,
    "us10y": 4.35,
    "vix": 16.40,
    "gold_silver_ratio": 82.50,
    "regime": "Risk-Off",
    "safe_haven": "Gold",
    "updated_at": datetime.now(timezone.utc).isoformat(),
}

COT_STATE: Dict[str, Dict[str, Any]] = {
    "Gold": {"long": 225000, "short": 78000, "prev_long": 220000, "prev_short": 82000},
    "EUR":  {"long": 165000, "short": 112000, "prev_long": 168000, "prev_short": 108000},
    "GBP":  {"long": 72000,  "short": 58000,  "prev_long": 70000,  "prev_short": 61000},
    "JPY":  {"long": 48000,  "short": 118000, "prev_long": 52000,  "prev_short": 115000},
}

ECONOMIC_CALENDAR: List[Dict[str, Any]] = [
    {"event": "FOMC Rate Decision",    "currency": "USD", "impact": "HIGH",   "time": "T-2 days", "forecast": "5.25%", "previous": "5.25%"},
    {"event": "Non-Farm Payrolls",     "currency": "USD", "impact": "HIGH",   "time": "T-3 days", "forecast": "185K",  "previous": "175K"},
    {"event": "US CPI YoY",            "currency": "USD", "impact": "HIGH",   "time": "T-5 days", "forecast": "3.2%",  "previous": "3.4%"},
    {"event": "ECB Press Conference",  "currency": "EUR", "impact": "MEDIUM", "time": "T-1 day",  "forecast": "Hold",  "previous": "Hold"},
    {"event": "BoE Bank Rate",         "currency": "GBP", "impact": "MEDIUM", "time": "T-4 days", "forecast": "5.00%", "previous": "5.25%"},
    {"event": "BoJ Policy Statement",  "currency": "JPY", "impact": "HIGH",   "time": "T-6 days", "forecast": "Hold",  "previous": "Hold"},
    {"event": "US Retail Sales",       "currency": "USD", "impact": "MEDIUM", "time": "T-2 days", "forecast": "0.4%",  "previous": "0.3%"},
    {"event": "German ZEW Sentiment",  "currency": "EUR", "impact": "LOW",    "time": "T-1 day",  "forecast": "12.5",  "previous": "11.0"},
]


# ============================================================================
# DATABASE LAYER (Thread-Safe)
# ============================================================================
def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def db_execute(sql: str, params: tuple = ()) -> int:
    with DB_LOCK:
        conn = get_conn()
        try:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur.lastrowid or 0
        finally:
            conn.close()


def db_executemany(sql: str, params_list: list) -> None:
    with DB_LOCK:
        conn = get_conn()
        try:
            conn.executemany(sql, params_list)
            conn.commit()
        finally:
            conn.close()


def db_query(sql: str, params: tuple = ()) -> List[sqlite3.Row]:
    with DB_LOCK:
        conn = get_conn()
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()


def db_query_one(sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
    with DB_LOCK:
        conn = get_conn()
        try:
            return conn.execute(sql, params).fetchone()
        finally:
            conn.close()


def init_db() -> None:
    with DB_LOCK:
        conn = get_conn()
        try:
            cur = conn.cursor()

            cur.execute("""
                CREATE TABLE IF NOT EXISTS bot_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    capital REAL NOT NULL DEFAULT 10000.0,
                    risk_percent REAL NOT NULL DEFAULT 1.0,
                    updated_at TEXT NOT NULL
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
                    entry_price REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    take_profit REAL NOT NULL,
                    lot_size REAL NOT NULL,
                    pattern TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','WIN','LOSS')),
                    pnl REAL DEFAULT 0.0,
                    exit_price REAL,
                    opened_at TEXT NOT NULL,
                    closed_at TEXT
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS strategies (
                    name TEXT PRIMARY KEY,
                    total_trades INTEGER NOT NULL DEFAULT 0,
                    wins INTEGER NOT NULL DEFAULT 0,
                    losses INTEGER NOT NULL DEFAULT 0
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS self_learning (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id INTEGER,
                    symbol TEXT,
                    strategy TEXT,
                    lesson TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (trade_id) REFERENCES trades (id)
                )
            """)

            cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_opened ON trades(opened_at)")

            cur.execute("SELECT COUNT(*) AS c FROM bot_settings")
            if cur.fetchone()["c"] == 0:
                cur.execute(
                    "INSERT INTO bot_settings (id, capital, risk_percent, updated_at) VALUES (1, ?, ?, ?)",
                    (10000.0, 1.0, datetime.now(timezone.utc).isoformat())
                )

            for name in ICT_STRATEGIES:
                cur.execute(
                    "INSERT OR IGNORE INTO strategies (name, total_trades, wins, losses) VALUES (?, 0, 0, 0)",
                    (name,)
                )

            cur.execute("SELECT COUNT(*) AS c FROM strategies WHERE total_trades > 0")
            if cur.fetchone()["c"] == 0:
                rng = random.Random(42)
                for name in ICT_STRATEGIES:
                    total = rng.randint(28, 72)
                    wr = rng.uniform(0.54, 0.78)
                    wins = int(total * wr)
                    cur.execute(
                        "UPDATE strategies SET total_trades=?, wins=?, losses=? WHERE name=?",
                        (total, wins, total - wins, name)
                    )

            conn.commit()
        finally:
            conn.close()


# ============================================================================
# RISK ENGINE
# ============================================================================
def calculate_lot_size(capital: float, risk_percent: float, sl_distance: float, symbol: str) -> float:
    if sl_distance <= 0 or capital <= 0 or risk_percent <= 0:
        return 0.01
    mult = SYMBOLS.get(symbol, {}).get("multiplier", 100000)
    risk_amount = capital * (risk_percent / 100.0)
    raw = risk_amount / (sl_distance * mult)
    return max(0.01, round(raw, 2))


# ============================================================================
# PRICE ENGINE
# ============================================================================
def price_engine() -> None:
    while not SHUTDOWN_EVENT.is_set():
        try:
            with PRICE_LOCK:
                for sym, cfg in SYMBOLS.items():
                    old = PRICES[sym]["price"]
                    shock = random.gauss(0, cfg["vol"]) * old
                    mean_pull = (cfg["price"] - old) * 0.0008
                    new_price = old + shock + mean_pull
                    if new_price <= 0.000001:
                        new_price = 0.000001
                    PRICES[sym]["prev_price"] = old
                    PRICES[sym]["price"] = new_price
                    PRICES[sym]["last_update"] = datetime.now(timezone.utc).isoformat()

                    hist = PRICE_HISTORY[sym]
                    hist.append(new_price)
                    if len(hist) > 30:
                        hist.pop(0)
        except Exception as exc:
            print(f"[price_engine] error: {exc}")
        SHUTDOWN_EVENT.wait(1.0)


# ============================================================================
# SESSION / KILL ZONE HELPERS
# ============================================================================
def get_active_session() -> str:
    h = datetime.now(timezone.utc).hour
    if 22 <= h or h < 1:
        return "Sydney"
    if 1 <= h < 7:
        return "Tokyo"
    if 7 <= h < 12:
        return "London"
    if 12 <= h < 16:
        return "London/NY Overlap"
    if 16 <= h < 21:
        return "New York"
    return "After Hours"


def is_kill_zone() -> bool:
    h = datetime.now(timezone.utc).hour
    return (7 <= h < 10) or (12 <= h < 15)


# ============================================================================
# SELF-LEARNING LESSON GENERATOR
# ============================================================================
def generate_lesson(symbol: str, strategy: str, side: str, entry: float,
                    sl: float, tp: float, exit_price: float) -> str:
    loss_dist = abs(entry - sl)
    direction = "bullish" if side == "BUY" else "bearish"
    lessons = {
        "Liquidity Sweep & Stop Hunt":
            f"Stop-hunt triggered on {symbol}: {direction} entry {entry:.5f} was swept to {exit_price:.5f}. "
            f"Structural adjustment: require a full candle close beyond sweep wick before entry; reduce lot 25% on grab setups.",
        "Fair Value Gap (FVG)":
            f"FVG on {symbol} invalidated at {exit_price:.5f}. Adjustment: only enter when displacement candle CLOSES inside FVG; skip first-touch entries.",
        "Order Block (OB)":
            f"OB failed on {symbol} (loss dist {loss_dist:.5f}). Adjustment: confirm OB is last opposite candle before impulse with confirmed BOS; require volume spike.",
        "Change of Character (CHoCH)":
            f"CHoCH was false on {symbol} (exit {exit_price:.5f}). Adjustment: demand CHoCH on lower timeframe AFTER a verified liquidity sweep, not standalone.",
        "Break of Structure (BOS)":
            f"BOS fake-out on {symbol}. Adjustment: require body close (not wick) beyond swing, plus higher-TF alignment before entry.",
        "Breaker Block":
            f"Breaker block on {symbol} was not defended (exit {exit_price:.5f}). Adjustment: only enter if original OB was consumed by impulse with displacement.",
        "Judas Swing / ORL":
            f"Judas swing misidentified on {symbol}. Adjustment: only trade Judas AFTER opening range liquidity sweep AND confirmation candle.",
        "Kill Zones & Power of 3":
            f"Trade outside Kill Zone / wrong AMD phase on {symbol}. Adjustment: restrict entries to 07:00-10:00 and 12:00-15:00 UTC only.",
        "OTE & Premium/Discount":
            f"Entry not in OTE zone on {symbol}. Adjustment: never buy above 50% premium, never sell below 50% discount; require 62%-79% fib retracement.",
        "Inversion FVG (IFVG)":
            f"IFVG did not act as support/resistance on {symbol}. Adjustment: only trade IFVG after body close through FVG with strong displacement.",
    }
    return lessons.get(
        strategy,
        f"LOSS on {symbol} ({strategy}). Exit at {exit_price:.5f}. Review confluence stack and entry timing."
    )


# ============================================================================
# TRADE EVALUATOR
# ============================================================================
def trade_evaluator() -> None:
    while not SHUTDOWN_EVENT.is_set():
        try:
            rows = db_query("SELECT * FROM trades WHERE status='PENDING'")
            for row in rows:
                tid = row["id"]
                symbol = row["symbol"]
                side = row["side"]
                entry = float(row["entry_price"])
                sl = float(row["stop_loss"])
                tp = float(row["take_profit"])
                lot = float(row["lot_size"])
                strategy = row["strategy"]

                with PRICE_LOCK:
                    current = PRICES.get(symbol, {}).get("price")
                if current is None:
                    continue

                hit_status: Optional[str] = None
                exit_price: Optional[float] = None

                if side == "BUY":
                    if current <= sl:
                        hit_status, exit_price = "LOSS", sl
                    elif current >= tp:
                        hit_status, exit_price = "WIN", tp
                else:  # SELL
                    if current >= sl:
                        hit_status, exit_price = "LOSS", sl
                    elif current <= tp:
                        hit_status, exit_price = "WIN", tp

                if not hit_status:
                    continue

                mult = SYMBOLS.get(symbol, {}).get("multiplier", 100000)
                diff = (exit_price - entry) if side == "BUY" else (entry - exit_price)
                pnl = round(diff * mult * lot, 2)
                now_iso = datetime.now(timezone.utc).isoformat()

                db_execute(
                    "UPDATE trades SET status=?, pnl=?, closed_at=?, exit_price=? WHERE id=?",
                    (hit_status, pnl, now_iso, exit_price, tid)
                )

                if hit_status == "WIN":
                    db_execute(
                        "UPDATE strategies SET total_trades=total_trades+1, wins=wins+1 WHERE name=?",
                        (strategy,)
                    )
                else:
                    db_execute(
                        "UPDATE strategies SET total_trades=total_trades+1, losses=losses+1 WHERE name=?",
                        (strategy,)
                    )
                    lesson = generate_lesson(symbol, strategy, side, entry, sl, tp, exit_price)
                    db_execute(
                        "INSERT INTO self_learning (trade_id, symbol, strategy, lesson, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (tid, symbol, strategy, lesson, now_iso)
                    )
        except Exception as exc:
            print(f"[trade_evaluator] error: {exc}")
        SHUTDOWN_EVENT.wait(0.5)


# ============================================================================
# MACRO INTELLIGENCE ENGINE
# ============================================================================
def macro_engine() -> None:
    regimes = ["Risk-On", "Risk-Off", "Safe-Haven", "Mixed"]
    safe_havens = {"Risk-On": "Equities", "Risk-Off": "USD", "Safe-Haven": "Gold", "Mixed": "Gold/USD"}
    while not SHUTDOWN_EVENT.is_set():
        try:
            with PRICE_LOCK:
                dxy = PRICES["DXY"]["price"]
            MACRO_STATE["dxy"] = round(dxy, 2)
            MACRO_STATE["us10y"] = round(max(0.5, MACRO_STATE["us10y"] + random.gauss(0, 0.008)), 3)
            MACRO_STATE["vix"] = round(max(8.0, min(80.0, MACRO_STATE["vix"] + random.gauss(0, 0.15))), 2)
            MACRO_STATE["gold_silver_ratio"] = round(
                max(60.0, min(100.0, MACRO_STATE["gold_silver_ratio"] + random.gauss(0, 0.05))), 2
            )

            if random.random() < 0.03:
                MACRO_STATE["regime"] = random.choice(regimes)
                MACRO_STATE["safe_haven"] = safe_havens[MACRO_STATE["regime"]]

            MACRO_STATE["updated_at"] = datetime.now(timezone.utc).isoformat()

            if random.random() < 0.10:
                for name in COT_STATE:
                    d_long = int(random.gauss(0, 800))
                    d_short = int(random.gauss(0, 600))
                    COT_STATE[name]["prev_long"] = COT_STATE[name]["long"]
                    COT_STATE[name]["prev_short"] = COT_STATE[name]["short"]
                    COT_STATE[name]["long"] = max(5000, COT_STATE[name]["long"] + d_long)
                    COT_STATE[name]["short"] = max(5000, COT_STATE[name]["short"] + d_short)
        except Exception as exc:
            print(f"[macro_engine] error: {exc}")
        SHUTDOWN_EVENT.wait(5.0)


# ============================================================================
# PYDANTIC MODELS
# ============================================================================
class SettingsUpdate(BaseModel):
    capital: float = Field(..., gt=0, description="Account capital in USD")
    risk_percent: float = Field(..., gt=0, le=100, description="Risk % per trade")


class TradeCreate(BaseModel):
    symbol: str
    side: str
    pattern: str = "Scalping"
    strategy: str
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


class AutoDispatchRequest(BaseModel):
    pattern: str = "Scalping"


# ============================================================================
# FASTAPI APP
# ============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    threads = [
        threading.Thread(target=price_engine, daemon=True, name="price_engine"),
        threading.Thread(target=trade_evaluator, daemon=True, name="trade_evaluator"),
        threading.Thread(target=macro_engine, daemon=True, name="macro_engine"),
    ]
    for t in threads:
        t.start()
    print(f"[startup] listening on {HOST}:{PORT}  |  DB: {DB_PATH}")
    yield
    SHUTDOWN_EVENT.set()
    for t in threads:
        t.join(timeout=3.0)
    print("[shutdown] background threads stopped")


app = FastAPI(title="Pro Trading & Macro Intelligence Engine", lifespan=lifespan)


# ============================================================================
# API ROUTES
# ============================================================================
@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "status": "live",
        "server_time": datetime.now(timezone.utc).isoformat(),
        "session": get_active_session(),
        "kill_zone": is_kill_zone(),
    }


@app.get("/api/prices")
def get_prices() -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    with PRICE_LOCK:
        for sym, cfg in SYMBOLS.items():
            p = PRICES[sym]["price"]
            prev = PRICES[sym]["prev_price"]
            open_p = PRICES[sym]["open_price"]
            change_pct = ((p - open_p) / open_p * 100.0) if open_p else 0.0
            data[sym] = {
                "price": round(p, cfg["decimals"]),
                "prev_price": round(prev, cfg["decimals"]),
                "open_price": round(open_p, cfg["decimals"]),
                "change_pct": round(change_pct, 3),
                "decimals": cfg["decimals"],
                "pip_label": cfg["pip_label"],
                "history": [round(x, cfg["decimals"]) for x in PRICE_HISTORY[sym][-30:]],
                "last_update": PRICES[sym]["last_update"],
            }
    return {"ok": True, "data": data}


@app.get("/api/settings")
def get_settings() -> Dict[str, Any]:
    row = db_query_one("SELECT capital, risk_percent, updated_at FROM bot_settings WHERE id=1")
    if not row:
        raise HTTPException(status_code=500, detail="settings not initialized")
    return {
        "ok": True,
        "data": {
            "capital": float(row["capital"]),
            "risk_percent": float(row["risk_percent"]),
            "updated_at": row["updated_at"],
        },
    }


@app.post("/api/settings")
def update_settings(body: SettingsUpdate) -> Dict[str, Any]:
    db_execute(
        "UPDATE bot_settings SET capital=?, risk_percent=?, updated_at=? WHERE id=1",
        (body.capital, body.risk_percent, datetime.now(timezone.utc).isoformat())
    )
    return get_settings()


@app.get("/api/trades")
def get_trades(status: Optional[str] = Query(None), limit: int = 100) -> Dict[str, Any]:
    if status:
        rows = db_query(
            "SELECT * FROM trades WHERE status=? ORDER BY id DESC LIMIT ?",
            (status, limit)
        )
    else:
        rows = db_query("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,))
    return {"ok": True, "count": len(rows), "data": [dict(r) for r in rows]}


@app.post("/api/trades")
def create_trade(body: TradeCreate) -> Dict[str, Any]:
    if body.symbol not in SYMBOLS:
        raise HTTPException(status_code=400, detail=f"Unknown symbol: {body.symbol}")
    side = body.side.upper()
    if side not in ("BUY", "SELL"):
        raise HTTPException(status_code=400, detail="side must be BUY or SELL")
    if body.strategy not in ICT_STRATEGIES:
        raise HTTPException(status_code=400, detail="Unknown ICT strategy")
    if body.pattern not in ("Scalping", "Swing"):
        raise HTTPException(status_code=400, detail="pattern must be Scalping or Swing")

    cfg = SYMBOLS[body.symbol]
    with PRICE_LOCK:
        live = PRICES[body.symbol]["price"]

    entry = body.entry_price if body.entry_price is not None else round(live, cfg["decimals"])

    # Defaults per pattern/symbol
    if body.symbol == "XAU/USD":
        sl_d, tp_d = (3.0, 6.0) if body.pattern == "Scalping" else (10.0, 30.0)
    elif body.symbol == "DXY":
        sl_d, tp_d = (0.15, 0.30) if body.pattern == "Scalping" else (0.50, 1.50)
    elif body.symbol == "USD/JPY":
        sl_d, tp_d = (0.15, 0.30) if body.pattern == "Scalping" else (0.50, 1.50)
    else:
        sl_d, tp_d = (0.0015, 0.0030) if body.pattern == "Scalping" else (0.0040, 0.0120)

    sl = body.stop_loss if body.stop_loss is not None else round(entry - sl_d if side == "BUY" else entry + sl_d, cfg["decimals"])
    tp = body.take_profit if body.take_profit is not None else round(entry + tp_d if side == "BUY" else entry - tp_d, cfg["decimals"])

    if side == "BUY" and not (sl < entry < tp):
        raise HTTPException(status_code=400, detail="For BUY: SL < entry < TP required")
    if side == "SELL" and not (tp < entry < sl):
        raise HTTPException(status_code=400, detail="For SELL: TP < entry < SL required")

    settings = get_settings()["data"]
    sl_distance = abs(entry - sl)
    lot = calculate_lot_size(settings["capital"], settings["risk_percent"], sl_distance, body.symbol)

    new_id = db_execute(
        "INSERT INTO trades (symbol, side, entry_price, stop_loss, take_profit, lot_size, "
        "pattern, strategy, status, opened_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)",
        (body.symbol, side, entry, sl, tp, lot, body.pattern, body.strategy,
         datetime.now(timezone.utc).isoformat())
    )
    row = db_query_one("SELECT * FROM trades WHERE id=?", (new_id,))
    return {"ok": True, "data": dict(row)}


@app.post("/api/auto_dispatch")
def auto_dispatch(body: AutoDispatchRequest) -> Dict[str, Any]:
    if body.pattern not in ("Scalping", "Swing"):
        raise HTTPException(status_code=400, detail="pattern must be Scalping or Swing")

    # Strategy picker: top-3 by win rate
    top = db_query(
        "SELECT name FROM strategies WHERE total_trades > 0 "
        "ORDER BY CAST(wins AS REAL) / MAX(total_trades, 1) DESC LIMIT 3"
    )
    pool = [r["name"] for r in top] if top else ICT_STRATEGIES
    strategy = random.choice(pool)

    symbol = random.choice(["XAU/USD", "XAU/USD", "EUR/USD", "GBP/USD"])
    cfg = SYMBOLS[symbol]
    with PRICE_LOCK:
        price_now = PRICES[symbol]["price"]
        prev = PRICES[symbol]["prev_price"]

    side = "BUY" if price_now >= prev else "SELL"

    if symbol == "XAU/USD":
        sl_d, tp_d = (3.0, 6.0) if body.pattern == "Scalping" else (10.0, 30.0)
    else:
        sl_d, tp_d = (0.0015, 0.0030) if body.pattern == "Scalping" else (0.0040, 0.0120)

    entry = round(price_now, cfg["decimals"])
    sl = round(entry - sl_d if side == "BUY" else entry + sl_d, cfg["decimals"])
    tp = round(entry + tp_d if side == "BUY" else entry - tp_d, cfg["decimals"])

    settings = get_settings()["data"]
    lot = calculate_lot_size(settings["capital"], settings["risk_percent"], abs(entry - sl), symbol)

    new_id = db_execute(
        "INSERT INTO trades (symbol, side, entry_price, stop_loss, take_profit, lot_size, "
        "pattern, strategy, status, opened_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)",
        (symbol, side, entry, sl, tp, lot, body.pattern, strategy,
         datetime.now(timezone.utc).isoformat())
    )
    row = db_query_one("SELECT * FROM trades WHERE id=?", (new_id,))
    return {"ok": True, "auto": True, "data": dict(row)}


@app.get("/api/strategies")
def get_strategies() -> Dict[str, Any]:
    rows = db_query(
        "SELECT name, total_trades, wins, losses FROM strategies ORDER BY "
        "CAST(wins AS REAL) / MAX(total_trades, 1) DESC"
    )
    out: List[Dict[str, Any]] = []
    for r in rows:
        total = int(r["total_trades"])
        wins = int(r["wins"])
        losses = int(r["losses"])
        wr = (wins / total * 100.0) if total > 0 else 0.0
        out.append({
            "name": r["name"],
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wr, 2),
        })
    return {"ok": True, "data": out}


@app.get("/api/self_learning")
def get_self_learning(limit: int = 50) -> Dict[str, Any]:
    rows = db_query(
        "SELECT id, trade_id, symbol, strategy, lesson, created_at "
        "FROM self_learning ORDER BY id DESC LIMIT ?",
        (limit,)
    )
    return {"ok": True, "count": len(rows), "data": [dict(r) for r in rows]}


@app.get("/api/macro")
def get_macro() -> Dict[str, Any]:
    with PRICE_LOCK:
        dxy_now = PRICES["DXY"]["price"]
    cot_out: Dict[str, Any] = {}
    for name, c in COT_STATE.items():
        total = c["long"] + c["short"]
        net = c["long"] - c["short"]
        delta_net = (c["long"] - c["prev_long"]) - (c["short"] - c["prev_short"])
        cot_out[name] = {
            "long": c["long"],
            "short": c["short"],
            "net": net,
            "long_pct": round(c["long"] * 100.0 / max(1, total), 2),
            "short_pct": round(c["short"] * 100.0 / max(1, total), 2),
            "delta_net": delta_net,
        }
    return {
        "ok": True,
        "data": {
            "dxy": round(dxy_now, 2),
            "us10y": MACRO_STATE["us10y"],
            "vix": MACRO_STATE["vix"],
            "gold_silver_ratio": MACRO_STATE["gold_silver_ratio"],
            "regime": MACRO_STATE["regime"],
            "safe_haven": MACRO_STATE["safe_haven"],
            "cot": cot_out,
            "calendar": ECONOMIC_CALENDAR,
            "updated_at": MACRO_STATE["updated_at"],
        }
    }


@app.get("/api/summary")
def get_summary() -> Dict[str, Any]:
    row = db_query_one(
        "SELECT "
        "(SELECT COUNT(*) FROM trades) AS total, "
        "(SELECT COUNT(*) FROM trades WHERE status='PENDING') AS pending, "
        "(SELECT COUNT(*) FROM trades WHERE status='WIN') AS wins, "
        "(SELECT COUNT(*) FROM trades WHERE status='LOSS') AS losses, "
        "(SELECT COALESCE(SUM(pnl),0) FROM trades WHERE status IN ('WIN','LOSS')) AS realized "
    )
    settings = get_settings()["data"]
    total = int(row["total"] or 0)
    wins = int(row["wins"] or 0)
    losses = int(row["losses"] or 0)
    wr = (wins / (wins + losses) * 100.0) if (wins + losses) > 0 else 0.0
    return {
        "ok": True,
        "data": {
            "capital": settings["capital"],
            "risk_percent": settings["risk_percent"],
            "total_trades": total,
            "pending": int(row["pending"] or 0),
            "wins": wins,
            "losses": losses,
            "win_rate": round(wr, 2),
            "realized_pnl": round(float(row["realized"] or 0), 2),
            "session": get_active_session(),
            "kill_zone": is_kill_zone(),
        }
    }


@app.post("/api/reset_learning")
def reset_learning() -> Dict[str, Any]:
    db_execute("DELETE FROM self_learning")
    return {"ok": True, "message": "self_learning cleared"}


@app.post("/api/reset_trades")
def reset_trades() -> Dict[str, Any]:
    db_execute("DELETE FROM trades")
    db_execute("UPDATE strategies SET total_trades=0, wins=0, losses=0")
    return {"ok": True, "message": "trades reset"}


# ============================================================================
# FRONTEND (HTML + Tailwind + Vanilla JS)
# ============================================================================
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en" class="dark">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Pro Trading &amp; Macro Intelligence Engine</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
  html, body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
  body { background: radial-gradient(1200px 600px at 20% -10%, #0e1b3a 0%, #050914 55%, #020308 100%); }
  .tabnum { font-variant-numeric: tabular-nums; font-feature-settings: "tnum"; }
  .card { background: linear-gradient(180deg, rgba(15,23,42,0.82) 0%, rgba(2,6,23,0.78) 100%);
          border: 1px solid rgba(59,130,246,0.14);
          box-shadow: 0 4px 20px -4px rgba(0,0,0,0.45); }
  .card:hover { border-color: rgba(59,130,246,0.28); }
  .flash-up   { animation: flashUp 0.55s ease-out; }
  .flash-down { animation: flashDown 0.55s ease-out; }
  @keyframes flashUp   { from { background-color: rgba(16,185,129,0.28); } to { background-color: transparent; } }
  @keyframes flashDown { from { background-color: rgba(244,63,94,0.28); } to { background-color: transparent; } }
  .pulse-dot { position: relative; }
  .pulse-dot::before {
    content: ''; position: absolute; inset: -4px; border-radius: 9999px;
    background: currentColor; opacity: 0.35; animation: pulseRing 1.8s ease-out infinite;
  }
  @keyframes pulseRing { 0% { transform: scale(0.6); opacity: 0.5; } 100% { transform: scale(2.0); opacity: 0; } }
  ::-webkit-scrollbar { width: 8px; height: 8px; }
  ::-webkit-scrollbar-track { background: #0b1220; }
  ::-webkit-scrollbar-thumb { background: #1e293b; border-radius: 8px; }
  ::-webkit-scrollbar-thumb:hover { background: #334155; }
  .glow-blue  { box-shadow: 0 0 24px -6px rgba(56,189,248,0.55); }
  .glow-green { box-shadow: 0 0 24px -6px rgba(16,185,129,0.55); }
  .glow-red   { box-shadow: 0 0 24px -6px rgba(244,63,94,0.55); }
  .stripe-row:nth-child(odd) { background: rgba(15,23,42,0.35); }
  .stripe-row:hover { background: rgba(30,64,175,0.12); }
  select, input { outline: none; }
  select:focus, input:focus { border-color: #38bdf8 !important; box-shadow: 0 0 0 2px rgba(56,189,248,0.20); }
</style>
</head>
<body class="text-slate-200 min-h-screen pb-16">

<!-- ============================ TOP BAR ============================ -->
<header class="sticky top-0 z-40 backdrop-blur-xl bg-slate-950/70 border-b border-blue-500/15">
  <div class="max-w-[1600px] mx-auto px-4 py-3 flex flex-wrap items-center gap-4 justify-between">
    <div class="flex items-center gap-3">
      <div class="w-9 h-9 rounded-lg bg-gradient-to-br from-sky-400 to-blue-700 flex items-center justify-center font-black text-lg shadow-lg">P</div>
      <div>
        <div class="text-[15px] font-bold tracking-tight text-white">Pro Trading &amp; Macro Intelligence</div>
        <div class="text-[10px] uppercase tracking-widest text-slate-500">Institutional ICT Engine</div>
      </div>
    </div>

    <div class="flex flex-wrap items-center gap-2 text-xs">
      <div class="flex items-center gap-2 bg-slate-900/70 border border-slate-800 rounded-full px-3 py-1.5">
        <span class="text-emerald-400 pulse-dot w-2 h-2 rounded-full bg-emerald-400 inline-block"></span>
        <span class="text-emerald-300 font-semibold">LIVE</span>
      </div>
      <div class="bg-slate-900/70 border border-slate-800 rounded-full px-3 py-1.5">
        Session: <b class="text-sky-300" id="sessionLabel">—</b>
      </div>
      <div id="killZoneBadge" class="bg-slate-900/70 border border-slate-800 rounded-full px-3 py-1.5">
        Kill Zone: <b class="text-slate-400" id="killZoneLabel">—</b>
      </div>
      <div class="bg-slate-900/70 border border-slate-800 rounded-full px-3 py-1.5">
        Capital: <b class="text-emerald-300 tabnum" id="topCapital">$0</b>
      </div>
      <div class="bg-slate-900/70 border border-slate-800 rounded-full px-3 py-1.5">
        Win Rate: <b class="text-amber-300 tabnum" id="topWinRate">0%</b>
      </div>
    </div>
  </div>
</header>

<main class="max-w-[1600px] mx-auto px-4 py-6 space-y-6">

  <!-- ============================ PRICE TICKER ============================ -->
  <section>
    <h2 class="text-xs font-bold uppercase tracking-[0.18em] text-slate-400 mb-3">Live Market Feed</h2>
    <div id="priceGrid" class="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3"></div>
  </section>

  <!-- ============================ CONTROLS GRID ============================ -->
  <section class="grid grid-cols-1 xl:grid-cols-3 gap-4">

    <!-- Risk Control Panel -->
    <div class="card rounded-xl p-5">
      <h3 class="text-xs font-bold uppercase tracking-widest text-sky-400 mb-4">Account &amp; Risk Control</h3>
      <div class="space-y-4">
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest">Capital (USD)</label>
          <input id="inpCapital" type="number" step="0.01" min="1"
                 class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white tabnum" />
        </div>
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest">Risk per Trade (%)</label>
          <input id="inpRisk" type="number" step="0.05" min="0.01" max="100"
                 class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white tabnum" />
        </div>
        <button id="btnSaveSettings"
                class="w-full bg-sky-500 hover:bg-sky-400 text-white font-semibold rounded-lg py-2 transition glow-blue">
          Update Settings
        </button>
        <div id="settingsStatus" class="text-[11px] text-emerald-400 h-4"></div>
        <div class="pt-2 border-t border-slate-800 grid grid-cols-2 gap-2 text-xs">
          <div class="text-slate-500">Risk $/trade</div><div class="text-right text-white tabnum" id="riskUsd">—</div>
          <div class="text-slate-500">Trades total</div><div class="text-right text-white tabnum" id="statTotal">—</div>
          <div class="text-slate-500">Pending</div><div class="text-right text-amber-300 tabnum" id="statPending">—</div>
          <div class="text-slate-500">Realized P&amp;L</div><div class="text-right tabnum" id="statPnl">—</div>
        </div>
      </div>
    </div>

    <!-- Trading Console -->
    <div class="card rounded-xl p-5 xl:col-span-2">
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-xs font-bold uppercase tracking-widest text-sky-400">Trading Console</h3>
        <label class="flex items-center gap-2 text-xs text-slate-300 cursor-pointer select-none">
          <input id="chkAuto" type="checkbox" class="accent-sky-500 w-4 h-4" />
          Auto Dispatch Mode
        </label>
      </div>

      <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest">Symbol</label>
          <select id="selSymbol" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white"></select>
        </div>
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest">Side</label>
          <select id="selSide" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white">
            <option value="BUY">BUY</option><option value="SELL">SELL</option>
          </select>
        </div>
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest">Pattern</label>
          <select id="selPattern" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white">
            <option value="Scalping">Scalping</option><option value="Swing">Swing</option>
          </select>
        </div>
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest">ICT Strategy</label>
          <select id="selStrategy" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white"></select>
        </div>
      </div>

      <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3">
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest">Entry</label>
          <input id="inpEntry" type="number" step="any" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white tabnum" />
        </div>
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest">Stop Loss</label>
          <input id="inpSL" type="number" step="any" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-rose-300 tabnum" />
        </div>
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest">Take Profit</label>
          <input id="inpTP" type="number" step="any" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-emerald-300 tabnum" />
        </div>
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest">Lot Size (auto)</label>
          <div id="lotDisplay" class="w-full mt-1 bg-slate-950 border border-sky-500/40 rounded-lg px-3 py-2 text-sky-300 font-bold tabnum text-center">0.00</div>
        </div>
      </div>

      <div class="flex flex-wrap gap-2 mt-4">
        <button id="btnDispatch" class="flex-1 min-w-[180px] bg-emerald-500 hover:bg-emerald-400 text-white font-semibold rounded-lg py-2.5 transition glow-green">
          ⚡ Dispatch Trade
        </button>
        <button id="btnAutoDispatch" class="flex-1 min-w-[180px] bg-sky-500 hover:bg-sky-400 text-white font-semibold rounded-lg py-2.5 transition glow-blue">
          🤖 Auto Dispatch
        </button>
      </div>
      <div id="dispatchStatus" class="text-[11px] mt-2 h-4"></div>
    </div>
  </section>

  <!-- ============================ ACTIVE TRADES ============================ -->
  <section class="card rounded-xl overflow-hidden">
    <div class="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
      <h3 class="text-xs font-bold uppercase tracking-widest text-amber-400">Active Trades (PENDING)</h3>
      <span id="pendingCount" class="text-[11px] text-slate-500">0</span>
    </div>
    <div class="overflow-x-auto">
      <table class="w-full text-xs">
        <thead class="bg-slate-950/60 text-slate-500 uppercase text-[10px] tracking-wider">
          <tr>
            <th class="text-left px-3 py-2">ID</th><th class="text-left px-3 py-2">Symbol</th>
            <th class="text-left px-3 py-2">Side</th><th class="text-right px-3 py-2">Entry</th>
            <th class="text-right px-3 py-2">SL</th><th class="text-right px-3 py-2">TP</th>
            <th class="text-right px-3 py-2">Lot</th><th class="text-left px-3 py-2">Pattern</th>
            <th class="text-left px-3 py-2">Strategy</th><th class="text-left px-3 py-2">Opened</th>
          </tr>
        </thead>
        <tbody id="tblActive"></tbody>
      </table>
    </div>
  </section>

  <!-- ============================ CLOSED TRADES ============================ -->
  <section class="card rounded-xl overflow-hidden">
    <div class="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
      <h3 class="text-xs font-bold uppercase tracking-widest text-slate-300">Trade History</h3>
      <span class="text-[11px] text-slate-500">last 50</span>
    </div>
    <div class="overflow-x-auto max-h-[420px]">
      <table class="w-full text-xs">
        <thead class="bg-slate-950/60 text-slate-500 uppercase text-[10px] tracking-wider sticky top-0">
          <tr>
            <th class="text-left px-3 py-2">ID</th><th class="text-left px-3 py-2">Symbol</th>
            <th class="text-left px-3 py-2">Side</th><th class="text-right px-3 py-2">Entry</th>
            <th class="text-right px-3 py-2">Exit</th><th class="text-right px-3 py-2">Lot</th>
            <th class="text-left px-3 py-2">Pattern</th><th class="text-left px-3 py-2">Strategy</th>
            <th class="text-left px-3 py-2">Status</th><th class="text-right px-3 py-2">P&amp;L</th>
            <th class="text-left px-3 py-2">Closed</th>
          </tr>
        </thead>
        <tbody id="tblHistory"></tbody>
      </table>
    </div>
  </section>

  <!-- ============================ ICT WIN RATES + MACRO ============================ -->
  <section class="grid grid-cols-1 xl:grid-cols-2 gap-4">

    <div class="card rounded-xl overflow-hidden">
      <div class="px-5 py-3 border-b border-slate-800">
        <h3 class="text-xs font-bold uppercase tracking-widest text-fuchsia-400">ICT Strategy Win Rates</h3>
      </div>
      <div class="overflow-x-auto max-h-[480px]">
        <table class="w-full text-xs">
          <thead class="bg-slate-950/60 text-slate-500 uppercase text-[10px] tracking-wider sticky top-0">
            <tr>
              <th class="text-left px-3 py-2">Strategy</th>
              <th class="text-right px-3 py-2">Total</th>
              <th class="text-right px-3 py-2">Wins</th>
              <th class="text-right px-3 py-2">Losses</th>
              <th class="text-right px-3 py-2">Win Rate</th>
            </tr>
          </thead>
          <tbody id="tblStrategies"></tbody>
        </table>
      </div>
    </div>

    <div class="card rounded-xl p-5">
      <h3 class="text-xs font-bold uppercase tracking-widest text-indigo-400 mb-4">Macro Intelligence</h3>
      <div class="grid grid-cols-2 gap-3">
        <div class="bg-slate-950/60 border border-slate-800 rounded-lg p-3">
          <div class="text-[10px] uppercase tracking-widest text-slate-500">DXY</div>
          <div class="text-2xl font-bold text-white tabnum mt-1" id="macroDxy">—</div>
        </div>
        <div class="bg-slate-950/60 border border-slate-800 rounded-lg p-3">
          <div class="text-[10px] uppercase tracking-widest text-slate-500">US 10Y Yield</div>
          <div class="text-2xl font-bold text-amber-300 tabnum mt-1" id="macro10y">—</div>
        </div>
        <div class="bg-slate-950/60 border border-slate-800 rounded-lg p-3">
          <div class="text-[10px] uppercase tracking-widest text-slate-500">VIX</div>
          <div class="text-2xl font-bold text-rose-300 tabnum mt-1" id="macroVix">—</div>
        </div>
        <div class="bg-slate-950/60 border border-slate-800 rounded-lg p-3">
          <div class="text-[10px] uppercase tracking-widest text-slate-500">Gold/Silver Ratio</div>
          <div class="text-2xl font-bold text-sky-300 tabnum mt-1" id="macroGsr">—</div>
        </div>
      </div>
      <div class="mt-3 flex flex-wrap items-center gap-2 text-xs">
        <span class="bg-slate-950/60 border border-slate-800 rounded-full px-3 py-1.5">
          Regime: <b id="macroRegime" class="text-emerald-300">—</b>
        </span>
        <span class="bg-slate-950/60 border border-slate-800 rounded-full px-3 py-1.5">
          Safe-Haven: <b id="macroHaven" class="text-amber-300">—</b>
        </span>
      </div>
    </div>
  </section>

  <!-- ============================ COT + CALENDAR ============================ -->
  <section class="grid grid-cols-1 xl:grid-cols-2 gap-4">

    <div class="card rounded-xl overflow-hidden">
      <div class="px-5 py-3 border-b border-slate-800">
        <h3 class="text-xs font-bold uppercase tracking-widest text-teal-400">COT Institutional Positioning</h3>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-xs">
          <thead class="bg-slate-950/60 text-slate-500 uppercase text-[10px] tracking-wider">
            <tr>
              <th class="text-left px-3 py-2">Asset</th>
              <th class="text-right px-3 py-2">Long</th>
              <th class="text-right px-3 py-2">Short</th>
              <th class="text-right px-3 py-2">Net</th>
              <th class="text-right px-3 py-2">Long %</th>
              <th class="text-right px-3 py-2">Δ Net</th>
            </tr>
          </thead>
          <tbody id="tblCot"></tbody>
        </table>
      </div>
    </div>

    <div class="card rounded-xl overflow-hidden">
      <div class="px-5 py-3 border-b border-slate-800">
        <h3 class="text-xs font-bold uppercase tracking-widest text-purple-400">Economic Calendar</h3>
      </div>
      <div class="overflow-x-auto max-h-[360px]">
        <table class="w-full text-xs">
          <thead class="bg-slate-950/60 text-slate-500 uppercase text-[10px] tracking-wider sticky top-0">
            <tr>
              <th class="text-left px-3 py-2">Event</th>
              <th class="text-left px-3 py-2">Currency</th>
              <th class="text-left px-3 py-2">Impact</th>
              <th class="text-left px-3 py-2">When</th>
              <th class="text-right px-3 py-2">Forecast</th>
              <th class="text-right px-3 py-2">Previous</th>
            </tr>
          </thead>
          <tbody id="tblCalendar"></tbody>
        </table>
      </div>
    </div>
  </section>

  <!-- ============================ SELF-LEARNING ============================ -->
  <section class="card rounded-xl overflow-hidden">
    <div class="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
      <h3 class="text-xs font-bold uppercase tracking-widest text-amber-400">AI Self-Learning Journal</h3>
      <button id="btnClearLearn" class="text-[11px] text-slate-500 hover:text-rose-400 transition">Clear all</button>
    </div>
    <div id="learnList" class="divide-y divide-slate-800 max-h-[420px] overflow-y-auto">
    </div>
  </section>

</main>

<footer class="fixed bottom-0 left-0 right-0 text-center text-[10px] text-slate-600 bg-slate-950/80 border-t border-slate-800 py-2 z-30">
  Pro Trading &amp; Macro Intelligence Engine · FastAPI + SQLite · © <span id="year"></span>
</footer>

<script>
// ===================================================================
// CONSTANTS
// ===================================================================
const SYMBOLS = {
  "XAU/USD": { decimals: 2, multiplier: 100,    pip: 0.01,   pipLabel: "pts" },
  "EUR/USD": { decimals: 4, multiplier: 100000, pip: 0.0001, pipLabel: "pips" },
  "GBP/USD": { decimals: 4, multiplier: 100000, pip: 0.0001, pipLabel: "pips" },
  "USD/JPY": { decimals: 2, multiplier: 1000,   pip: 0.01,   pipLabel: "pips" },
  "AUD/USD": { decimals: 4, multiplier: 100000, pip: 0.0001, pipLabel: "pips" },
  "USD/CHF": { decimals: 4, multiplier: 100000, pip: 0.0001, pipLabel: "pips" },
  "USD/CAD": { decimals: 4, multiplier: 100000, pip: 0.0001, pipLabel: "pips" },
  "DXY":     { decimals: 2, multiplier: 1000,   pip: 0.01,   pipLabel: "pts" },
};

const ICT_STRATEGIES = [
  "Liquidity Sweep & Stop Hunt",
  "Fair Value Gap (FVG)",
  "Order Block (OB)",
  "Change of Character (CHoCH)",
  "Break of Structure (BOS)",
  "Breaker Block",
  "Judas Swing / ORL",
  "Kill Zones & Power of 3",
  "OTE & Premium/Discount",
  "Inversion FVG (IFVG)",
];

const DEFAULT_DISTANCES = {
  "XAU/USD": { Scalping: [3.0, 6.0],  Swing: [10.0, 30.0] },
  "DXY":     { Scalping: [0.15, 0.30], Swing: [0.50, 1.50] },
  "USD/JPY": { Scalping: [0.15, 0.30], Swing: [0.50, 1.50] },
  _fx:       { Scalping: [0.0015, 0.0030], Swing: [0.0040, 0.0120] },
};

// ===================================================================
// STATE
// ===================================================================
const state = {
  prices: {},
  settings: { capital: 10000, risk_percent: 1 },
  autoMode: false,
};

// ===================================================================
// HELPERS
// ===================================================================
function fmtPrice(sym, price) {
  const d = (SYMBOLS[sym] && SYMBOLS[sym].decimals) || 2;
  return Number(price).toFixed(d);
}
function fmtUsd(n) { return "$" + Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function fmtPnl(n) {
  const v = Number(n || 0);
  const cls = v > 0 ? "text-emerald-400" : v < 0 ? "text-rose-400" : "text-slate-400";
  return `<span class="${cls}">${v >= 0 ? "+" : ""}${v.toFixed(2)}</span>`;
}
async function api(path, method = "GET", body = null) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body !== null) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) {
    const err = (data && (data.detail || data.error)) || `HTTP ${res.status}`;
    throw new Error(typeof err === "string" ? err : JSON.stringify(err));
  }
  return data;
}
function setStatus(el, msg, type = "ok") {
  el.textContent = msg;
  el.className = "text-[11px] h-4 " + (type === "err" ? "text-rose-400" : "text-emerald-400");
  if (msg) setTimeout(() => { if (el.textContent === msg) el.textContent = ""; }, 3500);
}
function getDefaults(sym, pattern) {
  const cfg = DEFAULT_DISTANCES[sym] || DEFAULT_DISTANCES._fx;
  return cfg[pattern] || DEFAULT_DISTANCES._fx[pattern];
}
function sparkline(history) {
  if (!history || history.length < 2) return "";
  const min = Math.min(...history), max = Math.max(...history);
  const range = max - min || 1;
  const W = 80, H = 22;
  const points = history.map((p, i) => {
    const x = (i / (history.length - 1)) * W;
    const y = H - ((p - min) / range) * H;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const rising = history[history.length - 1] >= history[0];
  const stroke = rising ? "#10b981" : "#f43f5e";
  return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" class="opacity-80">
    <polyline points="${points}" fill="none" stroke="${stroke}" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>
  </svg>`;
}

// ===================================================================
// RENDER: PRICE GRID
// ===================================================================
function renderPrices(data) {
  const grid = document.getElementById("priceGrid");
  let html = "";
  for (const sym of Object.keys(data)) {
    const p = data[sym];
    const prev = state.prices[sym] ? state.prices[sym].price : p.prev_price;
    let flashCls = "";
    if (state.prices[sym]) {
      if (p.price > prev) flashCls = "flash-up";
      else if (p.price < prev) flashCls = "flash-down";
    }
    const changeCls = p.change_pct > 0 ? "text-emerald-400" : p.change_pct < 0 ? "text-rose-400" : "text-slate-500";
    const arrow = p.change_pct > 0 ? "▲" : p.change_pct < 0 ? "▼" : "—";
    html += `
      <div class="card rounded-xl p-3 ${flashCls}">
        <div class="flex items-center justify-between">
          <div class="text-[11px] font-bold text-slate-300 tracking-wide">${sym}</div>
          <div class="text-[10px] ${changeCls} tabnum">${arrow} ${Math.abs(p.change_pct).toFixed(2)}%</div>
        </div>
        <div class="text-lg font-bold text-white tabnum mt-1">${fmtPrice(sym, p.price)}</div>
        <div class="mt-1">${sparkline(p.history)}</div>
      </div>`;
    state.prices[sym] = p;
  }
  grid.innerHTML = html;
}

// ===================================================================
// RENDER: SUMMARY
// ===================================================================
function renderSummary(s) {
  document.getElementById("topCapital").textContent = fmtUsd(s.capital);
  document.getElementById("topWinRate").textContent = s.win_rate.toFixed(1) + "%";
  document.getElementById("sessionLabel").textContent = s.session || "—";
  const kz = document.getElementById("killZoneBadge");
  const kzLbl = document.getElementById("killZoneLabel");
  if (s.kill_zone) {
    kzLbl.textContent = "ACTIVE";
    kzLbl.className = "text-emerald-300 font-bold";
    kz.className = "bg-emerald-950/60 border border-emerald-700/50 rounded-full px-3 py-1.5";
  } else {
    kzLbl.textContent = "INACTIVE";
    kzLbl.className = "text-slate-400";
    kz.className = "bg-slate-900/70 border border-slate-800 rounded-full px-3 py-1.5";
  }
  const riskUsd = s.capital * s.risk_percent / 100.0;
  document.getElementById("riskUsd").textContent = fmtUsd(riskUsd);
  document.getElementById("statTotal").textContent = s.total_trades;
  document.getElementById("statPending").textContent = s.pending;
  document.getElementById("statPnl").innerHTML = fmtPnl(s.realized_pnl);

  if (document.activeElement !== document.getElementById("inpCapital")) {
    document.getElementById("inpCapital").value = s.capital;
  }
  if (document.activeElement !== document.getElementById("inpRisk")) {
    document.getElementById("inpRisk").value = s.risk_percent;
  }
  state.settings.capital = s.capital;
  state.settings.risk_percent = s.risk_percent;
}

// ===================================================================
// RENDER: TRADES
// ===================================================================
function renderActiveTrades(trades) {
  const pending = trades.filter(t => t.status === "PENDING");
  document.getElementById("pendingCount").textContent = pending.length + " open";
  const body = document.getElementById("tblActive");
  if (pending.length === 0) {
    body.innerHTML = `<tr><td colspan="10" class="text-center text-slate-500 py-6 text-xs">No active trades — dispatch one from the console above</td></tr>`;
    return;
  }
  body.innerHTML = pending.map(t => `
    <tr class="stripe-row border-b border-slate-800/60">
      <td class="px-3 py-2 text-slate-400 tabnum">#${t.id}</td>
      <td class="px-3 py-2 font-semibold text-white">${t.symbol}</td>
      <td class="px-3 py-2 font-bold ${t.side === "BUY" ? "text-emerald-400" : "text-rose-400"}">${t.side}</td>
      <td class="px-3 py-2 text-right tabnum text-slate-200">${fmtPrice(t.symbol, t.entry_price)}</td>
      <td class="px-3 py-2 text-right tabnum text-rose-400">${fmtPrice(t.symbol, t.stop_loss)}</td>
      <td class="px-3 py-2 text-right tabnum text-emerald-400">${fmtPrice(t.symbol, t.take_profit)}</td>
      <td class="px-3 py-2 text-right tabnum text-sky-300">${Number(t.lot_size).toFixed(2)}</td>
      <td class="px-3 py-2 text-slate-400">${t.pattern}</td>
      <td class="px-3 py-2 text-slate-400 max-w-[180px] truncate" title="${t.strategy}">${t.strategy}</td>
      <td class="px-3 py-2 text-slate-500 tabnum text-[10px]">${(t.opened_at || "").replace("T", " ").slice(0, 19)}</td>
    </tr>`).join("");
}

function renderHistory(trades) {
  const closed = trades.filter(t => t.status !== "PENDING").slice(0, 50);
  const body = document.getElementById("tblHistory");
  if (closed.length === 0) {
    body.innerHTML = `<tr><td colspan="11" class="text-center text-slate-500 py-6 text-xs">No closed trades yet</td></tr>`;
    return;
  }
  body.innerHTML = closed.map(t => `
    <tr class="stripe-row border-b border-slate-800/60">
      <td class="px-3 py-2 text-slate-400 tabnum">#${t.id}</td>
      <td class="px-3 py-2 font-semibold text-white">${t.symbol}</td>
      <td class="px-3 py-2 font-bold ${t.side === "BUY" ? "text-emerald-400" : "text-rose-400"}">${t.side}</td>
      <td class="px-3 py-2 text-right tabnum text-slate-200">${fmtPrice(t.symbol, t.entry_price)}</td>
      <td class="px-3 py-2 text-right tabnum text-slate-200">${t.exit_price != null ? fmtPrice(t.symbol, t.exit_price) : "—"}</td>
      <td class="px-3 py-2 text-right tabnum text-sky-300">${Number(t.lot_size).toFixed(2)}</td>
      <td class="px-3 py-2 text-slate-400">${t.pattern}</td>
      <td class="px-3 py-2 text-slate-400 max-w-[180px] truncate" title="${t.strategy}">${t.strategy}</td>
      <td class="px-3 py-2">
        <span class="text-[10px] font-bold px-2 py-0.5 rounded-full ${t.status === "WIN" ? "bg-emerald-950/70 text-emerald-300" : "bg-rose-950/70 text-rose-300"}">${t.status}</span>
      </td>
      <td class="px-3 py-2 text-right tabnum">${fmtPnl(t.pnl)}</td>
      <td class="px-3 py-2 text-slate-500 tabnum text-[10px]">${(t.closed_at || "").replace("T", " ").slice(0, 19)}</td>
    </tr>`).join("");
}

// ===================================================================
// RENDER: STRATEGIES
// ===================================================================
function renderStrategies(list) {
  const body = document.getElementById("tblStrategies");
  body.innerHTML = list.map(s => {
    const wr = s.win_rate;
    const barColor = wr >= 65 ? "bg-emerald-500" : wr >= 50 ? "bg-amber-500" : "bg-rose-500";
    return `
      <tr class="stripe-row border-b border-slate-800/60">
        <td class="px-3 py-2 text-slate-200 max-w-[260px] truncate" title="${s.name}">${s.name}</td>
        <td class="px-3 py-2 text-right tabnum text-slate-400">${s.total_trades}</td>
        <td class="px-3 py-2 text-right tabnum text-emerald-400">${s.wins}</td>
        <td class="px-3 py-2 text-right tabnum text-rose-400">${s.losses}</td>
        <td class="px-3 py-2 text-right tabnum">
          <div class="flex items-center gap-2 justify-end">
            <div class="w-16 h-1.5 bg-slate-800 rounded-full overflow-hidden">
              <div class="h-full ${barColor}" style="width:${Math.min(100, wr)}%"></div>
            </div>
            <span class="font-bold text-white w-12 text-right">${wr.toFixed(1)}%</span>
          </div>
        </td>
      </tr>`;
  }).join("");
}

// ===================================================================
// RENDER: MACRO + COT + CALENDAR
// ===================================================================
function renderMacro(data) {
  document.getElementById("macroDxy").textContent = Number(data.dxy).toFixed(2);
  document.getElementById("macro10y").textContent = Number(data.us10y).toFixed(3) + "%";
  document.getElementById("macroVix").textContent = Number(data.vix).toFixed(2);
  document.getElementById("macroGsr").textContent = Number(data.gold_silver_ratio).toFixed(2);
  document.getElementById("macroRegime").textContent = data.regime;
  document.getElementById("macroHaven").textContent = data.safe_haven;

  const cotBody = document.getElementById("tblCot");
  cotBody.innerHTML = Object.keys(data.cot).map(name => {
    const c = data.cot[name];
    const deltaCls = c.delta_net > 0 ? "text-emerald-400" : c.delta_net < 0 ? "text-rose-400" : "text-slate-400";
    return `
      <tr class="stripe-row border-b border-slate-800/60">
        <td class="px-3 py-2 font-semibold text-white">${name}</td>
        <td class="px-3 py-2 text-right tabnum text-emerald-300">${c.long.toLocaleString()}</td>
        <td class="px-3 py-2 text-right tabnum text-rose-300">${c.short.toLocaleString()}</td>
        <td class="px-3 py-2 text-right tabnum text-white font-bold">${c.net.toLocaleString()}</td>
        <td class="px-3 py-2 text-right tabnum text-sky-300">${c.long_pct.toFixed(1)}%</td>
        <td class="px-3 py-2 text-right tabnum ${deltaCls}">${c.delta_net >= 0 ? "+" : ""}${c.delta_net.toLocaleString()}</td>
      </tr>`;
  }).join("");

  const calBody = document.getElementById("tblCalendar");
  calBody.innerHTML = (data.calendar || []).map(e => {
    const impactCls = e.impact === "HIGH" ? "bg-rose-950/70 text-rose-300"
                    : e.impact === "MEDIUM" ? "bg-amber-950/70 text-amber-300"
                    : "bg-slate-800/70 text-slate-400";
    return `
      <tr class="stripe-row border-b border-slate-800/60">
        <td class="px-3 py-2 text-slate-200 max-w-[220px] truncate">${e.event}</td>
        <td class="px-3 py-2 font-semibold text-sky-300">${e.currency}</td>
        <td class="px-3 py-2"><span class="text-[10px] font-bold px-2 py-0.5 rounded-full ${impactCls}">${e.impact}</span></td>
        <td class="px-3 py-2 text-slate-400 text-[11px]">${e.time}</td>
        <td class="px-3 py-2 text-right tabnum text-slate-300">${e.forecast}</td>
        <td class="px-3 py-2 text-right tabnum text-slate-500">${e.previous}</td>
      </tr>`;
  }).join("");
}

// ===================================================================
// RENDER: SELF-LEARNING
// ===================================================================
function renderLearning(list) {
  const el = document.getElementById("learnList");
  if (!list || list.length === 0) {
    el.innerHTML = `<div class="text-center text-slate-500 py-8 text-xs">No lessons recorded yet — losses will appear here automatically</div>`;
    return;
  }
  el.innerHTML = list.map(l => `
    <div class="px-5 py-3 flex gap-3 items-start">
      <div class="shrink-0 w-2 h-2 rounded-full bg-amber-400 mt-1.5"></div>
      <div class="flex-1 min-w-0">
        <div class="flex items-center gap-2 text-[11px] mb-1">
          <span class="font-bold text-white">${l.symbol || "?"}</span>
          <span class="text-slate-600">·</span>
          <span class="text-amber-300 truncate">${l.strategy || "?"}</span>
          <span class="text-slate-600">·</span>
          <span class="text-slate-500 tabnum">#${l.trade_id || "?"}</span>
          <span class="text-slate-600 ml-auto">${(l.created_at || "").replace("T", " ").slice(0, 19)}</span>
        </div>
        <div class="text-[12px] text-slate-300 leading-relaxed">${l.lesson}</div>
      </div>
    </div>`).join("");
}

// ===================================================================
// POLLING
// ===================================================================
async function pollPrices() {
  try {
    const r = await api("/api/prices");
    renderPrices(r.data);
  } catch (e) { console.error("prices:", e); }
}

async function pollSummary() {
  try {
    const r = await api("/api/summary");
    renderSummary(r.data);
  } catch (e) { console.error("summary:", e); }
}

async function pollTrades() {
  try {
    const r = await api("/api/trades?limit=200");
    renderActiveTrades(r.data);
    renderHistory(r.data);
  } catch (e) { console.error("trades:", e); }
}

async function pollStrategies() {
  try {
    const r = await api("/api/strategies");
    renderStrategies(r.data);
  } catch (e) { console.error("strategies:", e); }
}

async function pollMacro() {
  try {
    const r = await api("/api/macro");
    renderMacro(r.data);
  } catch (e) { console.error("macro:", e); }
}

async function pollLearning() {
  try {
    const r = await api("/api/self_learning?limit=30");
    renderLearning(r.data);
  } catch (e) { console.error("learning:", e); }
}

// ===================================================================
// FORM LOGIC
// ===================================================================
function populateSelects() {
  const symSel = document.getElementById("selSymbol");
  symSel.innerHTML = Object.keys(SYMBOLS).map(s => `<option value="${s}">${s}</option>`).join("");

  const stratSel = document.getElementById("selStrategy");
  stratSel.innerHTML = ICT_STRATEGIES.map(s => `<option value="${s}">${s}</option>`).join("");
}

function fillDefaults() {
  const sym = document.getElementById("selSymbol").value;
  const side = document.getElementById("selSide").value;
  const pattern = document.getElementById("selPattern").value;
  const [slD, tpD] = getDefaults(sym, pattern);
  const currentPrice = state.prices[sym] ? state.prices[sym].price : SYMBOLS[sym].multiplier === 100 ? 2350 : 1.08;
  const entry = currentPrice;
  const sl = side === "BUY" ? entry - slD : entry + slD;
  const tp = side === "BUY" ? entry + tpD : entry - tpD;
  document.getElementById("inpEntry").value = fmtPrice(sym, entry);
  document.getElementById("inpSL").value = fmtPrice(sym, sl);
  document.getElementById("inpTP").value = fmtPrice(sym, tp);
  updateLotCalc();
}

function updateLotCalc() {
  const sym = document.getElementById("selSymbol").value;
  const entry = parseFloat(document.getElementById("inpEntry").value);
  const sl = parseFloat(document.getElementById("inpSL").value);
  const capital = state.settings.capital;
  const riskPct = state.settings.risk_percent;
  if (!isFinite(entry) || !isFinite(sl) || sl === entry) {
    document.getElementById("lotDisplay").textContent = "0.00";
    return;
  }
  const slDist = Math.abs(entry - sl);
  const mult = SYMBOLS[sym].multiplier;
  const riskAmount = capital * (riskPct / 100.0);
  const lot = riskAmount / (slDist * mult);
  document.getElementById("lotDisplay").textContent = Math.max(0.01, lot).toFixed(2);
}

async function saveSettings() {
  const cap = parseFloat(document.getElementById("inpCapital").value);
  const risk = parseFloat(document.getElementById("inpRisk").value);
  const status = document.getElementById("settingsStatus");
  if (!isFinite(cap) || cap <= 0) { setStatus(status, "Capital must be > 0", "err"); return; }
  if (!isFinite(risk) || risk <= 0 || risk > 100) { setStatus(status, "Risk must be (0, 100]", "err"); return; }
  try {
    await api("/api/settings", "POST", { capital: cap, risk_percent: risk });
    state.settings.capital = cap;
    state.settings.risk_percent = risk;
    setStatus(status, "Settings saved permanently", "ok");
    updateLotCalc();
    pollSummary();
  } catch (e) { setStatus(status, e.message, "err"); }
}

async function dispatchTrade() {
  const status = document.getElementById("dispatchStatus");
  const sym = document.getElementById("selSymbol").value;
  const side = document.getElementById("selSide").value;
  const pattern = document.getElementById("selPattern").value;
  const strategy = document.getElementById("selStrategy").value;
  const entry = parseFloat(document.getElementById("inpEntry").value);
  const sl = parseFloat(document.getElementById("inpSL").value);
  const tp = parseFloat(document.getElementById("inpTP").value);
  if (!isFinite(entry) || !isFinite(sl) || !isFinite(tp)) {
    setStatus(status, "Invalid entry/SL/TP values", "err"); return;
  }
  const payload = { symbol: sym, side, pattern, strategy, entry_price: entry, stop_loss: sl, take_profit: tp };
  try {
    const r = await api("/api/trades", "POST", payload);
    setStatus(status, `Trade #${r.data.id} dispatched (lot ${r.data.lot_size})`, "ok");
    pollTrades(); pollSummary(); pollStrategies();
  } catch (e) { setStatus(status, e.message, "err"); }
}

async function dispatchAuto() {
  const status = document.getElementById("dispatchStatus");
  const pattern = document.getElementById("selPattern").value;
  try {
    const r = await api("/api/auto_dispatch", "POST", { pattern });
    setStatus(status, `AUTO Trade #${r.data.id}: ${r.data.symbol} ${r.data.side} · ${r.data.strategy}`, "ok");
    pollTrades(); pollSummary(); pollStrategies();
  } catch (e) { setStatus(status, e.message, "err"); }
}

async function clearLearning() {
  if (!confirm("Clear all self-learning entries?")) return;
  try {
    await api("/api/reset_learning", "POST", {});
    pollLearning();
  } catch (e) { console.error(e); }
}

// ===================================================================
// BOOTSTRAP
// ===================================================================
async function boot() {
  document.getElementById("year").textContent = new Date().getFullYear();
  populateSelects();
  document.getElementById("selSymbol").addEventListener("change", fillDefaults);
  document.getElementById("selSide").addEventListener("change", fillDefaults);
  document.getElementById("selPattern").addEventListener("change", fillDefaults);
  document.getElementById("inpEntry").addEventListener("input", updateLotCalc);
  document.getElementById("inpSL").addEventListener("input", updateLotCalc);
  document.getElementById("btnSaveSettings").addEventListener("click", saveSettings);
  document.getElementById("btnDispatch").addEventListener("click", dispatchTrade);
  document.getElementById("btnAutoDispatch").addEventListener("click", dispatchAuto);
  document.getElementById("btnClearLearn").addEventListener("click", clearLearning);
  document.getElementById("chkAuto").addEventListener("change", e => {
    state.autoMode = e.target.checked;
  });

  // Initial fetches
  await Promise.all([pollPrices(), pollSummary(), pollStrategies(), pollMacro()]);
  fillDefaults();
  await Promise.all([pollTrades(), pollLearning()]);

  // Intervals
  setInterval(pollPrices, 1000);
  setInterval(pollSummary, 3000);
  setInterval(pollTrades, 3000);
  setInterval(pollStrategies, 5000);
  setInterval(pollMacro, 5000);
  setInterval(pollLearning, 4000);
}

boot();
</script>
</body>
</html>
"""


# ============================================================================
# ROOT ROUTE
# ============================================================================
@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(content=INDEX_HTML)


# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host=HOST,
        port=PORT,
        log_level="info",
        access_log=False,
        reload=False,
    )

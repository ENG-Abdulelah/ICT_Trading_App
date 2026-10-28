#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pro Trading & Macro Intelligence Engine
========================================
Single-file production server: Python stdlib http.server + SQLite.
Real-time simulated price feed · Macro/COT intelligence · Multi-timeframe
execution hierarchy · AI self-learning risk engine · TradingView-style UI.

Run:   python app.py
Port:  $PORT (default 8000)
"""

import os
import sys
import json
import math
import time
import random
import signal
import sqlite3
import threading
import traceback
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# ============================================================================
# CONFIGURATION
# ============================================================================
DB_PATH = os.environ.get("DB_PATH", "trading_bot_memory.db")
PORT    = int(os.environ.get("PORT", 8000))
HOST    = os.environ.get("HOST", "0.0.0.0")

DB_LOCK    = threading.RLock()
PRICE_LOCK = threading.RLock()
MACRO_LOCK = threading.RLock()
CB_LOCK    = threading.RLock()
COT_LOCK   = threading.RLock()
SHUTDOWN   = threading.Event()

# ---------------------------------------------------------------------------
# SYMBOL UNIVERSE
# ---------------------------------------------------------------------------
SYMBOLS = {
    "XAU/USD": {"base": 2352.40, "decimals": 2, "mult": 100,    "pip": 0.01,   "daily_vol": 0.012, "spread": 0.30,  "label": "Gold"},
    "XAG/USD": {"base": 27.480,  "decimals": 3, "mult": 1000,   "pip": 0.01,   "daily_vol": 0.025, "spread": 0.030, "label": "Silver"},
    "EUR/USD": {"base": 1.08720, "decimals": 5, "mult": 100000, "pip": 0.0001, "daily_vol": 0.006, "spread": 0.00008, "label": "Euro"},
    "GBP/USD": {"base": 1.27150, "decimals": 5, "mult": 100000, "pip": 0.0001, "daily_vol": 0.007, "spread": 0.00010, "label": "Sterling"},
    "USD/JPY": {"base": 155.320, "decimals": 3, "mult": 1000,   "pip": 0.01,   "daily_vol": 0.007, "spread": 0.015, "label": "Yen"},
    "DXY":     {"base": 105.180, "decimals": 3, "mult": 1000,   "pip": 0.01,   "daily_vol": 0.004, "spread": 0.020, "label": "Dollar Index"},
}

# ---------------------------------------------------------------------------
# TRADE MODES — MULTI-TIMEFRAME EXECUTION HIERARCHY
# ---------------------------------------------------------------------------
TRADE_MODES = {
    "SCALPING_A": {
        "label": "Scalping Mode A",
        "htf":   ["1W", "1D", "1H"],
        "entry_tfs": ["M5"],
        "desc": "HTF analysis 1W/1D/1H  →  Entry M5",
    },
    "SCALPING_B": {
        "label": "Scalping Mode B",
        "htf":   ["1W", "1D", "4H"],
        "entry_tfs": ["M15", "M1"],
        "desc": "HTF analysis 1W/1D/4H  →  Entry M15 or M1",
    },
    "SWING": {
        "label": "Swing",
        "htf":   ["1W", "1D"],
        "entry_tfs": ["H1", "H4"],
        "desc": "Macro Swing  →  Entry H1 or H4",
    },
}

# ---------------------------------------------------------------------------
# ICT STRATEGIES (10 institutional concepts)
# ---------------------------------------------------------------------------
ICT_STRATEGIES = [
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

# ---------------------------------------------------------------------------
# LIVE PRICE STATE
# ---------------------------------------------------------------------------
PRICES = {}
for _sym, _cfg in SYMBOLS.items():
    PRICES[_sym] = {
        "price":      _cfg["base"],
        "prev_price": _cfg["base"],
        "open":       _cfg["base"],
        "high":       _cfg["base"],
        "low":        _cfg["base"],
        "prev_close": _cfg["base"],
        "history":    [_cfg["base"]] * 60,
        "last_update": datetime.now(timezone.utc).isoformat(),
    }

# ---------------------------------------------------------------------------
# MACRO STATE
# ---------------------------------------------------------------------------
MACRO = {
    "vix":              16.40,
    "us10y":            4.355,
    "fed_rate":         5.375,
    "ecb_rate":         4.000,
    "boe_rate":         5.000,
    "boj_rate":         0.100,
    "regime":           "Neutral",
    "safe_haven_flow":  "USD",
    "updated_at":       datetime.now(timezone.utc).isoformat(),
}

# ---------------------------------------------------------------------------
# CENTRAL BANK RATE PROBABILITIES
# ---------------------------------------------------------------------------
CB_STATE = {
    "FED": {
        "name": "Federal Reserve",  "currency": "USD",  "rate": 5.375,
        "next_meeting_days": 17,
        "prob_cut": 55.0, "prob_hold": 40.0, "prob_hike": 5.0,
    },
    "ECB": {
        "name": "European Central Bank", "currency": "EUR", "rate": 4.000,
        "next_meeting_days": 11,
        "prob_cut": 70.0, "prob_hold": 28.0, "prob_hike": 2.0,
    },
    "BOE": {
        "name": "Bank of England", "currency": "GBP", "rate": 5.000,
        "next_meeting_days": 22,
        "prob_cut": 60.0, "prob_hold": 36.0, "prob_hike": 4.0,
    },
    "BOJ": {
        "name": "Bank of Japan", "currency": "JPY", "rate": 0.100,
        "next_meeting_days": 27,
        "prob_cut": 5.0,  "prob_hold": 65.0, "prob_hike": 30.0,
    },
}

# ---------------------------------------------------------------------------
# COMMITMENT OF TRADERS STATE
# ---------------------------------------------------------------------------
COT_STATE = {
    "Gold": {"long": 224_850, "short": 78_200, "prev_long": 221_000, "prev_short": 81_500},
    "EUR":  {"long": 165_300, "short": 112_400, "prev_long": 168_100, "prev_short": 108_700},
    "GBP":  {"long": 72_400,  "short": 58_100,  "prev_long": 70_200,  "prev_short": 61_300},
    "JPY":  {"long": 48_600,  "short": 118_900, "prev_long": 52_100,  "prev_short": 115_400},
}

# ---------------------------------------------------------------------------
# ECONOMIC CALENDAR — relabeled relative to now at runtime
# ---------------------------------------------------------------------------
CALENDAR_TEMPLATE = [
    {"offset_days": 2,  "hour": 18, "event": "FOMC Rate Decision",       "currency": "USD", "impact": "HIGH",   "forecast": "5.25%", "previous": "5.50%"},
    {"offset_days": 3,  "hour": 12, "event": "US Non-Farm Payrolls",     "currency": "USD", "impact": "HIGH",   "forecast": "185K",  "previous": "175K"},
    {"offset_days": 5,  "hour": 12, "event": "US CPI YoY",               "currency": "USD", "impact": "HIGH",   "forecast": "3.2%",  "previous": "3.4%"},
    {"offset_days": 1,  "hour": 11, "event": "ECB Press Conference",     "currency": "EUR", "impact": "MEDIUM", "forecast": "Hold",  "previous": "Hold"},
    {"offset_days": 4,  "hour": 11, "event": "BoE Bank Rate",            "currency": "GBP", "impact": "MEDIUM", "forecast": "5.00%", "previous": "5.25%"},
    {"offset_days": 6,  "hour": 3,  "event": "BoJ Policy Statement",     "currency": "JPY", "impact": "HIGH",   "forecast": "Hold",  "previous": "Hold"},
    {"offset_days": 2,  "hour": 12, "event": "US Retail Sales MoM",      "currency": "USD", "impact": "MEDIUM", "forecast": "0.4%",  "previous": "0.3%"},
    {"offset_days": 1,  "hour": 9,  "event": "German ZEW Sentiment",     "currency": "EUR", "impact": "LOW",    "forecast": "12.5",  "previous": "11.0"},
    {"offset_days": 8,  "hour": 12, "event": "US PPI YoY",               "currency": "USD", "impact": "MEDIUM", "forecast": "2.4%",  "previous": "2.6%"},
    {"offset_days": 9,  "hour": 8,  "event": "Eurozone GDP QoQ",         "currency": "EUR", "impact": "MEDIUM", "forecast": "0.2%",  "previous": "0.3%"},
    {"offset_days": 11, "hour": 12, "event": "FOMC Minutes",             "currency": "USD", "impact": "MEDIUM", "forecast": "N/A",   "previous": "N/A"},
    {"offset_days": 13, "hour": 12, "event": "US Core PCE YoY",          "currency": "USD", "impact": "HIGH",   "forecast": "2.6%",  "previous": "2.7%"},
]


# ============================================================================
# UTILITIES
# ============================================================================
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def session_volatility(hour_utc: int) -> float:
    """Realistic volatility multipliers across trading sessions (UTC hour)."""
    if 12 <= hour_utc < 16:
        return 1.85          # London / NY overlap — highest
    if 7 <= hour_utc < 12:
        return 1.55          # London
    if 16 <= hour_utc < 21:
        return 1.30          # New York
    if 1 <= hour_utc < 7:
        return 0.85          # Tokyo
    if hour_utc >= 21 or hour_utc < 1:
        return 0.65          # Late Sydney / pre-Tokyo
    return 1.00


def active_session() -> str:
    h = datetime.now(timezone.utc).hour
    if 22 <= h or h < 1:  return "Sydney"
    if 1 <= h < 7:        return "Tokyo"
    if 7 <= h < 12:       return "London"
    if 12 <= h < 16:      return "London / NY Overlap"
    if 16 <= h < 21:      return "New York"
    return "After Hours"


def is_kill_zone() -> bool:
    h = datetime.now(timezone.utc).hour
    return (7 <= h < 10) or (12 <= h < 15)


def classify_regime(vix: float) -> str:
    if vix >= 35: return "Crisis"
    if vix >= 25: return "Risk-Off"
    if vix <= 14: return "Risk-On"
    if vix <= 18: return "Neutral-Constructive"
    return "Neutral"


def classify_safe_haven(regime: str) -> str:
    return {"Crisis": "USD / JPY / Gold", "Risk-Off": "USD / Gold",
            "Risk-On": "Equities / AUD", "Neutral-Constructive": "Gold",
            "Neutral": "Gold / USD"}.get(regime, "Gold")


def calculate_lot_size(capital: float, risk_percent: float,
                       sl_distance: float, symbol: str) -> float:
    """Risk-based position sizing — returns lot size rounded to 2 decimals."""
    if sl_distance <= 0 or capital <= 0 or risk_percent <= 0:
        return 0.01
    mult = SYMBOLS.get(symbol, {}).get("mult", 100000)
    risk_amount = capital * (risk_percent / 100.0)
    raw = risk_amount / (sl_distance * mult)
    return max(0.01, round(raw, 2))


def default_sl_tp(symbol: str, mode: str, side: str, entry: float):
    """Return (SL, TP) based on symbol/mode/side using realistic ATR-style distances."""
    cfg = SYMBOLS[symbol]
    dec = cfg["decimals"]
    # Default pip/point distances per mode
    if symbol == "XAU/USD":
        dists = {"SCALPING_A": (3.5, 7.0), "SCALPING_B": (6.0, 12.0), "SWING": (18.0, 54.0)}
    elif symbol == "XAG/USD":
        dists = {"SCALPING_A": (0.08, 0.16), "SCALPING_B": (0.15, 0.30), "SWING": (0.45, 1.35)}
    elif symbol == "DXY":
        dists = {"SCALPING_A": (0.12, 0.24), "SCALPING_B": (0.20, 0.40), "SWING": (0.60, 1.80)}
    elif symbol == "USD/JPY":
        dists = {"SCALPING_A": (0.12, 0.24), "SCALPING_B": (0.20, 0.40), "SWING": (0.60, 1.80)}
    else:  # EUR/USD, GBP/USD — majors
        dists = {"SCALPING_A": (0.0012, 0.0024), "SCALPING_B": (0.0020, 0.0040), "SWING": (0.0060, 0.0180)}
    sl_d, tp_d = dists.get(mode, (0.0012, 0.0024))
    if side == "BUY":
        return round(entry - sl_d, dec), round(entry + tp_d, dec)
    return round(entry + sl_d, dec), round(entry - tp_d, dec)


# ============================================================================
# DATABASE
# ============================================================================
def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def db_exec(sql: str, params: tuple = ()) -> int:
    with DB_LOCK:
        c = get_conn()
        try:
            cur = c.execute(sql, params)
            c.commit()
            return cur.lastrowid or 0
        finally:
            c.close()


def db_query(sql: str, params: tuple = ()):
    with DB_LOCK:
        c = get_conn()
        try:
            return c.execute(sql, params).fetchall()
        finally:
            c.close()


def db_query_one(sql: str, params: tuple = ()):
    with DB_LOCK:
        c = get_conn()
        try:
            return c.execute(sql, params).fetchone()
        finally:
            c.close()


def init_db() -> None:
    with DB_LOCK:
        c = get_conn()
        try:
            cur = c.cursor()

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
                    entry_type TEXT NOT NULL CHECK (entry_type IN ('MARKET','LIMIT')),
                    mode TEXT NOT NULL,
                    htf_analysis TEXT NOT NULL,
                    entry_timeframe TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    take_profit REAL NOT NULL,
                    lot_size REAL NOT NULL,
                    strategy TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING'
                        CHECK (status IN ('PENDING','ACTIVE','WIN','LOSS','CANCELLED')),
                    pnl REAL DEFAULT 0.0,
                    exit_price REAL,
                    opened_at TEXT NOT NULL,
                    activated_at TEXT,
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
                    mode TEXT,
                    lesson TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (trade_id) REFERENCES trades (id)
                )
            """)

            cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_status   ON trades(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol   ON trades(symbol)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_learning_created ON self_learning(created_at)")

            cur.execute("SELECT COUNT(*) AS c FROM bot_settings")
            if cur.fetchone()["c"] == 0:
                cur.execute(
                    "INSERT INTO bot_settings (id, capital, risk_percent, updated_at) VALUES (1, ?, ?, ?)",
                    (10000.0, 1.0, now_iso())
                )

            for name in ICT_STRATEGIES:
                cur.execute(
                    "INSERT OR IGNORE INTO strategies (name, total_trades, wins, losses) VALUES (?, 0, 0, 0)",
                    (name,)
                )

            cur.execute("SELECT COUNT(*) AS c FROM strategies WHERE total_trades > 0")
            if cur.fetchone()["c"] == 0:
                rng = random.Random(7)
                for name in ICT_STRATEGIES:
                    total = rng.randint(30, 75)
                    wr = rng.uniform(0.55, 0.79)
                    wins = int(total * wr)
                    cur.execute(
                        "UPDATE strategies SET total_trades=?, wins=?, losses=? WHERE name=?",
                        (total, wins, total - wins, name)
                    )

            c.commit()
        finally:
            c.close()


# ============================================================================
# PRICE ENGINE — REALISTIC HIGH-FREQUENCY SIMULATION
# ============================================================================
def price_engine() -> None:
    last_day = datetime.now(timezone.utc).date()
    rng = random.Random()
    while not SHUTDOWN.is_set():
        try:
            now = datetime.now(timezone.utc)
            if now.date() != last_day:
                with PRICE_LOCK:
                    for sym in SYMBOLS:
                        PRICES[sym]["prev_close"] = PRICES[sym]["price"]
                        PRICES[sym]["open"]  = PRICES[sym]["price"]
                        PRICES[sym]["high"]  = PRICES[sym]["price"]
                        PRICES[sym]["low"]   = PRICES[sym]["price"]
                last_day = now.date()

            sess_mult = session_volatility(now.hour)
            with PRICE_LOCK:
                for sym, cfg in SYMBOLS.items():
                    st = PRICES[sym]
                    price = st["price"]

                    # Per-second volatility (Brownian motion) scaled to session
                    sigma_tick = cfg["daily_vol"] / math.sqrt(86400.0) * 1.35 * sess_mult
                    # Mean-reversion pull toward base
                    mr = (math.log(cfg["base"]) - math.log(price)) * 0.00035
                    log_ret = rng.gauss(mr, sigma_tick)

                    # Microstructure: bid/ask noise ± spread/2 applied as bound
                    spread_half = cfg["spread"] * 0.5
                    # Occasional jump (news/flow events)
                    if rng.random() < 0.0009:
                        log_ret += rng.choice((-1.0, 1.0)) * rng.uniform(0.0008, 0.0032) * sess_mult
                    # Mild autocorrelation: small continuation
                    if rng.random() < 0.42:
                        log_ret *= 1.15

                    new_price = price * math.exp(log_ret)
                    # Enforce non-degenerate bounds
                    new_price = max(0.000001, new_price)
                    # Apply spread noise to close simulation realism
                    new_price += rng.uniform(-spread_half, spread_half)
                    new_price = max(0.000001, new_price)

                    st["prev_price"] = price
                    st["price"] = new_price
                    if new_price > st["high"]:
                        st["high"] = new_price
                    if new_price < st["low"]:
                        st["low"] = new_price
                    st["last_update"] = now.isoformat()

                    h = st["history"]
                    h.append(new_price)
                    if len(h) > 60:
                        h.pop(0)
        except Exception as exc:
            print(f"[price_engine] {exc}", flush=True)
            traceback.print_exc()
        SHUTDOWN.wait(1.0)


# ============================================================================
# MACRO ENGINE
# ============================================================================
def macro_engine() -> None:
    rng = random.Random()
    while not SHUTDOWN.is_set():
        try:
            with MACRO_LOCK:
                # VIX — Ornstein-Uhlenbeck mean reversion + noise
                vix_target = 16.5
                MACRO["vix"] += (vix_target - MACRO["vix"]) * 0.008 + rng.gauss(0.0, 0.14)
                MACRO["vix"] = max(8.0, min(80.0, MACRO["vix"]))

                # US 10Y yield — slow drift
                MACRO["us10y"] += rng.gauss(0.0, 0.006)
                MACRO["us10y"] = max(0.5, min(7.5, MACRO["us10y"]))

                MACRO["regime"] = classify_regime(MACRO["vix"])
                MACRO["safe_haven_flow"] = classify_safe_haven(MACRO["regime"])
                MACRO["updated_at"] = now_iso()

            with CB_LOCK:
                for key in CB_STATE:
                    cb = CB_STATE[key]
                    drift = rng.gauss(0.0, 0.35)
                    cb["prob_cut"]  = max(0.0,   min(100.0, cb["prob_cut"]  + drift))
                    cb["prob_hike"] = max(0.0,   min(100.0, cb["prob_hike"] - drift * 0.4))
                    cb["prob_hold"] = max(0.0, 100.0 - cb["prob_cut"] - cb["prob_hike"])
                    s = cb["prob_cut"] + cb["prob_hold"] + cb["prob_hike"]
                    if s > 0:
                        cb["prob_cut"]  = round(cb["prob_cut"]  * 100.0 / s, 1)
                        cb["prob_hold"] = round(cb["prob_hold"] * 100.0 / s, 1)
                        cb["prob_hike"] = round(100.0 - cb["prob_cut"] - cb["prob_hold"], 1)

            with COT_LOCK:
                if rng.random() < 0.30:
                    for name in COT_STATE:
                        d_long  = int(rng.gauss(0.0, 750))
                        d_short = int(rng.gauss(0.0, 550))
                        row = COT_STATE[name]
                        row["prev_long"]  = row["long"]
                        row["prev_short"] = row["short"]
                        row["long"]  = max(5_000, row["long"]  + d_long)
                        row["short"] = max(5_000, row["short"] + d_short)
        except Exception as exc:
            print(f"[macro_engine] {exc}", flush=True)
            traceback.print_exc()
        SHUTDOWN.wait(3.0)


# ============================================================================
# SELF-LEARNING LESSON GENERATOR
# ============================================================================
STRATEGY_LESSONS = {
    "Liquidity Sweep & Stop Hunt":
        "Require a full entry-timeframe candle CLOSE beyond the sweep wick before entry. If the sweep occurs outside "
        "a Kill Zone, skip. Structural rule: never front-run a sweep — wait for displacement.",
    "Fair Value Gap (FVG)":
        "Only valid if the displacement candle closed with >1.5x the average range AND created an unmitigated FVG. "
        "Skip first-touch entries on HTF; require LTF mitigation with rejection wick before entry.",
    "Order Block (OB)":
        "Confirm OB is the last opposite-colour candle before impulse with a confirmed Break of Structure. "
        "Require rejection wick + volume spike before entry; avoid OB touches above 50% of block body.",
    "Change of Character (CHoCH)":
        "Verify CHoCH on the entry timeframe AFTER a verified HTF liquidity sweep. Standalone CHoCH without "
        "prior liquidity grab is <45% reliable. Always confirm with HTF bias alignment.",
    "Break of Structure (BOS)":
        "Require body close (not wick) beyond the swing with HTF alignment. BOS against HTF trend = counter-trend "
        "continuation trap. Skip BOS inside consolidation ranges.",
    "Breaker Block":
        "Only valid if the original Order Block was CLEANLY consumed by impulse with displacement. Confirm a fresh "
        "FVG in the same leg. Skip if breaker was formed by news wick only.",
    "Judas Swing / ORL":
        "Only trade Judas AFTER the opening-range liquidity sweep AND a confirmation candle. Never front-run the "
        "ORL sweep. Restrict to first 60 minutes of session.",
    "Kill Zones & Power of 3":
        "Restrict entries to London (07:00–10:00 UTC) or NY (12:00–15:00 UTC) Kill Zones. Skip AMD Distribution "
        "phase entries — the move is done by then. Power-of-3 requires ACCUMULATION confirmation on LTF.",
    "OTE & Premium/Discount":
        "Enter ONLY within 62%–79% retracement of the impulse leg. Skip any long above 50% premium or short below "
        "50% discount. Confluence with FVG/OB inside the OTE zone = highest probability.",
    "Inversion FVG (IFVG)":
        "IFVG is only valid after a full-body close through the FVG with strong displacement. Weak closes = "
        "invalid IFVG. Require retest of the inverted zone with rejection wick before entry.",
}

MODE_LESSONS = {
    "SCALPING_A": "Mode A lesson: HTF (1W/1D/1H) must align before M5 entry. If HTF conflicted, this trade was "
                  "low-probability. Reduce size 50% when HTF is not aligned.",
    "SCALPING_B": "Mode B lesson: HTF (1W/1D/4H) bias drives M15/M1 entry. The 4H FVG is the primary magnet — "
                  "if absent, entry should be skipped.",
    "SWING":      "Swing lesson: H1/H4 entry must be inside a verified HTF discount (BUY) or premium (SELL). "
                  "If price was in the wrong half of the HTF range, skip.",
}


def generate_lesson(trade_row, exit_price: float) -> str:
    sym       = trade_row["symbol"]
    side      = trade_row["side"]
    entry     = float(trade_row["entry_price"])
    sl        = float(trade_row["stop_loss"])
    strategy  = trade_row["strategy"]
    mode      = trade_row["mode"]
    htf       = trade_row["htf_analysis"]
    entry_tf  = trade_row["entry_timeframe"]
    cfg       = SYMBOLS.get(sym, {})
    pip       = cfg.get("pip", 0.0001)
    dec       = cfg.get("decimals", 4)

    loss_pips = abs(entry - sl) / pip if pip > 0 else 0.0

    head = (f"[{TRADE_MODES.get(mode, {}).get('label', mode)}] "
            f"{side} {sym} @ {entry:.{dec}f} → SL hit {exit_price:.{dec}f} "
            f"({loss_pips:.1f} pips loss).")

    strat_lesson = STRATEGY_LESSONS.get(strategy, "Review entry timing against HTF bias.")
    mode_lesson  = MODE_LESSONS.get(mode, "Review timeframe alignment.")
    tf_line      = f"Timeframe check: HTF ({','.join(htf)}) ↔ Entry ({entry_tf}) — verify alignment before re-entry."

    return f"{head} {strat_lesson} {mode_lesson} {tf_line}"


# ============================================================================
# TRADE EVALUATOR (fills LIMIT orders + monitors SL/TP)
# ============================================================================
def trade_evaluator() -> None:
    while not SHUTDOWN.is_set():
        try:
            with DB_LOCK:
                c = get_conn()
                try:
                    cur = c.cursor()
                    # ---- 1. Fill pending LIMIT orders --------------------------------
                    pending = cur.execute(
                        "SELECT * FROM trades WHERE status='PENDING' AND entry_type='LIMIT'"
                    ).fetchall()
                    for t in pending:
                        sym = t["symbol"]
                        with PRICE_LOCK:
                            current = PRICES.get(sym, {}).get("price")
                        if current is None:
                            continue
                        hit = False
                        if t["side"] == "BUY"  and current <= float(t["entry_price"]):
                            hit = True
                        if t["side"] == "SELL" and current >= float(t["entry_price"]):
                            hit = True
                        if hit:
                            cur.execute(
                                "UPDATE trades SET status='ACTIVE', activated_at=? WHERE id=?",
                                (now_iso(), t["id"])
                            )

                    # ---- 2. Evaluate ACTIVE positions for SL/TP ---------------------
                    active = cur.execute("SELECT * FROM trades WHERE status='ACTIVE'").fetchall()
                    for t in active:
                        tid     = t["id"]
                        sym     = t["symbol"]
                        side    = t["side"]
                        entry   = float(t["entry_price"])
                        sl      = float(t["stop_loss"])
                        tp      = float(t["take_profit"])
                        lot     = float(t["lot_size"])
                        strat   = t["strategy"]
                        with PRICE_LOCK:
                            current = PRICES.get(sym, {}).get("price")
                        if current is None:
                            continue

                        outcome = None
                        exit_price = None
                        if side == "BUY":
                            if current <= sl:     outcome, exit_price = "LOSS", sl
                            elif current >= tp:   outcome, exit_price = "WIN", tp
                        else:
                            if current >= sl:     outcome, exit_price = "LOSS", sl
                            elif current <= tp:   outcome, exit_price = "WIN", tp
                        if outcome is None:
                            continue

                        mult = SYMBOLS.get(sym, {}).get("mult", 100000)
                        diff = (exit_price - entry) if side == "BUY" else (entry - exit_price)
                        pnl  = round(diff * mult * lot, 2)
                        iso  = now_iso()

                        cur.execute(
                            "UPDATE trades SET status=?, pnl=?, exit_price=?, closed_at=? WHERE id=?",
                            (outcome, pnl, exit_price, iso, tid)
                        )

                        if outcome == "WIN":
                            cur.execute(
                                "UPDATE strategies SET total_trades=total_trades+1, wins=wins+1 WHERE name=?",
                                (strat,)
                            )
                        else:
                            cur.execute(
                                "UPDATE strategies SET total_trades=total_trades+1, losses=losses+1 WHERE name=?",
                                (strat,)
                            )
                            lesson = generate_lesson(t, exit_price)
                            cur.execute(
                                "INSERT INTO self_learning "
                                "(trade_id, symbol, strategy, mode, lesson, created_at) "
                                "VALUES (?, ?, ?, ?, ?, ?)",
                                (tid, sym, strat, t["mode"], lesson, iso)
                            )

                    c.commit()
                finally:
                    c.close()
        except Exception as exc:
            print(f"[trade_evaluator] {exc}", flush=True)
            traceback.print_exc()
        SHUTDOWN.wait(0.5)


# ============================================================================
# HTTP HANDLER
# ============================================================================
class Handler(BaseHTTPRequestHandler):

    server_version = "ProTradingEngine/2.0"

    def log_message(self, fmt, *args):
        # Suppress per-request access log noise; keep only warnings
        pass

    # ------------------ helpers ------------------
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")

    def _json(self, payload, status=200):
        try:
            body = json.dumps(payload, default=str).encode("utf-8")
        except Exception as exc:
            body = json.dumps({"ok": False, "error": f"serialize: {exc}"}).encode("utf-8")
            status = 500
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            print("[handler] broken pipe on response", flush=True)

    def _html(self, content, status=200):
        body = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            print("[handler] broken pipe on html", flush=True)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise ValueError(f"invalid JSON: {exc}")

    # ------------------ OPTIONS ------------------
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    # ------------------ GET ------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)
        try:
            if path in ("/", "/index.html"):
                self._html(INDEX_HTML)
                return

            if path == "/api/health":
                self._json({
                    "ok": True, "time": now_iso(),
                    "session": active_session(),
                    "kill_zone": is_kill_zone(),
                })
                return

            if path == "/api/config":
                self._json({
                    "ok": True,
                    "symbols": {
                        s: {"decimals": c["decimals"], "mult": c["mult"],
                            "pip": c["pip"], "label": c["label"]}
                        for s, c in SYMBOLS.items()
                    },
                    "modes": TRADE_MODES,
                    "strategies": ICT_STRATEGIES,
                })
                return

            if path == "/api/prices":
                data = {}
                with PRICE_LOCK:
                    for s, c in SYMBOLS.items():
                        st = PRICES[s]
                        open_p = st["open"]
                        chg = ((st["price"] - open_p) / open_p * 100.0) if open_p else 0.0
                        data[s] = {
                            "price":      round(st["price"],      c["decimals"]),
                            "prev_price": round(st["prev_price"], c["decimals"]),
                            "open":       round(open_p,           c["decimals"]),
                            "high":       round(st["high"],       c["decimals"]),
                            "low":        round(st["low"],        c["decimals"]),
                            "prev_close": round(st["prev_close"], c["decimals"]),
                            "change_pct": round(chg, 3),
                            "decimals":   c["decimals"],
                            "history":    [round(x, c["decimals"]) for x in st["history"][-40:]],
                            "last_update": st["last_update"],
                        }
                self._json({"ok": True, "data": data})
                return

            if path == "/api/settings":
                r = db_query_one("SELECT capital, risk_percent, updated_at FROM bot_settings WHERE id=1")
                if r is None:
                    self._json({"ok": False, "error": "settings missing"}, 500); return
                self._json({"ok": True, "data": {
                    "capital": float(r["capital"]),
                    "risk_percent": float(r["risk_percent"]),
                    "updated_at": r["updated_at"],
                }})
                return

            if path == "/api/trades":
                status_filter = qs.get("status", [None])[0]
                limit = int(qs.get("limit", ["200"])[0])
                if status_filter:
                    rows = db_query(
                        "SELECT * FROM trades WHERE status=? ORDER BY id DESC LIMIT ?",
                        (status_filter, limit)
                    )
                else:
                    rows = db_query("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,))
                self._json({"ok": True, "count": len(rows), "data": [dict(r) for r in rows]})
                return

            if path == "/api/strategies":
                rows = db_query(
                    "SELECT name, total_trades, wins, losses FROM strategies ORDER BY "
                    "CAST(wins AS REAL) / MAX(total_trades,1) DESC"
                )
                out = []
                for r in rows:
                    t = int(r["total_trades"]); w = int(r["wins"]); l = int(r["losses"])
                    wr = (w / t * 100.0) if t > 0 else 0.0
                    out.append({"name": r["name"], "total_trades": t,
                                "wins": w, "losses": l, "win_rate": round(wr, 2)})
                self._json({"ok": True, "data": out})
                return

            if path == "/api/summary":
                r = db_query_one(
                    "SELECT "
                    "(SELECT COUNT(*) FROM trades) AS total, "
                    "(SELECT COUNT(*) FROM trades WHERE status='PENDING') AS pending, "
                    "(SELECT COUNT(*) FROM trades WHERE status='ACTIVE') AS active, "
                    "(SELECT COUNT(*) FROM trades WHERE status='WIN') AS wins, "
                    "(SELECT COUNT(*) FROM trades WHERE status='LOSS') AS losses, "
                    "(SELECT COALESCE(SUM(pnl),0) FROM trades WHERE status IN ('WIN','LOSS')) AS realized"
                )
                settings = db_query_one("SELECT capital, risk_percent FROM bot_settings WHERE id=1")
                total = int(r["total"]); wins = int(r["wins"]); losses = int(r["losses"])
                wr = (wins / (wins + losses) * 100.0) if (wins + losses) > 0 else 0.0
                with PRICE_LOCK:
                    dxy_now = round(PRICES["DXY"]["price"], 3)
                self._json({"ok": True, "data": {
                    "capital": float(settings["capital"]),
                    "risk_percent": float(settings["risk_percent"]),
                    "total_trades": total,
                    "pending": int(r["pending"]),
                    "active": int(r["active"]),
                    "wins": wins,
                    "losses": losses,
                    "win_rate": round(wr, 2),
                    "realized_pnl": round(float(r["realized"]), 2),
                    "session": active_session(),
                    "kill_zone": is_kill_zone(),
                    "dxy": dxy_now,
                }})
                return

            if path == "/api/macro":
                with MACRO_LOCK:
                    vix = round(MACRO["vix"], 2)
                    us10y = round(MACRO["us10y"], 3)
                    regime = MACRO["regime"]
                    haven = MACRO["safe_haven_flow"]
                    upd = MACRO["updated_at"]
                with PRICE_LOCK:
                    xau = PRICES["XAU/USD"]["price"]
                    xag = PRICES["XAG/USD"]["price"]
                    dxy = PRICES["DXY"]["price"]
                gsr = round(xau / xag, 2) if xag > 0 else 0.0
                self._json({"ok": True, "data": {
                    "vix": vix,
                    "us10y": us10y,
                    "dxy": round(dxy, 3),
                    "gold_silver_ratio": gsr,
                    "fed_rate": MACRO["fed_rate"],
                    "ecb_rate": MACRO["ecb_rate"],
                    "boe_rate": MACRO["boe_rate"],
                    "boj_rate": MACRO["boj_rate"],
                    "regime": regime,
                    "safe_haven": haven,
                    "updated_at": upd,
                }})
                return

            if path == "/api/central_banks":
                with CB_LOCK:
                    snapshot = {k: dict(v) for k, v in CB_STATE.items()}
                self._json({"ok": True, "data": snapshot})
                return

            if path == "/api/cot":
                with COT_LOCK:
                    snapshot = {k: dict(v) for k, v in COT_STATE.items()}
                out = {}
                for name, c in snapshot.items():
                    total = c["long"] + c["short"]
                    net = c["long"] - c["short"]
                    delta_net = (c["long"] - c["prev_long"]) - (c["short"] - c["prev_short"])
                    out[name] = {
                        "long": c["long"],
                        "short": c["short"],
                        "net": net,
                        "delta_net": delta_net,
                        "long_pct": round(c["long"] * 100.0 / max(1, total), 2),
                        "short_pct": round(c["short"] * 100.0 / max(1, total), 2),
                    }
                self._json({"ok": True, "data": out})
                return

            if path == "/api/calendar":
                now = datetime.now(timezone.utc)
                events = []
                for tpl in CALENDAR_TEMPLATE:
                    dt = (now + timedelta(days=tpl["offset_days"])).replace(
                        hour=tpl["hour"], minute=0, second=0, microsecond=0
                    )
                    events.append({
                        "event":    tpl["event"],
                        "currency": tpl["currency"],
                        "impact":   tpl["impact"],
                        "forecast": tpl["forecast"],
                        "previous": tpl["previous"],
                        "when":     dt.isoformat(),
                        "when_str": dt.strftime("%Y-%m-%d %H:%M UTC"),
                        "in_days":  tpl["offset_days"],
                    })
                events.sort(key=lambda e: e["when"])
                self._json({"ok": True, "data": events})
                return

            if path == "/api/self_learning":
                limit = int(qs.get("limit", ["50"])[0])
                rows = db_query(
                    "SELECT id, trade_id, symbol, strategy, mode, lesson, created_at "
                    "FROM self_learning ORDER BY id DESC LIMIT ?",
                    (limit,)
                )
                self._json({"ok": True, "count": len(rows),
                            "data": [dict(r) for r in rows]})
                return

            self._json({"ok": False, "error": "not found", "path": path}, 404)
        except Exception as exc:
            traceback.print_exc()
            self._json({"ok": False, "error": str(exc)}, 500)

    # ------------------ POST ------------------
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        try:
            # ---------- SETTINGS ----------
            if path == "/api/settings":
                body = self._read_json()
                cap  = float(body.get("capital", 10000.0))
                risk = float(body.get("risk_percent", 1.0))
                if cap <= 0:
                    self._json({"ok": False, "error": "capital must be > 0"}, 400); return
                if risk <= 0 or risk > 100:
                    self._json({"ok": False, "error": "risk_percent must be (0, 100]"}, 400); return
                db_exec(
                    "UPDATE bot_settings SET capital=?, risk_percent=?, updated_at=? WHERE id=1",
                    (cap, risk, now_iso())
                )
                r = db_query_one("SELECT capital, risk_percent, updated_at FROM bot_settings WHERE id=1")
                self._json({"ok": True, "data": {
                    "capital": float(r["capital"]),
                    "risk_percent": float(r["risk_percent"]),
                    "updated_at": r["updated_at"],
                }})
                return

            # ---------- CREATE TRADE ----------
            if path == "/api/trades":
                body = self._read_json()
                symbol       = body.get("symbol", "XAU/USD")
                side         = str(body.get("side", "BUY")).upper()
                entry_type   = str(body.get("entry_type", "MARKET")).upper()
                mode         = body.get("mode", "SCALPING_A")
                strategy     = body.get("strategy", "Fair Value Gap (FVG)")
                entry_tf     = body.get("entry_timeframe", "")

                # Validation
                if symbol not in SYMBOLS:
                    self._json({"ok": False, "error": f"unknown symbol {symbol}"}, 400); return
                if side not in ("BUY", "SELL"):
                    self._json({"ok": False, "error": "side must be BUY/SELL"}, 400); return
                if entry_type not in ("MARKET", "LIMIT"):
                    self._json({"ok": False, "error": "entry_type must be MARKET/LIMIT"}, 400); return
                if mode not in TRADE_MODES:
                    self._json({"ok": False, "error": f"unknown mode {mode}"}, 400); return
                if strategy not in ICT_STRATEGIES:
                    self._json({"ok": False, "error": "unknown strategy"}, 400); return
                if not entry_tf:
                    entry_tf = TRADE_MODES[mode]["entry_tfs"][0]
                if entry_tf not in TRADE_MODES[mode]["entry_tfs"]:
                    self._json({"ok": False, "error":
                                f"entry timeframe {entry_tf} not valid for mode {mode}"}, 400); return

                cfg = SYMBOLS[symbol]
                dec = cfg["decimals"]
                with PRICE_LOCK:
                    live = PRICES[symbol]["price"]

                # Entry price
                if entry_type == "MARKET":
                    entry = round(live, dec)
                else:
                    user_entry = body.get("entry_price")
                    if user_entry is None:
                        self._json({"ok": False, "error":
                                    "entry_price required for LIMIT orders"}, 400); return
                    entry = round(float(user_entry), dec)
                    if side == "BUY" and entry >= live:
                        self._json({"ok": False, "error":
                                    "BUY LIMIT requires entry below current price"}, 400); return
                    if side == "SELL" and entry <= live:
                        self._json({"ok": False, "error":
                                    "SELL LIMIT requires entry above current price"}, 400); return

                # SL / TP
                sl_user = body.get("stop_loss")
                tp_user = body.get("take_profit")
                if sl_user is not None and tp_user is not None:
                    stop_loss   = round(float(sl_user), dec)
                    take_profit = round(float(tp_user), dec)
                else:
                    stop_loss, take_profit = default_sl_tp(symbol, mode, side, entry)

                if side == "BUY" and not (stop_loss < entry < take_profit):
                    self._json({"ok": False, "error": "For BUY: SL < entry < TP required"}, 400); return
                if side == "SELL" and not (take_profit < entry < stop_loss):
                    self._json({"ok": False, "error": "For SELL: TP < entry < SL required"}, 400); return

                # Lot
                s = db_query_one("SELECT capital, risk_percent FROM bot_settings WHERE id=1")
                sl_dist = abs(entry - stop_loss)
                lot = calculate_lot_size(float(s["capital"]), float(s["risk_percent"]), sl_dist, symbol)

                htf_str = ",".join(TRADE_MODES[mode]["htf"])
                status = "ACTIVE" if entry_type == "MARKET" else "PENDING"
                activated_at = now_iso() if status == "ACTIVE" else None

                new_id = db_exec(
                    "INSERT INTO trades (symbol, side, entry_type, mode, htf_analysis, "
                    "entry_timeframe, entry_price, stop_loss, take_profit, lot_size, "
                    "strategy, status, opened_at, activated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (symbol, side, entry_type, mode, htf_str, entry_tf,
                     entry, stop_loss, take_profit, lot, strategy,
                     status, now_iso(), activated_at)
                )
                r = db_query_one("SELECT * FROM trades WHERE id=?", (new_id,))
                self._json({"ok": True, "data": dict(r)})
                return

            # ---------- AUTO DISPATCH ----------
            if path == "/api/auto_dispatch":
                body = self._read_json()
                mode = body.get("mode") or random.choice(list(TRADE_MODES.keys()))
                if mode not in TRADE_MODES:
                    mode = "SCALPING_A"

                # Pick highest-volatility symbol over last N ticks
                with PRICE_LOCK:
                    def volatility_pct(sym):
                        h = PRICES[sym]["history"]
                        if len(h) < 5:
                            return 0.0
                        lo, hi = min(h), max(h)
                        return (hi - lo) / max(lo, 1e-9)
                    ranked = sorted(SYMBOLS.keys(), key=volatility_pct, reverse=True)
                    symbol = random.choice(ranked[:3])
                    hist = PRICES[symbol]["history"]
                    momentum = hist[-1] - hist[-6] if len(hist) >= 6 else 0.0
                    live = PRICES[symbol]["price"]

                side = "BUY" if momentum >= 0 else "SELL"

                # Strategy: weighted toward top performers
                tops = db_query(
                    "SELECT name FROM strategies WHERE total_trades > 0 "
                    "ORDER BY CAST(wins AS REAL)/MAX(total_trades,1) DESC LIMIT 5"
                )
                pool = [r["name"] for r in tops] if tops else ICT_STRATEGIES
                strategy = random.choice(pool)

                entry_tf = random.choice(TRADE_MODES[mode]["entry_tfs"])
                entry_type = random.choices(["MARKET", "LIMIT"], weights=[0.7, 0.3])[0]

                cfg = SYMBOLS[symbol]
                dec = cfg["decimals"]
                entry = round(live, dec)

                if entry_type == "LIMIT":
                    sl, tp = default_sl_tp(symbol, mode, side, entry)
                    pull = abs(entry - sl) * 0.35
                    if side == "BUY":
                        entry = round(entry - pull, dec)
                    else:
                        entry = round(entry + pull, dec)

                sl, tp = default_sl_tp(symbol, mode, side, entry)

                s = db_query_one("SELECT capital, risk_percent FROM bot_settings WHERE id=1")
                lot = calculate_lot_size(float(s["capital"]), float(s["risk_percent"]),
                                         abs(entry - sl), symbol)

                htf_str = ",".join(TRADE_MODES[mode]["htf"])
                status = "ACTIVE" if entry_type == "MARKET" else "PENDING"
                activated_at = now_iso() if status == "ACTIVE" else None

                new_id = db_exec(
                    "INSERT INTO trades (symbol, side, entry_type, mode, htf_analysis, "
                    "entry_timeframe, entry_price, stop_loss, take_profit, lot_size, "
                    "strategy, status, opened_at, activated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (symbol, side, entry_type, mode, htf_str, entry_tf,
                     entry, sl, tp, lot, strategy, status, now_iso(), activated_at)
                )
                r = db_query_one("SELECT * FROM trades WHERE id=?", (new_id,))
                self._json({"ok": True, "auto": True, "data": dict(r)})
                return

            # ---------- CANCEL PENDING ORDER ----------
            if path.startswith("/api/trades/") and path.endswith("/cancel"):
                parts = path.split("/")
                try:
                    tid = int(parts[3])
                except (IndexError, ValueError):
                    self._json({"ok": False, "error": "invalid trade id"}, 400); return
                row = db_query_one("SELECT status FROM trades WHERE id=?", (tid,))
                if row is None:
                    self._json({"ok": False, "error": "trade not found"}, 404); return
                if row["status"] != "PENDING":
                    self._json({"ok": False, "error": "only PENDING orders can be cancelled"}, 400); return
                db_exec("UPDATE trades SET status='CANCELLED', closed_at=? WHERE id=?",
                        (now_iso(), tid))
                self._json({"ok": True, "message": f"Trade #{tid} cancelled"})
                return

            # ---------- MANUAL CLOSE ACTIVE ----------
            if path.startswith("/api/trades/") and path.endswith("/close"):
                parts = path.split("/")
                try:
                    tid = int(parts[3])
                except (IndexError, ValueError):
                    self._json({"ok": False, "error": "invalid trade id"}, 400); return
                row = db_query_one("SELECT * FROM trades WHERE id=?", (tid,))
                if row is None:
                    self._json({"ok": False, "error": "trade not found"}, 404); return
                if row["status"] != "ACTIVE":
                    self._json({"ok": False, "error": "only ACTIVE trades can be closed"}, 400); return
                sym = row["symbol"]
                with PRICE_LOCK:
                    current = PRICES[sym]["price"]
                entry = float(row["entry_price"])
                side = row["side"]
                lot = float(row["lot_size"])
                mult = SYMBOLS[sym]["mult"]
                diff = (current - entry) if side == "BUY" else (entry - current)
                pnl = round(diff * mult * lot, 2)
                outcome = "WIN" if pnl >= 0 else "LOSS"
                db_exec(
                    "UPDATE trades SET status=?, pnl=?, exit_price=?, closed_at=? WHERE id=?",
                    (outcome, pnl, round(current, SYMBOLS[sym]["decimals"]), now_iso(), tid)
                )
                if outcome == "WIN":
                    db_exec("UPDATE strategies SET total_trades=total_trades+1, wins=wins+1 "
                            "WHERE name=?", (row["strategy"],))
                else:
                    db_exec("UPDATE strategies SET total_trades=total_trades+1, losses=losses+1 "
                            "WHERE name=?", (row["strategy"],))
                    lesson = generate_lesson(row, current)
                    db_exec("INSERT INTO self_learning "
                            "(trade_id, symbol, strategy, mode, lesson, created_at) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (tid, sym, row["strategy"], row["mode"], lesson, now_iso()))
                self._json({"ok": True, "message": f"Trade #{tid} closed ({outcome})",
                            "pnl": pnl})
                return

            # ---------- RESET SELF-LEARNING ----------
            if path == "/api/self_learning/reset":
                db_exec("DELETE FROM self_learning")
                self._json({"ok": True, "message": "self_learning cleared"})
                return

            # ---------- RESET ALL ----------
            if path == "/api/reset_all":
                db_exec("DELETE FROM trades")
                db_exec("DELETE FROM self_learning")
                db_exec("UPDATE strategies SET total_trades=0, wins=0, losses=0")
                self._json({"ok": True, "message": "all trades + lessons cleared"})
                return

            self._json({"ok": False, "error": "not found", "path": path}, 404)
        except ValueError as exc:
            self._json({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:
            traceback.print_exc()
            self._json({"ok": False, "error": str(exc)}, 500)


# ============================================================================
# FRONTEND
# ============================================================================
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en" class="dark">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Pro Trading &amp; Macro Intelligence Engine</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
  html, body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: radial-gradient(1400px 700px at 15% -10%, #0d1b3e 0%, #05091a 45%, #020308 100%);
  }
  .tabnum { font-variant-numeric: tabular-nums; font-feature-settings: "tnum"; }
  .card {
    background: linear-gradient(180deg, rgba(15,23,42,0.85) 0%, rgba(2,6,23,0.82) 100%);
    border: 1px solid rgba(59,130,246,0.14);
    box-shadow: 0 8px 32px -8px rgba(0,0,0,0.55);
    transition: border-color .2s ease;
  }
  .card:hover { border-color: rgba(59,130,246,0.30); }
  .flash-up   { animation: flashUp 0.65s ease-out; }
  .flash-down { animation: flashDown 0.65s ease-out; }
  @keyframes flashUp   { from { background-color: rgba(16,185,129,0.30); } to { background-color: transparent; } }
  @keyframes flashDown { from { background-color: rgba(244,63,94,0.30); } to { background-color: transparent; } }
  .pulse-dot { position: relative; display: inline-block; }
  .pulse-dot::before {
    content: ''; position: absolute; inset: -4px; border-radius: 9999px;
    background: currentColor; opacity: 0.4; animation: pulseRing 1.8s ease-out infinite;
  }
  @keyframes pulseRing { 0% { transform: scale(0.55); opacity: 0.6; } 100% { transform: scale(2.2); opacity: 0; } }
  ::-webkit-scrollbar { width: 8px; height: 8px; }
  ::-webkit-scrollbar-track { background: #0b1220; }
  ::-webkit-scrollbar-thumb { background: #1e293b; border-radius: 8px; }
  ::-webkit-scrollbar-thumb:hover { background: #334155; }
  .glow-blue   { box-shadow: 0 0 24px -6px rgba(56,189,248,0.65); }
  .glow-green  { box-shadow: 0 0 24px -6px rgba(16,185,129,0.65); }
  .glow-red    { box-shadow: 0 0 24px -6px rgba(244,63,94,0.65); }
  .glow-amber  { box-shadow: 0 0 24px -6px rgba(245,158,11,0.65); }
  .stripe-row:nth-child(odd) { background: rgba(15,23,42,0.35); }
  .stripe-row:hover { background: rgba(30,64,175,0.14); }
  select, input { outline: none; }
  select:focus, input:focus { border-color: #38bdf8 !important; box-shadow: 0 0 0 2px rgba(56,189,248,0.22); }
  .btn-primary {
    background: linear-gradient(135deg, #0ea5e9 0%, #2563eb 100%);
    transition: transform .15s ease, filter .15s ease;
  }
  .btn-primary:hover { filter: brightness(1.10); transform: translateY(-1px); }
  .btn-primary:active { transform: translateY(0); }
  .btn-success {
    background: linear-gradient(135deg, #10b981 0%, #059669 100%);
    transition: transform .15s ease, filter .15s ease;
  }
  .btn-success:hover { filter: brightness(1.10); transform: translateY(-1px); }
  .tag { display: inline-block; padding: 1px 7px; border-radius: 999px; font-size: 10px; font-weight: 600; letter-spacing: 0.03em; }
  .scroll-area { max-height: 460px; overflow-y: auto; }
</style>
</head>
<body class="text-slate-200 min-h-screen pb-14">

<header class="sticky top-0 z-40 backdrop-blur-xl bg-slate-950/75 border-b border-blue-500/15">
  <div class="max-w-[1700px] mx-auto px-4 py-3 flex flex-wrap items-center gap-3 justify-between">
    <div class="flex items-center gap-3">
      <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-sky-400 via-blue-600 to-indigo-700 flex items-center justify-center font-black text-lg shadow-lg glow-blue">P</div>
      <div>
        <div class="text-[15px] font-bold tracking-tight text-white">Pro Trading &amp; Macro Intelligence</div>
        <div class="text-[10px] uppercase tracking-[0.22em] text-slate-500">Institutional ICT Engine · v2.0</div>
      </div>
    </div>
    <div class="flex flex-wrap items-center gap-2 text-xs">
      <div class="flex items-center gap-2 bg-slate-900/70 border border-slate-800 rounded-full px-3 py-1.5">
        <span class="text-emerald-400 pulse-dot w-2 h-2 rounded-full bg-emerald-400"></span>
        <span class="text-emerald-300 font-semibold">LIVE</span>
      </div>
      <div class="bg-slate-900/70 border border-slate-800 rounded-full px-3 py-1.5">
        Session: <b id="sessionLabel" class="text-sky-300">—</b>
      </div>
      <div id="killZoneBadge" class="bg-slate-900/70 border border-slate-800 rounded-full px-3 py-1.5">
        Kill Zone: <b id="killZoneLabel" class="text-slate-400">—</b>
      </div>
      <div class="bg-slate-900/70 border border-slate-800 rounded-full px-3 py-1.5">
        Capital: <b id="topCapital" class="text-emerald-300 tabnum">$0</b>
      </div>
      <div class="bg-slate-900/70 border border-slate-800 rounded-full px-3 py-1.5">
        Win Rate: <b id="topWinRate" class="text-amber-300 tabnum">0%</b>
      </div>
      <div class="bg-slate-900/70 border border-slate-800 rounded-full px-3 py-1.5">
        Regime: <b id="topRegime" class="text-fuchsia-300">—</b>
      </div>
    </div>
  </div>
</header>

<main class="max-w-[1700px] mx-auto px-4 py-6 space-y-6">

  <section>
    <div class="flex items-center justify-between mb-3">
      <h2 class="text-xs font-bold uppercase tracking-[0.22em] text-slate-400">Live Market Feed</h2>
      <div class="text-[10px] text-slate-500">1-second tick · real-time SL/TP evaluation</div>
    </div>
    <div id="priceGrid" class="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3"></div>
  </section>

  <section class="grid grid-cols-1 xl:grid-cols-3 gap-4">

    <div class="card rounded-xl p-5">
      <h3 class="text-xs font-bold uppercase tracking-[0.22em] text-sky-400 mb-4">Account &amp; Risk Control</h3>
      <div class="space-y-4">
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest">Capital (USD)</label>
          <input id="inpCapital" type="number" step="0.01" min="1" value="10000"
                 class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white tabnum" />
        </div>
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest">Risk per Trade (%)</label>
          <input id="inpRisk" type="number" step="0.05" min="0.01" max="100" value="1"
                 class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white tabnum" />
        </div>
        <button id="btnSaveSettings" class="btn-primary w-full text-white font-semibold rounded-lg py-2 glow-blue">
          Save Permanently
        </button>
        <div id="settingsStatus" class="text-[11px] h-4"></div>
        <div class="pt-3 border-t border-slate-800 grid grid-cols-2 gap-y-1.5 text-[11px]">
          <div class="text-slate-500">Risk $/trade</div><div class="text-right text-white tabnum" id="riskUsd">—</div>
          <div class="text-slate-500">Total trades</div><div class="text-right text-white tabnum" id="statTotal">—</div>
          <div class="text-slate-500">Active</div><div class="text-right text-emerald-300 tabnum" id="statActive">—</div>
          <div class="text-slate-500">Pending</div><div class="text-right text-amber-300 tabnum" id="statPending">—</div>
          <div class="text-slate-500">Realized P&amp;L</div><div class="text-right tabnum" id="statPnl">—</div>
        </div>
      </div>
    </div>

    <div class="card rounded-xl p-5 xl:col-span-2">
      <h3 class="text-xs font-bold uppercase tracking-[0.22em] text-sky-400 mb-4">Trade Console — Multi-Timeframe Execution</h3>

      <div class="grid grid-cols-2 md:grid-cols-3 gap-3">
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
          <label class="text-[11px] text-slate-400 uppercase tracking-widest">Entry Type</label>
          <select id="selEntryType" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white">
            <option value="MARKET">MARKET</option>
            <option value="LIMIT">LIMIT</option>
          </select>
        </div>
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest">Trade Mode</label>
          <select id="selMode" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white"></select>
        </div>
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest">Entry Timeframe</label>
          <select id="selEntryTF" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white"></select>
        </div>
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest">ICT Strategy</label>
          <select id="selStrategy" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white"></select>
        </div>
      </div>

      <div class="mt-3 grid grid-cols-3 gap-3">
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest">Entry Price</label>
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
      </div>

      <div class="mt-3 grid grid-cols-2 gap-3">
        <div class="bg-slate-950/70 border border-slate-800 rounded-lg px-3 py-2">
          <div class="text-[10px] uppercase tracking-widest text-slate-500">HTF Analysis (auto)</div>
          <div id="htfDisplay" class="text-sky-300 font-semibold text-sm tabnum">1W · 1D · 1H</div>
        </div>
        <div class="bg-slate-950/70 border border-sky-500/30 rounded-lg px-3 py-2">
          <div class="text-[10px] uppercase tracking-widest text-slate-500">Calculated Lot Size</div>
          <div id="lotDisplay" class="text-emerald-300 font-bold text-lg tabnum">0.00</div>
        </div>
      </div>

      <div class="flex flex-wrap gap-2 mt-4">
        <button id="btnDispatch" class="btn-success flex-1 min-w-[180px] text-white font-semibold rounded-lg py-2.5">
          ⚡ Dispatch Trade
        </button>
        <button id="btnAutoDispatch" class="btn-primary flex-1 min-w-[180px] text-white font-semibold rounded-lg py-2.5">
          🤖 Auto Dispatch
        </button>
      </div>
      <div id="dispatchStatus" class="text-[11px] mt-2 h-4"></div>
    </div>
  </section>

  <section class="card rounded-xl overflow-hidden">
    <div class="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
      <h3 class="text-xs font-bold uppercase tracking-[0.22em] text-emerald-400">Active Positions</h3>
      <span id="activeCount" class="text-[11px] text-slate-500">0</span>
    </div>
    <div class="overflow-x-auto">
      <table class="w-full text-xs">
        <thead class="bg-slate-950/60 text-slate-500 uppercase text-[10px] tracking-wider">
          <tr>
            <th class="text-left px-3 py-2">ID</th><th class="text-left px-3 py-2">Symbol</th>
            <th class="text-left px-3 py-2">Side</th><th class="text-left px-3 py-2">Mode</th>
            <th class="text-left px-3 py-2">HTF → Entry</th>
            <th class="text-right px-3 py-2">Entry</th><th class="text-right px-3 py-2">SL</th>
            <th class="text-right px-3 py-2">TP</th><th class="text-right px-3 py-2">Lot</th>
            <th class="text-left px-3 py-2">Strategy</th><th class="text-center px-3 py-2">Action</th>
          </tr>
        </thead>
        <tbody id="tblActive"></tbody>
      </table>
    </div>
  </section>

  <section class="card rounded-xl overflow-hidden">
    <div class="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
      <h3 class="text-xs font-bold uppercase tracking-[0.22em] text-amber-400">Pending Limit Orders</h3>
      <span id="pendingCountLabel" class="text-[11px] text-slate-500">0</span>
    </div>
    <div class="overflow-x-auto">
      <table class="w-full text-xs">
        <thead class="bg-slate-950/60 text-slate-500 uppercase text-[10px] tracking-wider">
          <tr>
            <th class="text-left px-3 py-2">ID</th><th class="text-left px-3 py-2">Symbol</th>
            <th class="text-left px-3 py-2">Side</th><th class="text-left px-3 py-2">Mode</th>
            <th class="text-left px-3 py-2">HTF → Entry</th>
            <th class="text-right px-3 py-2">Limit Entry</th><th class="text-right px-3 py-2">SL</th>
            <th class="text-right px-3 py-2">TP</th><th class="text-right px-3 py-2">Lot</th>
            <th class="text-left px-3 py-2">Strategy</th><th class="text-center px-3 py-2">Action</th>
          </tr>
        </thead>
        <tbody id="tblPending"></tbody>
      </table>
    </div>
  </section>

  <section class="card rounded-xl overflow-hidden">
    <div class="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
      <h3 class="text-xs font-bold uppercase tracking-[0.22em] text-slate-300">Trade History</h3>
      <span class="text-[11px] text-slate-500">last 50 closed</span>
    </div>
    <div class="overflow-x-auto scroll-area">
      <table class="w-full text-xs">
        <thead class="bg-slate-950/60 text-slate-500 uppercase text-[10px] tracking-wider sticky top-0">
          <tr>
            <th class="text-left px-3 py-2">ID</th><th class="text-left px-3 py-2">Symbol</th>
            <th class="text-left px-3 py-2">Side</th><th class="text-left px-3 py-2">Mode</th>
            <th class="text-left px-3 py-2">HTF → Entry</th>
            <th class="text-right px-3 py-2">Entry</th><th class="text-right px-3 py-2">Exit</th>
            <th class="text-right px-3 py-2">Lot</th><th class="text-left px-3 py-2">Strategy</th>
            <th class="text-left px-3 py-2">Status</th><th class="text-right px-3 py-2">P&amp;L</th>
            <th class="text-left px-3 py-2">Closed</th>
          </tr>
        </thead>
        <tbody id="tblHistory"></tbody>
      </table>
    </div>
  </section>

  <section class="grid grid-cols-1 xl:grid-cols-2 gap-4">

    <div class="card rounded-xl overflow-hidden">
      <div class="px-5 py-3 border-b border-slate-800">
        <h3 class="text-xs font-bold uppercase tracking-[0.22em] text-fuchsia-400">ICT Strategy Win Rates</h3>
      </div>
      <div class="overflow-x-auto scroll-area">
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
      <h3 class="text-xs font-bold uppercase tracking-[0.22em] text-indigo-400 mb-4">Macro Intelligence</h3>
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div class="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
          <div class="text-[10px] uppercase tracking-widest text-slate-500">VIX</div>
          <div id="macroVix" class="text-lg font-bold text-rose-300 tabnum mt-1">—</div>
        </div>
        <div class="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
          <div class="text-[10px] uppercase tracking-widest text-slate-500">US 10Y</div>
          <div id="macro10y" class="text-lg font-bold text-amber-300 tabnum mt-1">—</div>
        </div>
        <div class="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
          <div class="text-[10px] uppercase tracking-widest text-slate-500">DXY</div>
          <div id="macroDxy" class="text-lg font-bold text-sky-300 tabnum mt-1">—</div>
        </div>
        <div class="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
          <div class="text-[10px] uppercase tracking-widest text-slate-500">XAU/XAG</div>
          <div id="macroGsr" class="text-lg font-bold text-amber-200 tabnum mt-1">—</div>
        </div>
      </div>
      <div class="mt-3 flex flex-wrap gap-2 text-xs">
        <span class="bg-slate-950/70 border border-slate-800 rounded-full px-3 py-1.5">
          Regime: <b id="macroRegime" class="text-emerald-300">—</b>
        </span>
        <span class="bg-slate-950/70 border border-slate-800 rounded-full px-3 py-1.5">
          Safe-Haven: <b id="macroHaven" class="text-amber-300">—</b>
        </span>
      </div>
    </div>
  </section>

  <section class="grid grid-cols-1 xl:grid-cols-2 gap-4">

    <div class="card rounded-xl overflow-hidden">
      <div class="px-5 py-3 border-b border-slate-800">
        <h3 class="text-xs font-bold uppercase tracking-[0.22em] text-teal-400">COT Institutional Positioning</h3>
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
        <h3 class="text-xs font-bold uppercase tracking-[0.22em] text-purple-400">Central Bank Rate Probabilities</h3>
      </div>
      <div id="cbGrid" class="grid grid-cols-1 md:grid-cols-2 gap-3 p-4"></div>
    </div>
  </section>

  <section class="card rounded-xl overflow-hidden">
    <div class="px-5 py-3 border-b border-slate-800">
      <h3 class="text-xs font-bold uppercase tracking-[0.22em] text-orange-400">Economic Calendar — High Impact Events</h3>
    </div>
    <div class="overflow-x-auto scroll-area">
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
  </section>

  <section class="card rounded-xl overflow-hidden">
    <div class="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
      <h3 class="text-xs font-bold uppercase tracking-[0.22em] text-amber-400">AI Self-Learning Journal</h3>
      <button id="btnClearLearn" class="text-[11px] text-slate-500 hover:text-rose-400 transition">Clear all</button>
    </div>
    <div id="learnList" class="divide-y divide-slate-800 scroll-area"></div>
  </section>

</main>

<footer class="fixed bottom-0 left-0 right-0 text-center text-[10px] text-slate-600 bg-slate-950/85 border-t border-slate-800 py-2 z-30">
  Pro Trading &amp; Macro Intelligence Engine · Python stdlib · SQLite · © <span id="year"></span>
</footer>

<script>
// ===================================================================
// STATE & CONFIG
// ===================================================================
const SYMBOLS = {
  "XAU/USD": { decimals: 2, mult: 100,    pip: 0.01,   label: "Gold" },
  "XAG/USD": { decimals: 3, mult: 1000,   pip: 0.01,   label: "Silver" },
  "EUR/USD": { decimals: 5, mult: 100000, pip: 0.0001, label: "Euro" },
  "GBP/USD": { decimals: 5, mult: 100000, pip: 0.0001, label: "Sterling" },
  "USD/JPY": { decimals: 3, mult: 1000,   pip: 0.01,   label: "Yen" },
  "DXY":     { decimals: 3, mult: 1000,   pip: 0.01,   label: "Dollar Index" },
};

const MODES = {
  "SCALPING_A": { label: "Scalping Mode A", htf: ["1W","1D","1H"], entry_tfs: ["M5"] },
  "SCALPING_B": { label: "Scalping Mode B", htf: ["1W","1D","4H"], entry_tfs: ["M15","M1"] },
  "SWING":      { label: "Swing",           htf: ["1W","1D"],     entry_tfs: ["H1","H4"] },
};

const STRATEGIES = [
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

const DEFAULT_DISTS = {
  "XAU/USD": { SCALPING_A: [3.5, 7.0],  SCALPING_B: [6.0, 12.0], SWING: [18.0, 54.0] },
  "XAG/USD": { SCALPING_A: [0.08, 0.16], SCALPING_B: [0.15, 0.30], SWING: [0.45, 1.35] },
  "DXY":     { SCALPING_A: [0.12, 0.24], SCALPING_B: [0.20, 0.40], SWING: [0.60, 1.80] },
  "USD/JPY": { SCALPING_A: [0.12, 0.24], SCALPING_B: [0.20, 0.40], SWING: [0.60, 1.80] },
  "_fx":     { SCALPING_A: [0.0012, 0.0024], SCALPING_B: [0.0020, 0.0040], SWING: [0.0060, 0.0180] },
};

const state = {
  prices: {},
  settings: { capital: 10000, risk_percent: 1 },
  lastActiveIds: new Set(),
  lastPendingIds: new Set(),
};

// ===================================================================
// HELPERS
// ===================================================================
function fmt(sym, price) {
  const d = (SYMBOLS[sym] && SYMBOLS[sym].decimals) || 2;
  return Number(price).toFixed(d);
}
function fmtUsd(n) {
  return "$" + Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function fmtPnl(n) {
  const v = Number(n || 0);
  const cls = v > 0 ? "text-emerald-400" : v < 0 ? "text-rose-400" : "text-slate-400";
  return `<span class="${cls}">${v >= 0 ? "+" : ""}${v.toFixed(2)}</span>`;
}
function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
function modeTag(mode) {
  const cfg = MODES[mode] || { label: mode };
  const color = mode === "SWING" ? "bg-purple-900/60 text-purple-300"
              : mode === "SCALPING_B" ? "bg-cyan-900/60 text-cyan-300"
              : "bg-blue-900/60 text-blue-300";
  return `<span class="tag ${color}">${escapeHtml(cfg.label)}</span>`;
}
function tfHierarchy(htf, entryTf) {
  return `<span class="text-sky-300 font-semibold">${escapeHtml(htf)}</span> <span class="text-slate-600">→</span> <span class="text-emerald-300 font-semibold">${escapeHtml(entryTf)}</span>`;
}

async function api(path, method = "GET", body = null) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body !== null) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) {
    const err = (data && (data.error || data.detail)) || `HTTP ${res.status}`;
    throw new Error(typeof err === "string" ? err : JSON.stringify(err));
  }
  return data;
}
function setStatus(el, msg, type = "ok") {
  el.textContent = msg || "";
  el.className = "text-[11px] mt-2 h-4 " + (type === "err" ? "text-rose-400" : "text-emerald-400");
  if (msg) setTimeout(() => { if (el.textContent === msg) el.textContent = ""; }, 4000);
}
function sparkline(history) {
  if (!history || history.length < 2) return "";
  const min = Math.min(...history), max = Math.max(...history);
  const rng = max - min || 1;
  const W = 140, H = 28;
  const pts = history.map((p, i) => {
    const x = (i / (history.length - 1)) * W;
    const y = H - ((p - min) / rng) * H;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const up = history[history.length - 1] >= history[0];
  const stroke = up ? "#10b981" : "#f43f5e";
  return `<svg width="100%" height="${H}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" class="opacity-90">
    <polyline points="${pts}" fill="none" stroke="${stroke}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>
  </svg>`;
}

// ===================================================================
// RENDER: PRICES
// ===================================================================
function renderPrices(data) {
  const grid = document.getElementById("priceGrid");
  let html = "";
  for (const sym in data) {
    const p = data[sym];
    const prevState = state.prices[sym] ? state.prices[sym].price : p.prev_close;
    let flash = "";
    if (state.prices[sym]) {
      if (p.price > prevState + 1e-12) flash = "flash-up";
      else if (p.price < prevState - 1e-12) flash = "flash-down";
    }
    const pctColor = p.change_pct > 0 ? "text-emerald-400" : p.change_pct < 0 ? "text-rose-400" : "text-slate-500";
    const arrow = p.change_pct > 0 ? "▲" : p.change_pct < 0 ? "▼" : "—";
    html += `
      <div class="card rounded-xl p-3 ${flash}">
        <div class="flex items-center justify-between">
          <div class="text-[11px] font-bold text-slate-200 tracking-wider">${escapeHtml(sym)}</div>
          <div class="text-[10px] ${pctColor} tabnum">${arrow} ${Math.abs(p.change_pct).toFixed(2)}%</div>
        </div>
        <div class="text-xl font-bold text-white tabnum mt-1">${fmt(sym, p.price)}</div>
        <div class="text-[10px] text-slate-500 tabnum mt-1 flex justify-between">
          <span>H: ${fmt(sym, p.high)}</span>
          <span>L: ${fmt(sym, p.low)}</span>
        </div>
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
  document.getElementById("topRegime").textContent = s.dxy ? `DXY ${s.dxy.toFixed(2)}` : "—";

  const kz = document.getElementById("killZoneBadge");
  const kzLbl = document.getElementById("killZoneLabel");
  if (s.kill_zone) {
    kz.className = "bg-emerald-950/60 border border-emerald-700/50 rounded-full px-3 py-1.5";
    kzLbl.className = "text-emerald-300 font-bold";
    kzLbl.textContent = "ACTIVE";
  } else {
    kz.className = "bg-slate-900/70 border border-slate-800 rounded-full px-3 py-1.5";
    kzLbl.className = "text-slate-400";
    kzLbl.textContent = "INACTIVE";
  }

  const riskUsd = s.capital * s.risk_percent / 100.0;
  document.getElementById("riskUsd").textContent = fmtUsd(riskUsd);
  document.getElementById("statTotal").textContent = s.total_trades;
  document.getElementById("statActive").textContent = s.active;
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
function renderActive(trades) {
  const active = trades.filter(t => t.status === "ACTIVE");
  document.getElementById("activeCount").textContent = active.length + " open";
  const body = document.getElementById("tblActive");
  if (active.length === 0) {
    body.innerHTML = `<tr><td colspan="11" class="text-center text-slate-500 py-6 text-xs">No active positions</td></tr>`;
    return;
  }
  body.innerHTML = active.map(t => `
    <tr class="stripe-row border-b border-slate-800/60">
      <td class="px-3 py-2 text-slate-400 tabnum">#${t.id}</td>
      <td class="px-3 py-2 font-semibold text-white">${escapeHtml(t.symbol)}</td>
      <td class="px-3 py-2 font-bold ${t.side === "BUY" ? "text-emerald-400" : "text-rose-400"}">${t.side}</td>
      <td class="px-3 py-2">${modeTag(t.mode)}</td>
      <td class="px-3 py-2 text-[10px]">${tfHierarchy(t.htf_analysis, t.entry_timeframe)}</td>
      <td class="px-3 py-2 text-right tabnum text-slate-200">${fmt(t.symbol, t.entry_price)}</td>
      <td class="px-3 py-2 text-right tabnum text-rose-400">${fmt(t.symbol, t.stop_loss)}</td>
      <td class="px-3 py-2 text-right tabnum text-emerald-400">${fmt(t.symbol, t.take_profit)}</td>
      <td class="px-3 py-2 text-right tabnum text-sky-300">${Number(t.lot_size).toFixed(2)}</td>
      <td class="px-3 py-2 text-slate-400 max-w-[220px] truncate" title="${escapeHtml(t.strategy)}">${escapeHtml(t.strategy)}</td>
      <td class="px-3 py-2 text-center">
        <button class="btn-close bg-rose-600/80 hover:bg-rose-500 text-white text-[10px] px-2 py-1 rounded"
                data-id="${t.id}">Close</button>
      </td>
    </tr>`).join("");

  body.querySelectorAll(".btn-close").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!confirm(`Manually close trade #${btn.dataset.id} at current market?`)) return;
      try {
        const r = await api(`/api/trades/${btn.dataset.id}/close`, "POST", {});
        pollTrades(); pollSummary(); pollStrategies();
        console.log("Closed:", r);
      } catch (e) { alert("Close failed: " + e.message); }
    });
  });
}

function renderPending(trades) {
  const pending = trades.filter(t => t.status === "PENDING");
  document.getElementById("pendingCountLabel").textContent = pending.length + " waiting";
  const body = document.getElementById("tblPending");
  if (pending.length === 0) {
    body.innerHTML = `<tr><td colspan="11" class="text-center text-slate-500 py-6 text-xs">No pending limit orders</td></tr>`;
    return;
  }
  body.innerHTML = pending.map(t => `
    <tr class="stripe-row border-b border-slate-800/60">
      <td class="px-3 py-2 text-slate-400 tabnum">#${t.id}</td>
      <td class="px-3 py-2 font-semibold text-white">${escapeHtml(t.symbol)}</td>
      <td class="px-3 py-2 font-bold ${t.side === "BUY" ? "text-emerald-400" : "text-rose-400"}">${t.side}</td>
      <td class="px-3 py-2">${modeTag(t.mode)}</td>
      <td class="px-3 py-2 text-[10px]">${tfHierarchy(t.htf_analysis, t.entry_timeframe)}</td>
      <td class="px-3 py-2 text-right tabnum text-amber-300">${fmt(t.symbol, t.entry_price)}</td>
      <td class="px-3 py-2 text-right tabnum text-rose-400">${fmt(t.symbol, t.stop_loss)}</td>
      <td class="px-3 py-2 text-right tabnum text-emerald-400">${fmt(t.symbol, t.take_profit)}</td>
      <td class="px-3 py-2 text-right tabnum text-sky-300">${Number(t.lot_size).toFixed(2)}</td>
      <td class="px-3 py-2 text-slate-400 max-w-[220px] truncate" title="${escapeHtml(t.strategy)}">${escapeHtml(t.strategy)}</td>
      <td class="px-3 py-2 text-center">
        <button class="btn-cancel bg-slate-700 hover:bg-slate-600 text-white text-[10px] px-2 py-1 rounded"
                data-id="${t.id}">Cancel</button>
      </td>
    </tr>`).join("");

  body.querySelectorAll(".btn-cancel").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!confirm(`Cancel pending order #${btn.dataset.id}?`)) return;
      try {
        await api(`/api/trades/${btn.dataset.id}/cancel`, "POST", {});
        pollTrades(); pollSummary();
      } catch (e) { alert("Cancel failed: " + e.message); }
    });
  });
}

function renderHistory(trades) {
  const closed = trades.filter(t => ["WIN","LOSS","CANCELLED"].includes(t.status)).slice(0, 50);
  const body = document.getElementById("tblHistory");
  if (closed.length === 0) {
    body.innerHTML = `<tr><td colspan="12" class="text-center text-slate-500 py-6 text-xs">No closed trades yet</td></tr>`;
    return;
  }
  body.innerHTML = closed.map(t => {
    const statCls = t.status === "WIN" ? "bg-emerald-950/70 text-emerald-300"
                   : t.status === "LOSS" ? "bg-rose-950/70 text-rose-300"
                   : "bg-slate-800/70 text-slate-400";
    return `
      <tr class="stripe-row border-b border-slate-800/60">
        <td class="px-3 py-2 text-slate-400 tabnum">#${t.id}</td>
        <td class="px-3 py-2 font-semibold text-white">${escapeHtml(t.symbol)}</td>
        <td class="px-3 py-2 font-bold ${t.side === "BUY" ? "text-emerald-400" : "text-rose-400"}">${t.side}</td>
        <td class="px-3 py-2">${modeTag(t.mode)}</td>
        <td class="px-3 py-2 text-[10px]">${tfHierarchy(t.htf_analysis, t.entry_timeframe)}</td>
        <td class="px-3 py-2 text-right tabnum text-slate-200">${fmt(t.symbol, t.entry_price)}</td>
        <td class="px-3 py-2 text-right tabnum text-slate-200">${t.exit_price != null ? fmt(t.symbol, t.exit_price) : "—"}</td>
        <td class="px-3 py-2 text-right tabnum text-sky-300">${Number(t.lot_size).toFixed(2)}</td>
        <td class="px-3 py-2 text-slate-400 max-w-[220px] truncate" title="${escapeHtml(t.strategy)}">${escapeHtml(t.strategy)}</td>
        <td class="px-3 py-2"><span class="tag ${statCls}">${t.status}</span></td>
        <td class="px-3 py-2 text-right tabnum">${fmtPnl(t.pnl)}</td>
        <td class="px-3 py-2 text-slate-500 tabnum text-[10px]">${(t.closed_at || "").replace("T"," ").slice(0,16)}</td>
      </tr>`;
  }).join("");
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
        <td class="px-3 py-2 text-slate-200 max-w-[280px] truncate" title="${escapeHtml(s.name)}">${escapeHtml(s.name)}</td>
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
// RENDER: MACRO + COT + CALENDAR + CB
// ===================================================================
function renderMacro(d) {
  document.getElementById("macroVix").textContent = Number(d.vix).toFixed(2);
  document.getElementById("macro10y").textContent = Number(d.us10y).toFixed(3) + "%";
  document.getElementById("macroDxy").textContent = Number(d.dxy).toFixed(3);
  document.getElementById("macroGsr").textContent = Number(d.gold_silver_ratio).toFixed(2);
  document.getElementById("macroRegime").textContent = d.regime;
  document.getElementById("macroHaven").textContent = d.safe_haven;
}

function renderCOT(cot) {
  const body = document.getElementById("tblCot");
  body.innerHTML = Object.keys(cot).map(name => {
    const c = cot[name];
    const dCls = c.delta_net > 0 ? "text-emerald-400" : c.delta_net < 0 ? "text-rose-400" : "text-slate-400";
    return `
      <tr class="stripe-row border-b border-slate-800/60">
        <td class="px-3 py-2 font-semibold text-white">${escapeHtml(name)}</td>
        <td class="px-3 py-2 text-right tabnum text-emerald-300">${c.long.toLocaleString()}</td>
        <td class="px-3 py-2 text-right tabnum text-rose-300">${c.short.toLocaleString()}</td>
        <td class="px-3 py-2 text-right tabnum text-white font-bold">${c.net.toLocaleString()}</td>
        <td class="px-3 py-2 text-right tabnum text-sky-300">${c.long_pct.toFixed(1)}%</td>
        <td class="px-3 py-2 text-right tabnum ${dCls}">${c.delta_net >= 0 ? "+" : ""}${c.delta_net.toLocaleString()}</td>
      </tr>`;
  }).join("");
}

function renderCB(cb) {
  const el = document.getElementById("cbGrid");
  el.innerHTML = Object.keys(cb).map(key => {
    const c = cb[key];
    return `
      <div class="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
        <div class="flex items-baseline justify-between mb-2">
          <div class="font-bold text-white text-sm">${escapeHtml(c.name)}</div>
          <div class="text-[10px] text-slate-500">${escapeHtml(c.currency)} · ${Number(c.rate).toFixed(3)}%</div>
        </div>
        <div class="text-[10px] text-slate-500 mb-2">Next meeting in ${c.next_meeting_days} days</div>
        <div class="space-y-1.5">
          <div>
            <div class="flex justify-between text-[10px] mb-0.5">
              <span class="text-rose-300">Cut</span>
              <span class="text-white font-semibold tabnum">${c.prob_cut.toFixed(1)}%</span>
            </div>
            <div class="h-1.5 bg-slate-800 rounded-full overflow-hidden">
              <div class="h-full bg-rose-500" style="width:${c.prob_cut}%"></div>
            </div>
          </div>
          <div>
            <div class="flex justify-between text-[10px] mb-0.5">
              <span class="text-slate-300">Hold</span>
              <span class="text-white font-semibold tabnum">${c.prob_hold.toFixed(1)}%</span>
            </div>
            <div class="h-1.5 bg-slate-800 rounded-full overflow-hidden">
              <div class="h-full bg-slate-500" style="width:${c.prob_hold}%"></div>
            </div>
          </div>
          <div>
            <div class="flex justify-between text-[10px] mb-0.5">
              <span class="text-emerald-300">Hike</span>
              <span class="text-white font-semibold tabnum">${c.prob_hike.toFixed(1)}%</span>
            </div>
            <div class="h-1.5 bg-slate-800 rounded-full overflow-hidden">
              <div class="h-full bg-emerald-500" style="width:${c.prob_hike}%"></div>
            </div>
          </div>
        </div>
      </div>`;
  }).join("");
}

function renderCalendar(events) {
  const body = document.getElementById("tblCalendar");
  body.innerHTML = events.map(e => {
    const impCls = e.impact === "HIGH" ? "bg-rose-950/70 text-rose-300"
                 : e.impact === "MEDIUM" ? "bg-amber-950/70 text-amber-300"
                 : "bg-slate-800/70 text-slate-400";
    return `
      <tr class="stripe-row border-b border-slate-800/60">
        <td class="px-3 py-2 text-slate-200 max-w-[260px] truncate">${escapeHtml(e.event)}</td>
        <td class="px-3 py-2 font-semibold text-sky-300">${escapeHtml(e.currency)}</td>
        <td class="px-3 py-2"><span class="tag ${impCls}">${e.impact}</span></td>
        <td class="px-3 py-2 text-slate-400 text-[11px]">${escapeHtml(e.when_str)}</td>
        <td class="px-3 py-2 text-right tabnum text-slate-300">${escapeHtml(e.forecast)}</td>
        <td class="px-3 py-2 text-right tabnum text-slate-500">${escapeHtml(e.previous)}</td>
      </tr>`;
  }).join("");
}

function renderLearning(list) {
  const el = document.getElementById("learnList");
  if (!list || list.length === 0) {
    el.innerHTML = `<div class="text-center text-slate-500 py-8 text-xs">No lessons yet — losses will appear here automatically</div>`;
    return;
  }
  el.innerHTML = list.map(l => `
    <div class="px-5 py-3 flex gap-3 items-start">
      <div class="shrink-0 w-2 h-2 rounded-full bg-amber-400 mt-1.5"></div>
      <div class="flex-1 min-w-0">
        <div class="flex flex-wrap items-center gap-2 text-[11px] mb-1">
          <span class="font-bold text-white">${escapeHtml(l.symbol || "?")}</span>
          <span class="text-slate-600">·</span>
          <span class="text-amber-300">${escapeHtml(l.strategy || "?")}</span>
          ${l.mode ? `<span class="text-slate-600">·</span><span class="text-cyan-300">${escapeHtml(l.mode)}</span>` : ""}
          <span class="text-slate-600">·</span>
          <span class="text-slate-500 tabnum">#${l.trade_id || "?"}</span>
          <span class="text-slate-600 ml-auto">${(l.created_at || "").replace("T"," ").slice(0,19)}</span>
        </div>
        <div class="text-[12px] text-slate-300 leading-relaxed">${escapeHtml(l.lesson)}</div>
      </div>
    </div>`).join("");
}

// ===================================================================
// FORM
// ===================================================================
function populateSelects() {
  document.getElementById("selSymbol").innerHTML =
    Object.keys(SYMBOLS).map(s => `<option value="${s}">${s} · ${SYMBOLS[s].label}</option>`).join("");

  document.getElementById("selStrategy").innerHTML =
    STRATEGIES.map(s => `<option value="${s}">${s}</option>`).join("");

  document.getElementById("selMode").innerHTML =
    Object.keys(MODES).map(m => `<option value="${m}">${MODES[m].label}</option>`).join("");

  refreshEntryTFOptions();
  refreshHTFDisplay();
  applyDefaults();
}

function refreshEntryTFOptions() {
  const mode = document.getElementById("selMode").value;
  const tfs = MODES[mode].entry_tfs;
  document.getElementById("selEntryTF").innerHTML =
    tfs.map(tf => `<option value="${tf}">${tf}</option>`).join("");
  if (tfs.length === 1) {
    document.getElementById("selEntryTF").disabled = true;
  } else {
    document.getElementById("selEntryTF").disabled = false;
  }
}

function refreshHTFDisplay() {
  const mode = document.getElementById("selMode").value;
  document.getElementById("htfDisplay").textContent = MODES[mode].htf.join(" · ");
}

function applyDefaults() {
  const sym = document.getElementById("selSymbol").value;
  const side = document.getElementById("selSide").value;
  const mode = document.getElementById("selMode").value;
  const entryType = document.getElementById("selEntryType").value;

  const cfg = SYMBOLS[sym];
  const dist = (DEFAULT_DISTS[sym] || DEFAULT_DISTS._fx)[mode];
  const [slD, tpD] = dist;

  // Entry
  let entry;
  if (entryType === "MARKET" || !state.prices[sym]) {
    entry = state.prices[sym] ? state.prices[sym].price : cfg.pip * 100;
  } else {
    const current = parseFloat(document.getElementById("inpEntry").value);
    if (isFinite(current)) {
      entry = current;
    } else {
      entry = state.prices[sym] ? state.prices[sym].price : cfg.pip * 100;
    }
  }

  const sl = side === "BUY" ? entry - slD : entry + slD;
  const tp = side === "BUY" ? entry + tpD : entry - tpD;

  document.getElementById("inpEntry").value = entry.toFixed(cfg.decimals);
  document.getElementById("inpSL").value = sl.toFixed(cfg.decimals);
  document.getElementById("inpTP").value = tp.toFixed(cfg.decimals);

  const entryInput = document.getElementById("inpEntry");
  if (entryType === "MARKET") {
    entryInput.setAttribute("readonly", "readonly");
    entryInput.classList.add("opacity-60", "cursor-not-allowed");
  } else {
    entryInput.removeAttribute("readonly");
    entryInput.classList.remove("opacity-60", "cursor-not-allowed");
  }

  updateLotPreview();
}

function updateLotPreview() {
  const sym = document.getElementById("selSymbol").value;
  const entry = parseFloat(document.getElementById("inpEntry").value);
  const sl = parseFloat(document.getElementById("inpSL").value);
  const cap = state.settings.capital;
  const risk = state.settings.risk_percent;
  const lotEl = document.getElementById("lotDisplay");

  if (!isFinite(entry) || !isFinite(sl) || entry === sl) {
    lotEl.textContent = "0.00";
    return;
  }
  const dist = Math.abs(entry - sl);
  const mult = SYMBOLS[sym].mult;
  const riskAmt = cap * (risk / 100.0);
  const lot = riskAmt / (dist * mult);
  lotEl.textContent = Math.max(0.01, lot).toFixed(2);
}

// ===================================================================
// ACTIONS
// ===================================================================
async function saveSettings() {
  const cap = parseFloat(document.getElementById("inpCapital").value);
  const risk = parseFloat(document.getElementById("inpRisk").value);
  const st = document.getElementById("settingsStatus");
  if (!isFinite(cap) || cap <= 0) { setStatus(st, "Capital must be > 0", "err"); return; }
  if (!isFinite(risk) || risk <= 0 || risk > 100) { setStatus(st, "Risk must be (0, 100]", "err"); return; }
  try {
    await api("/api/settings", "POST", { capital: cap, risk_percent: risk });
    state.settings.capital = cap;
    state.settings.risk_percent = risk;
    setStatus(st, "Settings saved permanently", "ok");
    updateLotPreview();
    pollSummary();
  } catch (e) { setStatus(st, e.message, "err"); }
}

async function dispatchTrade() {
  const st = document.getElementById("dispatchStatus");
  const sym = document.getElementById("selSymbol").value;
  const side = document.getElementById("selSide").value;
  const mode = document.getElementById("selMode").value;
  const entryType = document.getElementById("selEntryType").value;
  const entryTF = document.getElementById("selEntryTF").value;
  const strat = document.getElementById("selStrategy").value;
  const entry = parseFloat(document.getElementById("inpEntry").value);
  const sl = parseFloat(document.getElementById("inpSL").value);
  const tp = parseFloat(document.getElementById("inpTP").value);

  if (!isFinite(entry) || !isFinite(sl) || !isFinite(tp)) {
    setStatus(st, "Invalid entry/SL/TP", "err"); return;
  }

  const payload = {
    symbol: sym, side, mode, entry_type: entryType,
    entry_timeframe: entryTF, strategy: strat,
    stop_loss: sl, take_profit: tp,
  };
  if (entryType === "LIMIT") payload.entry_price = entry;

  try {
    const r = await api("/api/trades", "POST", payload);
    setStatus(st, `Trade #${r.data.id} ${entryType === "MARKET" ? "dispatched" : "placed"} · lot ${r.data.lot_size}`, "ok");
    pollTrades(); pollSummary(); pollStrategies();
  } catch (e) { setStatus(st, e.message, "err"); }
}

async function dispatchAuto() {
  const st = document.getElementById("dispatchStatus");
  const mode = document.getElementById("selMode").value;
  try {
    const r = await api("/api/auto_dispatch", "POST", { mode });
    setStatus(st, `AUTO #${r.data.id} · ${r.data.symbol} ${r.data.side} · ${r.data.mode} · ${r.data.entry_timeframe}`, "ok");
    pollTrades(); pollSummary(); pollStrategies();
  } catch (e) { setStatus(st, e.message, "err"); }
}

async function clearLearning() {
  if (!confirm("Clear all self-learning entries?")) return;
  try {
    await api("/api/self_learning/reset", "POST", {});
    pollLearning();
  } catch (e) { alert("Failed: " + e.message); }
}

// ===================================================================
// POLLING
// ===================================================================
async function pollPrices() {
  try {
    const r = await api("/api/prices");
    renderPrices(r.data);
    // Keep MARKET entry price synced
    if (document.getElementById("selEntryType").value === "MARKET") {
      const sym = document.getElementById("selSymbol").value;
      if (state.prices[sym]) {
        const dec = SYMBOLS[sym].decimals;
        document.getElementById("inpEntry").value = Number(state.prices[sym].price).toFixed(dec);
        updateLotPreview();
      }
    }
  } catch (e) { console.error("prices:", e); }
}

async function pollSummary() {
  try { const r = await api("/api/summary"); renderSummary(r.data); }
  catch (e) { console.error("summary:", e); }
}

async function pollTrades() {
  try {
    const r = await api("/api/trades?limit=300");
    renderActive(r.data);
    renderPending(r.data);
    renderHistory(r.data);
  } catch (e) { console.error("trades:", e); }
}

async function pollStrategies() {
  try { const r = await api("/api/strategies"); renderStrategies(r.data); }
  catch (e) { console.error("strategies:", e); }
}

async function pollMacro() {
  try { const r = await api("/api/macro"); renderMacro(r.data); }
  catch (e) { console.error("macro:", e); }
}

async function pollCOT() {
  try { const r = await api("/api/cot"); renderCOT(r.data); }
  catch (e) { console.error("cot:", e); }
}

async function pollCB() {
  try { const r = await api("/api/central_banks"); renderCB(r.data); }
  catch (e) { console.error("cb:", e); }
}

async function pollCalendar() {
  try { const r = await api("/api/calendar"); renderCalendar(r.data); }
  catch (e) { console.error("calendar:", e); }
}

async function pollLearning() {
  try { const r = await api("/api/self_learning?limit=40"); renderLearning(r.data); }
  catch (e) { console.error("learning:", e); }
}

// ===================================================================
// BOOT
// ===================================================================
async function boot() {
  document.getElementById("year").textContent = new Date().getFullYear();
  populateSelects();

  // Event listeners
  document.getElementById("selSymbol").addEventListener("change", applyDefaults);
  document.getElementById("selSide").addEventListener("change", applyDefaults);
  document.getElementById("selMode").addEventListener("change", () => {
    refreshEntryTFOptions();
    refreshHTFDisplay();
    applyDefaults();
  });
  document.getElementById("selEntryType").addEventListener("change", applyDefaults);
  document.getElementById("selEntryTF").addEventListener("change", () => {});
  document.getElementById("inpEntry").addEventListener("input", updateLotPreview);
  document.getElementById("inpSL").addEventListener("input", updateLotPreview);
  document.getElementById("inpTP").addEventListener("input", updateLotPreview);
  document.getElementById("btnSaveSettings").addEventListener("click", saveSettings);
  document.getElementById("btnDispatch").addEventListener("click", dispatchTrade);
  document.getElementById("btnAutoDispatch").addEventListener("click", dispatchAuto);
  document.getElementById("btnClearLearn").addEventListener("click", clearLearning);

  // Initial fetches
  await Promise.all([pollPrices(), pollSummary(), pollStrategies(),
                     pollMacro(), pollCOT(), pollCB(), pollCalendar(),
                     pollTrades(), pollLearning()]);
  applyDefaults();

  // Intervals
  setInterval(pollPrices, 1000);
  setInterval(pollSummary, 3000);
  setInterval(pollTrades, 2500);
  setInterval(pollStrategies, 5000);
  setInterval(pollMacro, 3000);
  setInterval(pollCOT, 8000);
  setInterval(pollCB, 10000);
  setInterval(pollCalendar, 30000);
  setInterval(pollLearning, 5000);
}

boot();
</script>
</body>
</html>
"""


# ============================================================================
# SIGNALS & MAIN
# ============================================================================
def _handle_signal(signum, frame):
    print(f"[signal] received {signum}, shutting down...", flush=True)
    SHUTDOWN.set()


def main():
    init_db()
    print(f"[startup] DB: {DB_PATH}", flush=True)
    print(f"[startup] Listening on {HOST}:{PORT}", flush=True)

    threads = [
        threading.Thread(target=price_engine,    daemon=True, name="price_engine"),
        threading.Thread(target=macro_engine,    daemon=True, name="macro_engine"),
        threading.Thread(target=trade_evaluator, daemon=True, name="trade_evaluator"),
    ]
    for t in threads:
        t.start()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    server = HTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[server] KeyboardInterrupt", flush=True)
    finally:
        SHUTDOWN.set()
        server.server_close()
        for t in threads:
            t.join(timeout=3.0)
        print("[shutdown] complete", flush=True)


if __name__ == "__main__":
    main()

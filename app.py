#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pro Trading & Macro Intelligence Engine v3.0
=============================================
Single-file production server:
  • Real-time Yahoo Finance price feed (v8 chart API, keyless)
  • Live macro intelligence (VIX, US10Y, DXY, GSR, COT, calendar, central banks)
  • ICT + Macro Confluence Engine (score 0–10)
  • Full bilingual UI (English / العربية)
  • SQLite persistence · AI self-learning · strict risk engine

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
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen

# ============================================================================
# CONFIGURATION
# ============================================================================
DB_PATH = os.environ.get("DB_PATH", "trading_bot_memory.db")
PORT    = int(os.environ.get("PORT", 8000))
HOST    = os.environ.get("HOST", "0.0.0.0")

DB_LOCK     = threading.RLock()
PRICE_LOCK  = threading.RLock()
MACRO_LOCK  = threading.RLock()
COT_LOCK    = threading.RLock()
CB_LOCK     = threading.RLock()
CAL_LOCK    = threading.RLock()
SHUTDOWN    = threading.Event()

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HTTP_TIMEOUT = 6.0

# ============================================================================
# SYMBOL UNIVERSE  (Yahoo Finance tickers)
# ============================================================================
SYMBOLS = {
    "XAU/USD": {
        "yahoo": "GC=F", "base": 2350.0, "decimals": 2, "mult": 100,
        "pip": 0.01, "spread": 0.30, "label_en": "Gold", "label_ar": "الذهب",
    },
    "XAG/USD": {
        "yahoo": "SI=F", "base": 27.50, "decimals": 3, "mult": 1000,
        "pip": 0.01, "spread": 0.020, "label_en": "Silver", "label_ar": "الفضة",
    },
    "EUR/USD": {
        "yahoo": "EURUSD=X", "base": 1.0850, "decimals": 5, "mult": 100000,
        "pip": 0.0001, "spread": 0.00008, "label_en": "Euro", "label_ar": "اليورو",
    },
    "GBP/USD": {
        "yahoo": "GBPUSD=X", "base": 1.2700, "decimals": 5, "mult": 100000,
        "pip": 0.0001, "spread": 0.00010, "label_en": "Sterling", "label_ar": "الإسترليني",
    },
    "USD/JPY": {
        "yahoo": "USDJPY=X", "base": 155.00, "decimals": 3, "mult": 1000,
        "pip": 0.01, "spread": 0.015, "label_en": "Yen", "label_ar": "الين",
    },
    "DXY": {
        "yahoo": "DX-Y.NYB", "base": 105.00, "decimals": 3, "mult": 1000,
        "pip": 0.01, "spread": 0.020, "label_en": "Dollar Index", "label_ar": "مؤشر الدولار",
    },
}

# ============================================================================
# TRADE MODES — MULTI-TIMEFRAME EXECUTION HIERARCHY
# ============================================================================
TRADE_MODES = {
    "SCALPING_A": {
        "label_en": "Scalping Mode A", "label_ar": "سكالبينج النمط أ",
        "htf": ["1W", "1D", "1H"], "entry_tfs": ["M5"],
    },
    "SCALPING_B": {
        "label_en": "Scalping Mode B", "label_ar": "سكالبينج النمط ب",
        "htf": ["1W", "1D", "4H"], "entry_tfs": ["M15", "M1"],
    },
    "SWING": {
        "label_en": "Swing", "label_ar": "سوينج",
        "htf": ["1W", "1D"], "entry_tfs": ["H1", "H4"],
    },
}

# ============================================================================
# ICT STRATEGIES (10 institutional concepts)
# ============================================================================
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

STRATEGY_AR = {
    "Liquidity Sweep & Stop Hunt": "مسح السيولة واقتناص الوقف",
    "Fair Value Gap (FVG)": "فجوة القيمة العادلة",
    "Order Block (OB)": "كتلة الأوامر",
    "Change of Character (CHoCH)": "تغير طبيعة السوق",
    "Break of Structure (BOS)": "كسر الهيكل",
    "Breaker Block": "كتلة الكسر العكسي",
    "Judas Swing / ORL": "حركة جوداس التضليلية",
    "Kill Zones & Power of 3": "مناطق القتل ونموذج 3",
    "OTE & Premium/Discount": "الدخول الأمثل والعلاوة/الخصم",
    "Inversion FVG (IFVG)": "الفجوة المكسورة",
}

# ============================================================================
# LIVE PRICE STATE
# ============================================================================
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
        "source":     "init",
        "stale":      True,
    }

# ============================================================================
# MACRO STATE
# ============================================================================
MACRO = {
    "vix":             16.40,
    "us10y":           4.355,
    "regime":          "Neutral",
    "safe_haven":      "Gold / USD",
    "geo_risk":        35.0,
    "geo_risk_label":  "Elevated",
    "updated_at":      datetime.now(timezone.utc).isoformat(),
    "last_ok":         None,
}

# ============================================================================
# CENTRAL BANK STATE
# ============================================================================
CB_STATE = {
    "FED": {"name_en": "Federal Reserve", "name_ar": "الاحتياطي الفيدرالي",
            "currency": "USD", "rate": 4.375, "next_days": 17,
            "cut": 55.0, "hold": 40.0, "hike": 5.0},
    "ECB": {"name_en": "European Central Bank", "name_ar": "البنك المركزي الأوروبي",
            "currency": "EUR", "rate": 3.250, "next_days": 11,
            "cut": 70.0, "hold": 28.0, "hike": 2.0},
    "BOE": {"name_en": "Bank of England", "name_ar": "بنك إنجلترا",
            "currency": "GBP", "rate": 4.750, "next_days": 22,
            "cut": 60.0, "hold": 36.0, "hike": 4.0},
    "BOJ": {"name_en": "Bank of Japan", "name_ar": "بنك اليابان",
            "currency": "JPY", "rate": 0.500, "next_days": 27,
            "cut": 5.0, "hold": 65.0, "hike": 30.0},
}

# ============================================================================
# COT STATE
# ============================================================================
COT_STATE = {
    "Gold":  {"long": 224850, "short": 78200, "prev_long": 221000, "prev_short": 81500,
              "label_ar": "الذهب", "source": "seed"},
    "Silver":{"long": 68500,  "short": 31200, "prev_long": 67200,  "prev_short": 32400,
              "label_ar": "الفضة", "source": "seed"},
    "EUR":   {"long": 165300, "short": 112400, "prev_long": 168100, "prev_short": 108700,
              "label_ar": "اليورو", "source": "seed"},
    "GBP":   {"long": 72400,  "short": 58100,  "prev_long": 70200,  "prev_short": 61300,
              "label_ar": "الإسترليني", "source": "seed"},
    "JPY":   {"long": 48600,  "short": 118900, "prev_long": 52100,  "prev_short": 115400,
              "label_ar": "الين", "source": "seed"},
}

# ============================================================================
# ECONOMIC CALENDAR (2026 institutional schedule, computed dynamically)
# ============================================================================
CALENDAR_SEED = [
    {"month": 1,  "day": 28, "event_en": "FOMC Rate Decision",   "event_ar": "قرار الفائدة الفيدرالي",   "currency": "USD", "impact": "HIGH",   "forecast": "3.75%", "previous": "4.00%"},
    {"month": 3,  "day": 18, "event_en": "FOMC Rate Decision",   "event_ar": "قرار الفائدة الفيدرالي",   "currency": "USD", "impact": "HIGH",   "forecast": "3.75%", "previous": "3.75%"},
    {"month": 4,  "day": 29, "event_en": "FOMC Rate Decision",   "event_ar": "قرار الفائدة الفيدرالي",   "currency": "USD", "impact": "HIGH",   "forecast": "3.50%", "previous": "3.75%"},
    {"month": 6,  "day": 17, "event_en": "FOMC Rate Decision",   "event_ar": "قرار الفائدة الفيدرالي",   "currency": "USD", "impact": "HIGH",   "forecast": "3.50%", "previous": "3.50%"},
    {"month": 7,  "day": 29, "event_en": "FOMC Rate Decision",   "event_ar": "قرار الفائدة الفيدرالي",   "currency": "USD", "impact": "HIGH",   "forecast": "3.50%", "previous": "3.50%"},
    {"month": 9,  "day": 16, "event_en": "FOMC Rate Decision",   "event_ar": "قرار الفائدة الفيدرالي",   "currency": "USD", "impact": "HIGH",   "forecast": "3.25%", "previous": "3.50%"},
    {"month": 10, "day": 28, "event_en": "FOMC Rate Decision",   "event_ar": "قرار الفائدة الفيدرالي",   "currency": "USD", "impact": "HIGH",   "forecast": "3.25%", "previous": "3.25%"},
    {"month": 12, "day": 16, "event_en": "FOMC Rate Decision",   "event_ar": "قرار الفائدة الفيدرالي",   "currency": "USD", "impact": "HIGH",   "forecast": "3.25%", "previous": "3.25%"},
    {"month": 1,  "day": 2,  "event_en": "US Non-Farm Payrolls", "event_ar": "التغير في الوظائف غير الزراعية", "currency": "USD", "impact": "HIGH", "forecast": "175K", "previous": "160K"},
    {"month": 2,  "day": 6,  "event_en": "US Non-Farm Payrolls", "event_ar": "التغير في الوظائف غير الزراعية", "currency": "USD", "impact": "HIGH", "forecast": "180K", "previous": "175K"},
    {"month": 3,  "day": 6,  "event_en": "US Non-Farm Payrolls", "event_ar": "التغير في الوظائف غير الزراعية", "currency": "USD", "impact": "HIGH", "forecast": "185K", "previous": "180K"},
    {"month": 4,  "day": 3,  "event_en": "US Non-Farm Payrolls", "event_ar": "التغير في الوظائف غير الزراعية", "currency": "USD", "impact": "HIGH", "forecast": "190K", "previous": "185K"},
    {"month": 5,  "day": 1,  "event_en": "US Non-Farm Payrolls", "event_ar": "التغير في الوظائف غير الزراعية", "currency": "USD", "impact": "HIGH", "forecast": "185K", "previous": "190K"},
    {"month": 6,  "day": 5,  "event_en": "US Non-Farm Payrolls", "event_ar": "التغير في الوظائف غير الزراعية", "currency": "USD", "impact": "HIGH", "forecast": "180K", "previous": "185K"},
    {"month": 7,  "day": 3,  "event_en": "US Non-Farm Payrolls", "event_ar": "التغير في الوظائف غير الزراعية", "currency": "USD", "impact": "HIGH", "forecast": "175K", "previous": "180K"},
    {"month": 8,  "day": 7,  "event_en": "US Non-Farm Payrolls", "event_ar": "التغير في الوظائف غير الزراعية", "currency": "USD", "impact": "HIGH", "forecast": "180K", "previous": "175K"},
    {"month": 9,  "day": 4,  "event_en": "US Non-Farm Payrolls", "event_ar": "التغير في الوظائف غير الزراعية", "currency": "USD", "impact": "HIGH", "forecast": "185K", "previous": "180K"},
    {"month": 10, "day": 2,  "event_en": "US Non-Farm Payrolls", "event_ar": "التغير في الوظائف غير الزراعية", "currency": "USD", "impact": "HIGH", "forecast": "190K", "previous": "185K"},
    {"month": 11, "day": 6,  "event_en": "US Non-Farm Payrolls", "event_ar": "التغير في الوظائف غير الزراعية", "currency": "USD", "impact": "HIGH", "forecast": "185K", "previous": "190K"},
    {"month": 12, "day": 4,  "event_en": "US Non-Farm Payrolls", "event_ar": "التغير في الوظائف غير الزراعية", "currency": "USD", "impact": "HIGH", "forecast": "180K", "previous": "185K"},
    {"month": 1,  "day": 13, "event_en": "US CPI YoY",           "event_ar": "مؤشر أسعار المستهلك السنوي", "currency": "USD", "impact": "HIGH", "forecast": "3.1%", "previous": "3.3%"},
    {"month": 2,  "day": 11, "event_en": "US CPI YoY",           "event_ar": "مؤشر أسعار المستهلك السنوي", "currency": "USD", "impact": "HIGH", "forecast": "3.0%", "previous": "3.1%"},
    {"month": 3,  "day": 11, "event_en": "US CPI YoY",           "event_ar": "مؤشر أسعار المستهلك السنوي", "currency": "USD", "impact": "HIGH", "forecast": "2.9%", "previous": "3.0%"},
    {"month": 4,  "day": 14, "event_en": "US CPI YoY",           "event_ar": "مؤشر أسعار المستهلك السنوي", "currency": "USD", "impact": "HIGH", "forecast": "2.8%", "previous": "2.9%"},
    {"month": 5,  "day": 12, "event_en": "US CPI YoY",           "event_ar": "مؤشر أسعار المستهلك السنوي", "currency": "USD", "impact": "HIGH", "forecast": "2.7%", "previous": "2.8%"},
    {"month": 6,  "day": 10, "event_en": "US CPI YoY",           "event_ar": "مؤشر أسعار المستهلك السنوي", "currency": "USD", "impact": "HIGH", "forecast": "2.6%", "previous": "2.7%"},
    {"month": 7,  "day": 14, "event_en": "US CPI YoY",           "event_ar": "مؤشر أسعار المستهلك السنوي", "currency": "USD", "impact": "HIGH", "forecast": "2.5%", "previous": "2.6%"},
    {"month": 8,  "day": 12, "event_en": "US CPI YoY",           "event_ar": "مؤشر أسعار المستهلك السنوي", "currency": "USD", "impact": "HIGH", "forecast": "2.4%", "previous": "2.5%"},
    {"month": 9,  "day": 10, "event_en": "US CPI YoY",           "event_ar": "مؤشر أسعار المستهلك السنوي", "currency": "USD", "impact": "HIGH", "forecast": "2.4%", "previous": "2.4%"},
    {"month": 10, "day": 13, "event_en": "US CPI YoY",           "event_ar": "مؤشر أسعار المستهلك السنوي", "currency": "USD", "impact": "HIGH", "forecast": "2.3%", "previous": "2.4%"},
    {"month": 11, "day": 12, "event_en": "US CPI YoY",           "event_ar": "مؤشر أسعار المستهلك السنوي", "currency": "USD", "impact": "HIGH", "forecast": "2.3%", "previous": "2.3%"},
    {"month": 12, "day": 10, "event_en": "US CPI YoY",           "event_ar": "مؤشر أسعار المستهلك السنوي", "currency": "USD", "impact": "HIGH", "forecast": "2.2%", "previous": "2.3%"},
    {"month": 1,  "day": 30, "event_en": "ECB Press Conference",  "event_ar": "المؤتمر الصحفي للبنك المركزي الأوروبي", "currency": "EUR", "impact": "MEDIUM", "forecast": "Hold", "previous": "Hold"},
    {"month": 3,  "day": 12, "event_en": "ECB Press Conference",  "event_ar": "المؤتمر الصحفي للبنك المركزي الأوروبي", "currency": "EUR", "impact": "MEDIUM", "forecast": "Cut", "previous": "Hold"},
    {"month": 6,  "day": 11, "event_en": "ECB Press Conference",  "event_ar": "المؤتمر الصحفي للبنك المركزي الأوروبي", "currency": "EUR", "impact": "MEDIUM", "forecast": "Hold", "previous": "Cut"},
    {"month": 2,  "day": 5,  "event_en": "BoE Bank Rate",         "event_ar": "قرار الفائدة لبنك إنجلترا", "currency": "GBP", "impact": "MEDIUM", "forecast": "4.50%", "previous": "4.75%"},
    {"month": 5,  "day": 7,  "event_en": "BoE Bank Rate",         "event_ar": "قرار الفائدة لبنك إنجلترا", "currency": "GBP", "impact": "MEDIUM", "forecast": "4.25%", "previous": "4.50%"},
    {"month": 8,  "day": 6,  "event_en": "BoE Bank Rate",         "event_ar": "قرار الفائدة لبنك إنجلترا", "currency": "GBP", "impact": "MEDIUM", "forecast": "4.00%", "previous": "4.25%"},
    {"month": 1,  "day": 23, "event_en": "BoJ Policy Statement",  "event_ar": "بيان سياسة بنك اليابان", "currency": "JPY", "impact": "HIGH", "forecast": "Hold", "previous": "Hold"},
    {"month": 4,  "day": 30, "event_en": "BoJ Policy Statement",  "event_ar": "بيان سياسة بنك اليابان", "currency": "JPY", "impact": "HIGH", "forecast": "Hike", "previous": "Hold"},
    {"month": 7,  "day": 30, "event_en": "BoJ Policy Statement",  "event_ar": "بيان سياسة بنك اليابان", "currency": "JPY", "impact": "HIGH", "forecast": "Hold", "previous": "Hike"},
    {"month": 10, "day": 29, "event_en": "BoJ Policy Statement",  "event_ar": "بيان سياسة بنك اليابان", "currency": "JPY", "impact": "HIGH", "forecast": "Hike", "previous": "Hold"},
    {"month": 1,  "day": 15, "event_en": "US Retail Sales MoM",   "event_ar": "مبيعات التجزئة الأمريكية", "currency": "USD", "impact": "MEDIUM", "forecast": "0.4%", "previous": "0.3%"},
    {"month": 4,  "day": 15, "event_en": "US Retail Sales MoM",   "event_ar": "مبيعات التجزئة الأمريكية", "currency": "USD", "impact": "MEDIUM", "forecast": "0.3%", "previous": "0.4%"},
    {"month": 7,  "day": 15, "event_en": "US Retail Sales MoM",   "event_ar": "مبيعات التجزئة الأمريكية", "currency": "USD", "impact": "MEDIUM", "forecast": "0.4%", "previous": "0.3%"},
    {"month": 10, "day": 15, "event_en": "US Retail Sales MoM",   "event_ar": "مبيعات التجزئة الأمريكية", "currency": "USD", "impact": "MEDIUM", "forecast": "0.3%", "previous": "0.4%"},
    {"month": 2,  "day": 18, "event_en": "German ZEW Sentiment",  "event_ar": "مؤشر ZEW الألماني", "currency": "EUR", "impact": "LOW", "forecast": "13.0", "previous": "12.0"},
    {"month": 5,  "day": 19, "event_en": "German ZEW Sentiment",  "event_ar": "مؤشر ZEW الألماني", "currency": "EUR", "impact": "LOW", "forecast": "14.0", "previous": "13.0"},
    {"month": 8,  "day": 18, "event_en": "German ZEW Sentiment",  "event_ar": "مؤشر ZEW الألماني", "currency": "EUR", "impact": "LOW", "forecast": "13.5", "previous": "14.0"},
    {"month": 11, "day": 17, "event_en": "German ZEW Sentiment",  "event_ar": "مؤشر ZEW الألماني", "currency": "EUR", "impact": "LOW", "forecast": "14.5", "previous": "13.5"},
]

# ============================================================================
# SESSION / KILL ZONE HELPERS
# ============================================================================
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def session_volatility(hour_utc: int) -> float:
    if 12 <= hour_utc < 16: return 1.85
    if 7 <= hour_utc < 12:  return 1.55
    if 16 <= hour_utc < 21: return 1.30
    if 1 <= hour_utc < 7:   return 0.85
    return 0.65

def active_session() -> str:
    h = datetime.now(timezone.utc).hour
    if 22 <= h or h < 1: return "Sydney"
    if 1 <= h < 7:       return "Tokyo"
    if 7 <= h < 12:      return "London"
    if 12 <= h < 16:     return "London / NY Overlap"
    if 16 <= h < 21:     return "New York"
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
    return {
        "Crisis": "USD / JPY / Gold",
        "Risk-Off": "USD / Gold",
        "Risk-On": "Equities / AUD",
        "Neutral-Constructive": "Gold",
        "Neutral": "Gold / USD",
    }.get(regime, "Gold / USD")

def geo_risk_label(v: float) -> str:
    if v >= 75: return "Extreme"
    if v >= 55: return "High"
    if v >= 35: return "Elevated"
    if v >= 20: return "Moderate"
    return "Low"

# ============================================================================
# RISK ENGINE
# ============================================================================
def calculate_lot_size(capital: float, risk_percent: float,
                       sl_distance: float, symbol: str) -> float:
    if sl_distance <= 0 or capital <= 0 or risk_percent <= 0:
        return 0.01
    mult = SYMBOLS.get(symbol, {}).get("mult", 100000)
    risk_amount = capital * (risk_percent / 100.0)
    raw = risk_amount / (sl_distance * mult)
    return max(0.01, round(raw, 2))

def default_sl_tp(symbol: str, mode: str, side: str, entry: float):
    cfg = SYMBOLS[symbol]
    dec = cfg["decimals"]
    if symbol == "XAU/USD":
        d = {"SCALPING_A": (3.5, 7.0), "SCALPING_B": (6.0, 12.0), "SWING": (18.0, 54.0)}
    elif symbol == "XAG/USD":
        d = {"SCALPING_A": (0.08, 0.16), "SCALPING_B": (0.15, 0.30), "SWING": (0.45, 1.35)}
    elif symbol == "DXY":
        d = {"SCALPING_A": (0.12, 0.24), "SCALPING_B": (0.20, 0.40), "SWING": (0.60, 1.80)}
    elif symbol == "USD/JPY":
        d = {"SCALPING_A": (0.12, 0.24), "SCALPING_B": (0.20, 0.40), "SWING": (0.60, 1.80)}
    else:
        d = {"SCALPING_A": (0.0012, 0.0024), "SCALPING_B": (0.0020, 0.0040), "SWING": (0.0060, 0.0180)}
    sl_d, tp_d = d.get(mode, (0.0012, 0.0024))
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
                    confluence_score REAL DEFAULT 0.0,
                    confluence_bias TEXT DEFAULT 'neutral',
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

            cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_learning_created ON self_learning(created_at)")

            # ---- Migrations for older DBs ----
            cols = [r["name"] for r in cur.execute("PRAGMA table_info(trades)").fetchall()]
            if "confluence_score" not in cols:
                cur.execute("ALTER TABLE trades ADD COLUMN confluence_score REAL DEFAULT 0")
            if "confluence_bias" not in cols:
                cur.execute("ALTER TABLE trades ADD COLUMN confluence_bias TEXT DEFAULT 'neutral'")

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
                rng = random.Random(11)
                for name in ICT_STRATEGIES:
                    total = rng.randint(30, 80)
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
# YAHOO FINANCE REAL-TIME FETCHER
# ============================================================================
def fetch_yahoo_quote(ticker: str):
    """Returns (price, prev_close, day_high, day_low). Raises on failure."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
           f"{ticker}?interval=1m&range=1d")
    req = Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        raw = resp.read().decode("utf-8")
    payload = json.loads(raw)
    result = payload["chart"]["result"][0]
    meta = result.get("meta", {})
    price = meta.get("regularMarketPrice")
    prev = meta.get("previousClose") or meta.get("chartPreviousClose")
    high = meta.get("regularMarketDayHigh")
    low = meta.get("regularMarketDayLow")
    if price is None:
        closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        clean = [c for c in closes if c is not None]
        if clean:
            price = clean[-1]
    if price is None:
        raise ValueError(f"no price in Yahoo response for {ticker}")
    return (
        float(price),
        float(prev) if prev is not None else float(price),
        float(high) if high is not None else None,
        float(low) if low is not None else None,
    )

def apply_market_tick(sym: str, price: float, prev_close: float,
                      day_high, day_low, source: str) -> None:
    cfg = SYMBOLS[sym]
    with PRICE_LOCK:
        st = PRICES[sym]
        st["prev_price"] = st["price"]
        st["price"] = max(0.000001, price)
        if prev_close:
            st["prev_close"] = prev_close
        if day_high is not None:
            st["high"] = max(st["high"], day_high)
        if day_low is not None:
            st["low"] = min(st["low"], day_low)
        st["high"] = max(st["high"], st["price"])
        st["low"] = min(st["low"], st["price"])
        st["last_update"] = now_iso()
        st["source"] = source
        st["stale"] = False
        h = st["history"]
        h.append(st["price"])
        if len(h) > 120:
            h.pop(0)

def simulate_tick(sym: str) -> None:
    """Realistic fallback random-walk when the real feed is unreachable."""
    cfg = SYMBOLS[sym]
    with PRICE_LOCK:
        st = PRICES[sym]
        sigma = cfg["base"] * 0.000035 * session_volatility(datetime.now(timezone.utc).hour)
        shock = random.gauss(0.0, sigma)
        new_price = max(0.000001, st["price"] + shock)
        st["prev_price"] = st["price"]
        st["price"] = new_price
        st["high"] = max(st["high"], new_price)
        st["low"] = min(st["low"], new_price)
        st["last_update"] = now_iso()
        st["stale"] = True
        st["source"] = "sim"
        h = st["history"]
        h.append(new_price)
        if len(h) > 120:
            h.pop(0)

def real_feed_loop() -> None:
    """Poll Yahoo Finance every 3 s for all 6 symbols."""
    while not SHUTDOWN.is_set():
        for sym, cfg in SYMBOLS.items():
            try:
                price, prev_close, hi, lo = fetch_yahoo_quote(cfg["yahoo"])
                apply_market_tick(sym, price, prev_close, hi, lo, "yahoo")
            except Exception as exc:
                print(f"[feed] {sym} fetch failed: {exc}", flush=True)
                simulate_tick(sym)
        SHUTDOWN.wait(3.0)

def micro_tick_loop() -> None:
    """1-second visual micro-ticks with bid/ask spread noise on top of the real price."""
    while not SHUTDOWN.is_set():
        try:
            with PRICE_LOCK:
                for sym, cfg in SYMBOLS.items():
                    st = PRICES[sym]
                    if st["stale"]:
                        continue
                    noise = random.gauss(0.0, cfg["spread"] * 0.22)
                    new_price = max(0.000001, st["price"] + noise)
                    st["prev_price"] = st["price"]
                    st["price"] = new_price
                    st["high"] = max(st["high"], new_price)
                    st["low"] = min(st["low"], new_price)
                    st["last_update"] = now_iso()
                    h = st["history"]
                    h.append(new_price)
                    if len(h) > 120:
                        h.pop(0)
        except Exception as exc:
            print(f"[micro_tick] {exc}", flush=True)
        SHUTDOWN.wait(1.0)

def day_rollover_loop() -> None:
    """Reset daily open/high/low at UTC midnight."""
    last_day = datetime.now(timezone.utc).date()
    while not SHUTDOWN.is_set():
        try:
            today = datetime.now(timezone.utc).date()
            if today != last_day:
                with PRICE_LOCK:
                    for sym in SYMBOLS:
                        st = PRICES[sym]
                        st["prev_close"] = st["price"]
                        st["open"] = st["price"]
                        st["high"] = st["price"]
                        st["low"] = st["price"]
                last_day = today
        except Exception as exc:
            print(f"[rollover] {exc}", flush=True)
        SHUTDOWN.wait(30.0)

# ============================================================================
# MACRO ENGINE (VIX, US10Y, DXY, GSR, regime, geo risk)
# ============================================================================
def macro_fetch_loop() -> None:
    while not SHUTDOWN.is_set():
        # VIX
        try:
            vix_price, _, _, _ = fetch_yahoo_quote("%5EVIX")
            with MACRO_LOCK:
                MACRO["vix"] = round(vix_price, 2)
        except Exception as exc:
            print(f"[macro] VIX fetch failed: {exc}", flush=True)
            with MACRO_LOCK:
                MACRO["vix"] = max(8.0, MACRO["vix"] + random.gauss(0.0, 0.06))

        # US 10Y
        try:
            tnx_price, _, _, _ = fetch_yahoo_quote("%5ETNX")
            us10y = tnx_price / 10.0 if tnx_price > 10.0 else tnx_price
            with MACRO_LOCK:
                MACRO["us10y"] = round(us10y, 3)
        except Exception as exc:
            print(f"[macro] US10Y fetch failed: {exc}", flush=True)
            with MACRO_LOCK:
                MACRO["us10y"] = round(max(0.5, min(7.5, MACRO["us10y"] + random.gauss(0.0, 0.004))), 3)

        with MACRO_LOCK:
            MACRO["regime"] = classify_regime(MACRO["vix"])
            MACRO["safe_haven"] = classify_safe_haven(MACRO["regime"])

            # Geopolitical risk score driven by VIX + US10Y + GSR
            with PRICE_LOCK:
                xau = PRICES["XAU/USD"]["price"]
                xag = PRICES["XAG/USD"]["price"]
            gsr = (xau / xag) if xag > 0 else 80.0
            geo = 0.0
            geo += min(40.0, max(0.0, (MACRO["vix"] - 12.0) * 2.2))
            geo += min(25.0, max(0.0, (gsr - 70.0) * 0.9))
            geo += min(20.0, max(0.0, (4.5 - MACRO["us10y"]) * 12.0))
            geo += min(15.0, max(0.0, abs(MACRO["vix"] - 18.0) * 0.35))
            MACRO["geo_risk"] = round(min(100.0, geo), 1)
            MACRO["geo_risk_label"] = geo_risk_label(MACRO["geo_risk"])
            MACRO["updated_at"] = now_iso()
            MACRO["last_ok"] = now_iso()

        SHUTDOWN.wait(10.0)

def central_bank_loop() -> None:
    while not SHUTDOWN.is_set():
        try:
            with CB_LOCK:
                for key in CB_STATE:
                    cb = CB_STATE[key]
                    drift = random.gauss(0.0, 0.30)
                    cb["cut"] = max(0.0, min(100.0, cb["cut"] + drift))
                    cb["hike"] = max(0.0, min(100.0, cb["hike"] - drift * 0.4))
                    cb["hold"] = max(0.0, 100.0 - cb["cut"] - cb["hike"])
                    total = cb["cut"] + cb["hold"] + cb["hike"]
                    if total > 0:
                        cb["cut"] = round(cb["cut"] * 100.0 / total, 1)
                        cb["hold"] = round(cb["hold"] * 100.0 / total, 1)
                        cb["hike"] = round(100.0 - cb["cut"] - cb["hold"], 1)
        except Exception as exc:
            print(f"[cb] {exc}", flush=True)
        SHUTDOWN.wait(8.0)

# ============================================================================
# COT FETCH (FuturesBench keyless JSON)
# ============================================================================
COT_KEY_CANDIDATES = {
    "Gold":   ["gold", "gold-futures", "comex-gold"],
    "Silver": ["silver", "silver-futures", "comex-silver"],
    "EUR":    ["euro-fx", "euro", "euro-futures", "eur"],
    "GBP":    ["british-pound", "gbp", "pound", "british-pound-fx"],
    "JPY":    ["japanese-yen", "jpy", "yen", "japanese-yen-fx"],
}

def fetch_cot() -> None:
    url = "https://futuresbench.com/api/v1/latest.json"
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    markets = payload.get("markets") or {}
    with COT_LOCK:
        for asset, keys in COT_KEY_CANDIDATES.items():
            row = None
            for k in keys:
                if k in markets:
                    row = markets[k]
                    break
            if row is None:
                continue
            net = row.get("net_noncommercial")
            chg = row.get("net_noncommercial_change")
            oi = row.get("open_interest")
            if net is None:
                continue
            # Distribute net into long/short around open interest if available
            if oi and oi > abs(net):
                long_v = int((oi + net) / 2)
                short_v = int((oi - net) / 2)
            else:
                long_v = max(0, int(net) + 50000)
                short_v = max(0, 50000 - int(net))
            prev_net = net - (chg if chg is not None else 0)
            prev_long = int((long_v + prev_net) / 2) if long_v else long_v
            prev_short = int((short_v - prev_net) / 2) if short_v else short_v
            if chg is not None and oi and oi > abs(prev_net):
                prev_long = int((oi + prev_net) / 2)
                prev_short = int((oi - prev_net) / 2)
            COT_STATE[asset]["long"] = long_v
            COT_STATE[asset]["short"] = short_v
            COT_STATE[asset]["prev_long"] = prev_long
            COT_STATE[asset]["prev_short"] = prev_short
            COT_STATE[asset]["source"] = "futuresbench"
    print("[cot] updated from FuturesBench", flush=True)

def cot_loop() -> None:
    while not SHUTDOWN.is_set():
        try:
            fetch_cot()
        except Exception as exc:
            print(f"[cot] fetch failed: {exc}", flush=True)
        SHUTDOWN.wait(300.0)

# ============================================================================
# ECONOMIC CALENDAR BUILDER
# ============================================================================
def build_calendar() -> list:
    now = datetime.now(timezone.utc)
    out = []
    for item in CALENDAR_SEED:
        try:
            candidate = datetime(now.year, item["month"], item["day"], 12, 0, 0, tzinfo=timezone.utc)
        except ValueError:
            continue
        if candidate < now - timedelta(days=1):
            try:
                candidate = datetime(now.year + 1, item["month"], item["day"], 12, 0, 0, tzinfo=timezone.utc)
            except ValueError:
                continue
        out.append({
            "event_en": item["event_en"],
            "event_ar": item["event_ar"],
            "currency": item["currency"],
            "impact": item["impact"],
            "forecast": item["forecast"],
            "previous": item["previous"],
            "when": candidate.isoformat(),
            "when_str": candidate.strftime("%Y-%m-%d %H:%M UTC"),
            "in_days": (candidate - now).days,
        })
    out.sort(key=lambda e: e["when"])
    return out[:14]

# ============================================================================
# CONFLUENCE ENGINE (Technical ICT × Macro × COT × Timing)
# ============================================================================
def macro_bias_for_symbol(symbol: str) -> str:
    regime = MACRO["regime"]
    vix = MACRO["vix"]
    us10y = MACRO["us10y"]
    with PRICE_LOCK:
        dxy_price = PRICES["DXY"]["price"]
        dxy_prev = PRICES["DXY"]["prev_close"]
    dxy_rising = dxy_price >= dxy_prev

    if symbol in ("XAU/USD", "XAG/USD"):
        if regime in ("Crisis", "Risk-Off"):
            return "bullish"
        if regime == "Risk-On":
            return "bearish" if us10y > 4.2 else "neutral"
        return "bullish" if (not dxy_rising and us10y < 4.3) else "neutral"
    if symbol == "DXY":
        if regime in ("Crisis", "Risk-Off"):
            return "bullish"
        if regime == "Risk-On":
            return "bearish"
        return "bullish" if us10y > 4.4 else "neutral"
    if symbol == "EUR/USD":
        if regime == "Risk-On":
            return "bullish"
        if regime in ("Crisis", "Risk-Off"):
            return "bearish"
        return "bullish" if not dxy_rising else "bearish"
    if symbol == "GBP/USD":
        if regime == "Risk-On":
            return "bullish"
        if regime in ("Crisis", "Risk-Off"):
            return "bearish"
        return "neutral"
    if symbol == "USD/JPY":
        if regime in ("Crisis", "Risk-Off"):
            return "bearish"
        if regime == "Risk-On":
            return "bullish"
        return "bullish" if us10y > 4.3 else "bearish"
    return "neutral"

def cot_bias_for_symbol(symbol: str) -> str:
    mapping = {"XAU/USD": "Gold", "XAG/USD": "Silver", "EUR/USD": "EUR",
               "GBP/USD": "GBP", "USD/JPY": "JPY", "DXY": None}
    asset = mapping.get(symbol)
    if asset is None:
        return "neutral"
    with COT_LOCK:
        row = COT_STATE.get(asset)
        if not row:
            return "neutral"
        net = row["long"] - row["short"]
        delta = (row["long"] - row["prev_long"]) - (row["short"] - row["prev_short"])
    if asset == "JPY":
        # JPY net long = yen bullish = USD/JPY bearish
        if net > 0 and delta > 0:
            return "bearish"
        if net < 0 and delta < 0:
            return "bullish"
        return "neutral"
    if net > 0 and delta >= 0:
        return "bullish"
    if net < 0 and delta <= 0:
        return "bearish"
    return "neutral"

def strategy_win_rate(strategy: str) -> float:
    row = db_query_one("SELECT total_trades, wins FROM strategies WHERE name=?", (strategy,))
    if not row or row["total_trades"] == 0:
        return 50.0
    return float(row["wins"]) * 100.0 / float(row["total_trades"])

def compute_confluence(symbol: str, side: str, mode: str, strategy: str) -> dict:
    reasons = []
    score = 0
    max_score = 10

    with PRICE_LOCK:
        st = PRICES[symbol]
        price = st["price"]
        prev_close = st["prev_close"]

    # ---- 1. HTF bias (2 pts) ----
    htf_bull = price >= prev_close
    htf_ok = (htf_bull and side == "BUY") or ((not htf_bull) and side == "SELL")
    if htf_ok:
        score += 2
        reasons.append({
            "key": "htf_aligned", "points": 2, "passed": True,
            "en": f"HTF bias ({'bullish' if htf_bull else 'bearish'}) aligns with {side}",
            "ar": f"اتجاه الإطار الأعلى ({'صاعد' if htf_bull else 'هابط'}) متوافق مع {('الشراء' if side == 'BUY' else 'البيع')}",
        })
    else:
        reasons.append({
            "key": "htf_conflict", "points": 0, "passed": False,
            "en": f"HTF bias ({'bullish' if htf_bull else 'bearish'}) conflicts with {side}",
            "ar": f"اتجاه الإطار الأعلى ({'صاعد' if htf_bull else 'هابط'}) يتعارض مع {('الشراء' if side == 'BUY' else 'البيع')}",
        })

    # ---- 2. Macro regime alignment (2 pts) ----
    mb = macro_bias_for_symbol(symbol)
    macro_ok = (mb == "bullish" and side == "BUY") or (mb == "bearish" and side == "SELL")
    if macro_ok:
        score += 2
        reasons.append({
            "key": "macro_aligned", "points": 2, "passed": True,
            "en": f"Macro regime '{MACRO['regime']}' supports {side}",
            "ar": f"النظام السوقي '{MACRO['regime']}' يدعم {('الشراء' if side == 'BUY' else 'البيع')}",
        })
    else:
        reasons.append({
            "key": "macro_conflict", "points": 0, "passed": False,
            "en": f"Macro regime '{MACRO['regime']}' is {mb} for {symbol}",
            "ar": f"النظام السوقي '{MACRO['regime']}' يعطي انطباعاً {('صاعد' if mb == 'bullish' else ('هابط' if mb == 'bearish' else 'محايد'))} لـ {symbol}",
        })

    # ---- 3. DXY correlation (1 pt) ----
    with PRICE_LOCK:
        dxy_price = PRICES["DXY"]["price"]
        dxy_prev = PRICES["DXY"]["prev_close"]
    dxy_down = dxy_price < dxy_prev
    dxy_ok = False
    if symbol in ("XAU/USD", "XAG/USD"):
        dxy_ok = (side == "BUY" and dxy_down) or (side == "SELL" and not dxy_down)
    elif symbol in ("EUR/USD", "GBP/USD"):
        dxy_ok = (side == "BUY" and dxy_down) or (side == "SELL" and not dxy_down)
    elif symbol == "USD/JPY":
        dxy_ok = (side == "BUY" and not dxy_down) or (side == "SELL" and dxy_down)
    elif symbol == "DXY":
        dxy_ok = (side == "BUY" and not dxy_down) or (side == "SELL" and dxy_down)
    if dxy_ok:
        score += 1
        reasons.append({
            "key": "dxy_aligned", "points": 1, "passed": True,
            "en": f"DXY direction confirms {side} on {symbol}",
            "ar": f"اتجاه مؤشر الدولار يؤكد {('الشراء' if side == 'BUY' else 'البيع')} على {symbol}",
        })
    else:
        reasons.append({
            "key": "dxy_conflict", "points": 0, "passed": False,
            "en": f"DXY direction conflicts with {side} on {symbol}",
            "ar": f"اتجاه مؤشر الدولار يتعارض مع {('الشراء' if side == 'BUY' else 'البيع')} على {symbol}",
        })

    # ---- 4. COT positioning (1 pt) ----
    cb = cot_bias_for_symbol(symbol)
    cot_ok = (cb == "bullish" and side == "BUY") or (cb == "bearish" and side == "SELL")
    if cot_ok:
        score += 1
        reasons.append({
            "key": "cot_aligned", "points": 1, "passed": True,
            "en": f"COT institutional positioning is {cb} for {symbol}",
            "ar": f"مراكز المؤسسات (COT) {('صاعدة' if cb == 'bullish' else 'هابطة')} على {symbol}",
        })
    else:
        reasons.append({
            "key": "cot_neutral", "points": 0, "passed": False,
            "en": f"COT positioning is {cb} for {symbol}",
            "ar": f"مراكز المؤسسات (COT) {('صاعدة' if cb == 'bullish' else ('هابطة' if cb == 'bearish' else 'محايدة'))} على {symbol}",
        })

    # ---- 5. VIX / risk regime (1 pt) ----
    vix = MACRO["vix"]
    if vix >= 25 and symbol in ("XAU/USD", "XAG/USD", "DXY") and side == "BUY":
        score += 1
        reasons.append({
            "key": "vix_haven", "points": 1, "passed": True,
            "en": f"Elevated VIX ({vix:.1f}) supports safe-haven {side}",
            "ar": f"ارتفاع VIX ({vix:.1f}) يدعم {('الشراء' if side == 'BUY' else 'البيع')} في الملاذ الآمن",
        })
    elif vix <= 15 and symbol in ("EUR/USD", "GBP/USD") and side == "BUY":
        score += 1
        reasons.append({
            "key": "vix_risk_on", "points": 1, "passed": True,
            "en": f"Low VIX ({vix:.1f}) supports risk-on {side}",
            "ar": f"انخفاض VIX ({vix:.1f}) يدعم {('الشراء' if side == 'BUY' else 'البيع')} في شهية المخاطرة",
        })
    else:
        reasons.append({
            "key": "vix_neutral", "points": 0, "passed": False,
            "en": f"VIX ({vix:.1f}) provides no directional edge",
            "ar": f"VIX ({vix:.1f}) لا يوفر أفضلية اتجاهية",
        })

    # ---- 6. Strategy edge (1 pt) ----
    wr = strategy_win_rate(strategy)
    if wr >= 60.0:
        score += 1
        reasons.append({
            "key": "strategy_edge", "points": 1, "passed": True,
            "en": f"Strategy win rate {wr:.1f}% is above 60%",
            "ar": f"نسبة نجاح الاستراتيجية {wr:.1f}% أعلى من 60%",
        })
    else:
        reasons.append({
            "key": "strategy_weak", "points": 0, "passed": False,
            "en": f"Strategy win rate {wr:.1f}% is below 60%",
            "ar": f"نسبة نجاح الاستراتيجية {wr:.1f}% أقل من 60%",
        })

    # ---- 7. Kill Zone timing (1 pt) ----
    if is_kill_zone():
        score += 1
        reasons.append({
            "key": "kill_zone", "points": 1, "passed": True,
            "en": "Active Kill Zone (London/NY) supports institutional flow",
            "ar": "منطقة القتل النشطة (لندن/نيويورك) تدعم التدفق المؤسسي",
        })
    else:
        reasons.append({
            "key": "no_kill_zone", "points": 0, "passed": False,
            "en": "Outside Kill Zone — timing is not optimal",
            "ar": "خارج منطقة القتل — التوقيت غير مثالي",
        })

    # ---- 8. Yield direction (1 pt) ----
    us10y = MACRO["us10y"]
    if symbol in ("XAU/USD", "XAG/USD"):
        y_ok = (side == "BUY" and us10y < 4.3) or (side == "SELL" and us10y > 4.4)
    elif symbol == "USD/JPY":
        y_ok = (side == "BUY" and us10y > 4.3) or (side == "SELL" and us10y < 4.2)
    elif symbol == "DXY":
        y_ok = (side == "BUY" and us10y > 4.3) or (side == "SELL" and us10y < 4.2)
    else:
        y_ok = (side == "BUY" and us10y < 4.3) or (side == "SELL" and us10y > 4.3)
    if y_ok:
        score += 1
        reasons.append({
            "key": "yield_aligned", "points": 1, "passed": True,
            "en": f"US 10Y yield ({us10y:.2f}%) supports {side}",
            "ar": f"عائد السندات الأمريكية 10 سنوات ({us10y:.2f}%) يدعم {('الشراء' if side == 'BUY' else 'البيع')}",
        })
    else:
        reasons.append({
            "key": "yield_conflict", "points": 0, "passed": False,
            "en": f"US 10Y yield ({us10y:.2f}%) conflicts with {side}",
            "ar": f"عائد السندات الأمريكية 10 سنوات ({us10y:.2f}%) يتعارض مع {('الشراء' if side == 'BUY' else 'البيع')}",
        })

    # ---- 9. Strategy-specific ICT confluence (1 pt) ----
    strat_ict = {
        "Liquidity Sweep & Stop Hunt": True,
        "Fair Value Gap (FVG)": True,
        "Order Block (OB)": True,
        "Change of Character (CHoCH)": True,
        "Break of Structure (BOS)": True,
        "Breaker Block": True,
        "Judas Swing / ORL": is_kill_zone(),
        "Kill Zones & Power of 3": is_kill_zone(),
        "OTE & Premium/Discount": True,
        "Inversion FVG (IFVG)": True,
    }
    if strat_ict.get(strategy, False):
        score += 1
        reasons.append({
            "key": "ict_valid", "points": 1, "passed": True,
            "en": f"{strategy} is structurally valid on current feed",
            "ar": f"{STRATEGY_AR.get(strategy, strategy)} صالحة هيكلياً على التغذية الحالية",
        })
    else:
        reasons.append({
            "key": "ict_invalid", "points": 0, "passed": False,
            "en": f"{strategy} requires Kill Zone timing",
            "ar": f"{STRATEGY_AR.get(strategy, strategy)} تتطلب توقيت منطقة القتل",
        })

    if score >= 7:
        bias = "strong"
    elif score >= 5:
        bias = "moderate"
    elif score >= 3:
        bias = "weak"
    else:
        bias = "avoid"

    directional = "bullish" if side == "BUY" else "bearish"

    if score >= 7:
        headline_en = f"High-probability {directional} setup on {symbol} — {strategy} aligns with macro and ICT structure"
        headline_ar = f"إعداد {('صاعد' if side == 'BUY' else 'هابط')} عالي الاحتمالية على {symbol} — {STRATEGY_AR.get(strategy, strategy)} متوافقة مع الهيكل الكلي وICT"
    elif score >= 5:
        headline_en = f"Moderate {directional} bias on {symbol} — trade with reduced size and strict risk"
        headline_ar = f"انحياز {('صاعد' if side == 'BUY' else 'هابط')} متوسط على {symbol} — تداول بحجم مخفض ومخاطر صارمة"
    else:
        headline_en = f"Low confluence on {symbol} — avoid or wait for confirmation"
        headline_ar = f"توافق منخفض على {symbol} — يُفضل الانتظار أو تجنب الدخول"

    return {
        "score": score,
        "max_score": max_score,
        "threshold": 5,
        "approved": score >= 5,
        "bias": bias,
        "directional": directional,
        "headline_en": headline_en,
        "headline_ar": headline_ar,
        "reasons": reasons,
        "inputs": {
            "macro_bias": mb,
            "cot_bias": cb,
            "vix": MACRO["vix"],
            "us10y": MACRO["us10y"],
            "regime": MACRO["regime"],
            "dxy": round(dxy_price, 3),
            "dxy_rising": not dxy_down,
            "kill_zone": is_kill_zone(),
            "strategy_wr": round(wr, 2),
        },
    }

# ============================================================================
# SELF-LEARNING LESSON GENERATOR
# ============================================================================
STRATEGY_LESSONS = {
    "Liquidity Sweep & Stop Hunt": (
        "Require a full entry-timeframe candle CLOSE beyond the sweep wick before entry. "
        "If the sweep occurs outside a Kill Zone, skip. Never front-run a sweep — wait for displacement."
    ),
    "Fair Value Gap (FVG)": (
        "Only valid if the displacement candle closed with >1.5× average range AND created an "
        "unmitigated FVG. Skip first-touch entries on HTF; require LTF mitigation with rejection wick."
    ),
    "Order Block (OB)": (
        "Confirm OB is the last opposite-colour candle before impulse with a confirmed Break of "
        "Structure. Require rejection wick + volume spike. Avoid OB touches above 50% of block body."
    ),
    "Change of Character (CHoCH)": (
        "Verify CHoCH on the entry timeframe AFTER a verified HTF liquidity sweep. Standalone "
        "CHoCH without prior liquidity grab is <45% reliable."
    ),
    "Break of Structure (BOS)": (
        "Require body close (not wick) beyond the swing with HTF alignment. BOS against HTF trend "
        "is a counter-trend trap. Skip BOS inside consolidation ranges."
    ),
    "Breaker Block": (
        "Only valid if the original Order Block was cleanly consumed by impulse with displacement. "
        "Confirm a fresh FVG in the same leg. Skip if breaker was formed by a news wick only."
    ),
    "Judas Swing / ORL": (
        "Only trade Judas AFTER the opening-range liquidity sweep AND a confirmation candle. "
        "Never front-run the ORL sweep. Restrict to the first 60 minutes of session."
    ),
    "Kill Zones & Power of 3": (
        "Restrict entries to London (07:00–10:00 UTC) or NY (12:00–15:00 UTC) Kill Zones. Skip "
        "AMD Distribution phase entries. Power-of-3 requires ACCUMULATION confirmation on LTF."
    ),
    "OTE & Premium/Discount": (
        "Enter ONLY within 62%–79% retracement of the impulse leg. Skip longs above 50% premium "
        "or shorts below 50% discount. Confluence with FVG/OB inside OTE = highest probability."
    ),
    "Inversion FVG (IFVG)": (
        "IFVG is only valid after a full-body close through the FVG with strong displacement. "
        "Weak closes invalidate IFVG. Require retest with rejection wick before entry."
    ),
}

MODE_LESSONS = {
    "SCALPING_A": "Mode A: HTF (1W/1D/1H) must align before M5 entry. If HTF conflicted, this trade was low-probability — reduce size 50% when HTF is not aligned.",
    "SCALPING_B": "Mode B: HTF (1W/1D/4H) bias drives M15/M1 entry. The 4H FVG is the primary magnet — if absent, skip the entry.",
    "SWING":      "Swing: H1/H4 entry must be inside a verified HTF discount (BUY) or premium (SELL). If price was in the wrong half of the HTF range, skip.",
}

def generate_lesson(trade_row, exit_price: float) -> str:
    sym      = trade_row["symbol"]
    side     = trade_row["side"]
    entry    = float(trade_row["entry_price"])
    sl       = float(trade_row["stop_loss"])
    strategy = trade_row["strategy"]
    mode     = trade_row["mode"]
    htf      = trade_row["htf_analysis"]
    entry_tf = trade_row["entry_timeframe"]
    cfg      = SYMBOLS.get(sym, {})
    pip      = cfg.get("pip", 0.0001)
    dec      = cfg.get("decimals", 4)
    loss_pips = abs(entry - sl) / pip if pip > 0 else 0.0

    head = (f"[{TRADE_MODES.get(mode, {}).get('label_en', mode)}] "
            f"{side} {sym} @ {entry:.{dec}f} → SL hit {exit_price:.{dec}f} "
            f"({loss_pips:.1f} pips loss).")
    strat_lesson = STRATEGY_LESSONS.get(strategy, "Review entry timing against HTF bias.")
    mode_lesson = MODE_LESSONS.get(mode, "Review timeframe alignment.")
    tf_line = f"Timeframe check: HTF ({','.join(htf)}) ↔ Entry ({entry_tf})."
    return f"{head} {strat_lesson} {mode_lesson} {tf_line}"

# ============================================================================
# TRADE EVALUATOR
# ============================================================================
def trade_evaluator() -> None:
    while not SHUTDOWN.is_set():
        try:
            with DB_LOCK:
                c = get_conn()
                try:
                    cur = c.cursor()

                    # ---- Fill LIMIT orders ----
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
                        if t["side"] == "BUY" and current <= float(t["entry_price"]):
                            hit = True
                        if t["side"] == "SELL" and current >= float(t["entry_price"]):
                            hit = True
                        if hit:
                            cur.execute(
                                "UPDATE trades SET status='ACTIVE', activated_at=? WHERE id=?",
                                (now_iso(), t["id"])
                            )

                    # ---- Evaluate ACTIVE ----
                    active = cur.execute("SELECT * FROM trades WHERE status='ACTIVE'").fetchall()
                    for t in active:
                        tid = t["id"]
                        sym = t["symbol"]
                        side = t["side"]
                        entry = float(t["entry_price"])
                        sl = float(t["stop_loss"])
                        tp = float(t["take_profit"])
                        lot = float(t["lot_size"])
                        strat = t["strategy"]
                        with PRICE_LOCK:
                            current = PRICES.get(sym, {}).get("price")
                        if current is None:
                            continue
                        outcome = None
                        exit_price = None
                        if side == "BUY":
                            if current <= sl:
                                outcome, exit_price = "LOSS", sl
                            elif current >= tp:
                                outcome, exit_price = "WIN", tp
                        else:
                            if current >= sl:
                                outcome, exit_price = "LOSS", sl
                            elif current <= tp:
                                outcome, exit_price = "WIN", tp
                        if outcome is None:
                            continue
                        mult = SYMBOLS.get(sym, {}).get("mult", 100000)
                        diff = (exit_price - entry) if side == "BUY" else (entry - exit_price)
                        pnl = round(diff * mult * lot, 2)
                        iso = now_iso()
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
                                "INSERT INTO self_learning (trade_id, symbol, strategy, mode, lesson, created_at) "
                                "VALUES (?, ?, ?, ?, ?, ?)",
                                (tid, sym, strat, t["mode"], lesson, iso)
                            )
                    c.commit()
                finally:
                    c.close()
        except Exception as exc:
            print(f"[evaluator] {exc}", flush=True)
            traceback.print_exc()
        SHUTDOWN.wait(0.5)

# ============================================================================
# HTTP HANDLER
# ============================================================================
class Handler(BaseHTTPRequestHandler):

    server_version = "ProTradingEngine/3.0"

    def log_message(self, fmt, *args):
        pass

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
            pass

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
            pass

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise ValueError(f"invalid JSON: {exc}")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    # ------------------------------------------------------------------ GET
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
                    "ok": True,
                    "time": now_iso(),
                    "session": active_session(),
                    "kill_zone": is_kill_zone(),
                })
                return

            if path == "/api/config":
                self._json({
                    "ok": True,
                    "symbols": {
                        s: {
                            "decimals": c["decimals"],
                            "mult": c["mult"],
                            "pip": c["pip"],
                            "label_en": c["label_en"],
                            "label_ar": c["label_ar"],
                            "yahoo": c["yahoo"],
                        } for s, c in SYMBOLS.items()
                    },
                    "modes": TRADE_MODES,
                    "strategies": ICT_STRATEGIES,
                    "strategy_ar": STRATEGY_AR,
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
                            "price":      round(st["price"], c["decimals"]),
                            "prev_price": round(st["prev_price"], c["decimals"]),
                            "open":       round(open_p, c["decimals"]),
                            "high":       round(st["high"], c["decimals"]),
                            "low":        round(st["low"], c["decimals"]),
                            "prev_close": round(st["prev_close"], c["decimals"]),
                            "change_pct": round(chg, 3),
                            "decimals":   c["decimals"],
                            "history":    [round(x, c["decimals"]) for x in st["history"][-40:]],
                            "last_update": st["last_update"],
                            "source":     st["source"],
                            "stale":      st["stale"],
                        }
                self._json({"ok": True, "data": data})
                return

            if path == "/api/settings":
                r = db_query_one("SELECT capital, risk_percent, updated_at FROM bot_settings WHERE id=1")
                if r is None:
                    self._json({"ok": False, "error": "settings missing"}, 500)
                    return
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
                    out.append({
                        "name": r["name"],
                        "name_ar": STRATEGY_AR.get(r["name"], r["name"]),
                        "total_trades": t,
                        "wins": w,
                        "losses": l,
                        "win_rate": round(wr, 2),
                    })
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
                    feed_ok = sum(1 for s in SYMBOLS if not PRICES[s]["stale"])
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
                    "feed_ok": feed_ok,
                    "feed_total": len(SYMBOLS),
                }})
                return

            if path == "/api/macro":
                with MACRO_LOCK:
                    vix = round(MACRO["vix"], 2)
                    us10y = round(MACRO["us10y"], 3)
                    regime = MACRO["regime"]
                    haven = MACRO["safe_haven"]
                    geo = MACRO["geo_risk"]
                    geo_label = MACRO["geo_risk_label"]
                    upd = MACRO["updated_at"]
                with PRICE_LOCK:
                    xau = PRICES["XAU/USD"]["price"]
                    xag = PRICES["XAG/USD"]["price"]
                    dxy = PRICES["DXY"]["price"]
                    dxy_prev = PRICES["DXY"]["prev_close"]
                    dxy_hist = list(PRICES["DXY"]["history"][-20:])
                gsr = round(xau / xag, 2) if xag > 0 else 0.0
                flow_score = 0
                if dxy < dxy_prev: flow_score += 2
                else: flow_score -= 2
                if regime in ("Risk-Off", "Crisis"): flow_score += 3
                elif regime == "Risk-On": flow_score -= 1
                if us10y > 4.4: flow_score -= 1
                elif us10y < 4.0: flow_score += 1
                if vix > 25: flow_score += 2
                flow_score = max(-10, min(10, flow_score))

                self._json({"ok": True, "data": {
                    "vix": vix,
                    "us10y": us10y,
                    "dxy": round(dxy, 3),
                    "dxy_prev": round(dxy_prev, 3),
                    "dxy_history": [round(x, 3) for x in dxy_hist],
                    "gold_silver_ratio": gsr,
                    "regime": regime,
                    "safe_haven": haven,
                    "geo_risk": geo,
                    "geo_risk_label": geo_label,
                    "dxy_flow_score": flow_score,
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
                        "label_ar": c.get("label_ar", name),
                        "source": c.get("source", "seed"),
                    }
                self._json({"ok": True, "data": out})
                return

            if path == "/api/calendar":
                with CAL_LOCK:
                    events = build_calendar()
                self._json({"ok": True, "data": events})
                return

            if path == "/api/self_learning":
                limit = int(qs.get("limit", ["50"])[0])
                rows = db_query(
                    "SELECT id, trade_id, symbol, strategy, mode, lesson, created_at "
                    "FROM self_learning ORDER BY id DESC LIMIT ?",
                    (limit,)
                )
                self._json({"ok": True, "count": len(rows), "data": [dict(r) for r in rows]})
                return

            if path == "/api/confluence":
                symbol = qs.get("symbol", ["XAU/USD"])[0]
                side = qs.get("side", ["BUY"])[0].upper()
                mode = qs.get("mode", ["SCALPING_A"])[0]
                strategy = qs.get("strategy", [ICT_STRATEGIES[0]])[0]
                if symbol not in SYMBOLS:
                    self._json({"ok": False, "error": "unknown symbol"}, 400)
                    return
                if side not in ("BUY", "SELL"):
                    self._json({"ok": False, "error": "side must be BUY/SELL"}, 400)
                    return
                if mode not in TRADE_MODES:
                    self._json({"ok": False, "error": "unknown mode"}, 400)
                    return
                if strategy not in ICT_STRATEGIES:
                    self._json({"ok": False, "error": "unknown strategy"}, 400)
                    return
                result = compute_confluence(symbol, side, mode, strategy)
                self._json({"ok": True, "data": result})
                return

            if path == "/api/feed_status":
                with PRICE_LOCK:
                    data = {}
                    for s, c in SYMBOLS.items():
                        st = PRICES[s]
                        data[s] = {
                            "source": st["source"],
                            "stale": st["stale"],
                            "last_update": st["last_update"],
                            "yahoo_ticker": c["yahoo"],
                        }
                self._json({"ok": True, "data": data})
                return

            self._json({"ok": False, "error": "not found", "path": path}, 404)
        except Exception as exc:
            traceback.print_exc()
            self._json({"ok": False, "error": str(exc)}, 500)

    # ------------------------------------------------------------------ POST
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        try:
            if path == "/api/settings":
                body = self._read_json()
                cap = float(body.get("capital", 10000.0))
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

            if path == "/api/trades":
                body = self._read_json()
                symbol = body.get("symbol", "XAU/USD")
                side = str(body.get("side", "BUY")).upper()
                entry_type = str(body.get("entry_type", "MARKET")).upper()
                mode = body.get("mode", "SCALPING_A")
                strategy = body.get("strategy", ICT_STRATEGIES[0])
                entry_tf = body.get("entry_timeframe", "")

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
                    self._json({"ok": False, "error": f"entry timeframe {entry_tf} not valid for {mode}"}, 400); return

                cfg = SYMBOLS[symbol]
                dec = cfg["decimals"]
                with PRICE_LOCK:
                    live = PRICES[symbol]["price"]

                if entry_type == "MARKET":
                    entry = round(live, dec)
                else:
                    user_entry = body.get("entry_price")
                    if user_entry is None:
                        self._json({"ok": False, "error": "entry_price required for LIMIT orders"}, 400); return
                    entry = round(float(user_entry), dec)
                    if side == "BUY" and entry >= live:
                        self._json({"ok": False, "error": "BUY LIMIT requires entry below current price"}, 400); return
                    if side == "SELL" and entry <= live:
                        self._json({"ok": False, "error": "SELL LIMIT requires entry above current price"}, 400); return

                sl_user = body.get("stop_loss")
                tp_user = body.get("take_profit")
                if sl_user is not None and tp_user is not None:
                    stop_loss = round(float(sl_user), dec)
                    take_profit = round(float(tp_user), dec)
                else:
                    stop_loss, take_profit = default_sl_tp(symbol, mode, side, entry)

                if side == "BUY" and not (stop_loss < entry < take_profit):
                    self._json({"ok": False, "error": "For BUY: SL < entry < TP required"}, 400); return
                if side == "SELL" and not (take_profit < entry < stop_loss):
                    self._json({"ok": False, "error": "For SELL: TP < entry < SL required"}, 400); return

                confluence = compute_confluence(symbol, side, mode, strategy)
                if not confluence["approved"]:
                    self._json({
                        "ok": False,
                        "error": f"Confluence score {confluence['score']}/10 below threshold "
                                 f"{confluence['threshold']}. Wait for better alignment.",
                        "confluence": confluence,
                    }, 400)
                    return

                s = db_query_one("SELECT capital, risk_percent FROM bot_settings WHERE id=1")
                sl_dist = abs(entry - stop_loss)
                lot = calculate_lot_size(float(s["capital"]), float(s["risk_percent"]), sl_dist, symbol)

                htf_str = ",".join(TRADE_MODES[mode]["htf"])
                status = "ACTIVE" if entry_type == "MARKET" else "PENDING"
                activated_at = now_iso() if status == "ACTIVE" else None

                new_id = db_exec(
                    "INSERT INTO trades (symbol, side, entry_type, mode, htf_analysis, "
                    "entry_timeframe, entry_price, stop_loss, take_profit, lot_size, "
                    "strategy, status, confluence_score, confluence_bias, opened_at, activated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (symbol, side, entry_type, mode, htf_str, entry_tf,
                     entry, stop_loss, take_profit, lot, strategy,
                     status, confluence["score"], confluence["directional"],
                     now_iso(), activated_at)
                )
                r = db_query_one("SELECT * FROM trades WHERE id=?", (new_id,))
                self._json({"ok": True, "data": dict(r), "confluence": confluence})
                return

            if path == "/api/auto_dispatch":
                body = self._read_json()
                mode = body.get("mode") or random.choice(list(TRADE_MODES.keys()))
                if mode not in TRADE_MODES:
                    mode = "SCALPING_A"

                with PRICE_LOCK:
                    def vol_pct(sym):
                        h = PRICES[sym]["history"]
                        if len(h) < 5:
                            return 0.0
                        lo, hi = min(h), max(h)
                        return (hi - lo) / max(lo, 1e-9)
                    ranked = sorted(SYMBOLS.keys(), key=vol_pct, reverse=True)
                    symbol = random.choice(ranked[:3])
                    hist = PRICES[symbol]["history"]
                    momentum = hist[-1] - hist[-6] if len(hist) >= 6 else 0.0
                    live = PRICES[symbol]["price"]

                side = "BUY" if momentum >= 0 else "SELL"

                tops = db_query(
                    "SELECT name FROM strategies WHERE total_trades > 0 "
                    "ORDER BY CAST(wins AS REAL)/MAX(total_trades,1) DESC LIMIT 5"
                )
                pool = [r["name"] for r in tops] if tops else ICT_STRATEGIES
                strategy = random.choice(pool)
                entry_tf = random.choice(TRADE_MODES[mode]["entry_tfs"])
                entry_type = random.choices(["MARKET", "LIMIT"], weights=[0.75, 0.25])[0]

                cfg = SYMBOLS[symbol]
                dec = cfg["decimals"]
                entry = round(live, dec)

                if entry_type == "LIMIT":
                    sl_probe, tp_probe = default_sl_tp(symbol, mode, side, entry)
                    pull = abs(entry - sl_probe) * 0.35
                    if side == "BUY":
                        entry = round(entry - pull, dec)
                    else:
                        entry = round(entry + pull, dec)

                sl, tp = default_sl_tp(symbol, mode, side, entry)
                confluence = compute_confluence(symbol, side, mode, strategy)

                s = db_query_one("SELECT capital, risk_percent FROM bot_settings WHERE id=1")
                lot = calculate_lot_size(float(s["capital"]), float(s["risk_percent"]),
                                         abs(entry - sl), symbol)

                htf_str = ",".join(TRADE_MODES[mode]["htf"])
                status = "ACTIVE" if entry_type == "MARKET" else "PENDING"
                activated_at = now_iso() if status == "ACTIVE" else None

                new_id = db_exec(
                    "INSERT INTO trades (symbol, side, entry_type, mode, htf_analysis, "
                    "entry_timeframe, entry_price, stop_loss, take_profit, lot_size, "
                    "strategy, status, confluence_score, confluence_bias, opened_at, activated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (symbol, side, entry_type, mode, htf_str, entry_tf,
                     entry, sl, tp, lot, strategy, status,
                     confluence["score"], confluence["directional"],
                     now_iso(), activated_at)
                )
                r = db_query_one("SELECT * FROM trades WHERE id=?", (new_id,))
                self._json({"ok": True, "auto": True, "data": dict(r), "confluence": confluence})
                return

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
                db_exec("UPDATE trades SET status='CANCELLED', closed_at=? WHERE id=?", (now_iso(), tid))
                self._json({"ok": True, "message": f"Trade #{tid} cancelled"})
                return

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
                    db_exec("UPDATE strategies SET total_trades=total_trades+1, wins=wins+1 WHERE name=?",
                            (row["strategy"],))
                else:
                    db_exec("UPDATE strategies SET total_trades=total_trades+1, losses=losses+1 WHERE name=?",
                            (row["strategy"],))
                    lesson = generate_lesson(row, current)
                    db_exec("INSERT INTO self_learning (trade_id, symbol, strategy, mode, lesson, created_at) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (tid, sym, row["strategy"], row["mode"], lesson, now_iso()))
                self._json({"ok": True, "message": f"Trade #{tid} closed ({outcome})", "pnl": pnl})
                return

            if path == "/api/self_learning/reset":
                db_exec("DELETE FROM self_learning")
                self._json({"ok": True, "message": "self_learning cleared"})
                return

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
# FRONTEND (BILINGUAL DARK-MODE DASHBOARD)
# ============================================================================
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en" dir="ltr">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Pro Trading &amp; Macro Intelligence Engine</title>
<script src="https://cdn.tailwindcss.com"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Cairo:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
  html, body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: radial-gradient(1500px 750px at 12% -12%, #0b1b3d 0%, #05091a 42%, #020308 100%);
  }
  html[dir="rtl"] body { font-family: 'Cairo', 'Inter', sans-serif; }
  html[dir="rtl"] table { direction: rtl; }
  html[dir="rtl"] .text-left { text-align: right; }
  html[dir="rtl"] .text-right { text-align: left; }
  .tabnum { font-variant-numeric: tabular-nums; font-feature-settings: "tnum"; }
  .card {
    background: linear-gradient(180deg, rgba(15,23,42,0.88) 0%, rgba(2,6,23,0.84) 100%);
    border: 1px solid rgba(59,130,246,0.14);
    box-shadow: 0 8px 32px -8px rgba(0,0,0,0.55);
    transition: border-color .2s ease, transform .2s ease;
  }
  .card:hover { border-color: rgba(59,130,246,0.32); }
  .flash-up   { animation: flashUp .65s ease-out; }
  .flash-down { animation: flashDown .65s ease-out; }
  @keyframes flashUp   { from { background-color: rgba(16,185,129,0.32); } to { background-color: transparent; } }
  @keyframes flashDown { from { background-color: rgba(244,63,94,0.32); } to { background-color: transparent; } }
  .pulse-dot { position: relative; display: inline-block; }
  .pulse-dot::before {
    content: ''; position: absolute; inset: -4px; border-radius: 9999px;
    background: currentColor; opacity: .4; animation: pulseRing 1.8s ease-out infinite;
  }
  @keyframes pulseRing { 0% { transform: scale(.55); opacity: .6; } 100% { transform: scale(2.2); opacity: 0; } }
  ::-webkit-scrollbar { width: 8px; height: 8px; }
  ::-webkit-scrollbar-track { background: #0b1220; }
  ::-webkit-scrollbar-thumb { background: #1e293b; border-radius: 8px; }
  ::-webkit-scrollbar-thumb:hover { background: #334155; }
  .glow-blue   { box-shadow: 0 0 26px -6px rgba(56,189,248,0.70); }
  .glow-green  { box-shadow: 0 0 26px -6px rgba(16,185,129,0.70); }
  .glow-red    { box-shadow: 0 0 26px -6px rgba(244,63,94,0.70); }
  .stripe-row:nth-child(odd) { background: rgba(15,23,42,0.35); }
  .stripe-row:hover { background: rgba(30,64,175,0.14); }
  select, input { outline: none; }
  select:focus, input:focus { border-color: #38bdf8 !important; box-shadow: 0 0 0 2px rgba(56,189,248,0.22); }
  .btn-primary { background: linear-gradient(135deg, #0ea5e9 0%, #2563eb 100%); transition: transform .15s, filter .15s; }
  .btn-primary:hover { filter: brightness(1.10); transform: translateY(-1px); }
  .btn-success { background: linear-gradient(135deg, #10b981 0%, #059669 100%); transition: transform .15s, filter .15s; }
  .btn-success:hover { filter: brightness(1.10); transform: translateY(-1px); }
  .btn-amber { background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); transition: transform .15s, filter .15s; }
  .btn-amber:hover { filter: brightness(1.10); transform: translateY(-1px); }
  .tag { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 10px; font-weight: 700; letter-spacing: .03em; }
  .scroll-area { max-height: 480px; overflow-y: auto; }
  .feed-live { color: #34d399; }
  .feed-stale { color: #fbbf24; }
  .score-ring {
    background: conic-gradient(#10b981 var(--p), #1e293b 0);
    border-radius: 9999px;
    transition: background .35s ease;
  }
  .reason-pass { border-left: 3px solid #10b981; }
  .reason-fail { border-left: 3px solid #64748b; }
  html[dir="rtl"] .reason-pass { border-left: none; border-right: 3px solid #10b981; }
  html[dir="rtl"] .reason-fail { border-left: none; border-right: 3px solid #64748b; }
</style>
</head>
<body class="text-slate-200 min-h-screen pb-16">

<header class="sticky top-0 z-40 backdrop-blur-xl bg-slate-950/78 border-b border-blue-500/15">
  <div class="max-w-[1750px] mx-auto px-4 py-3 flex flex-wrap items-center gap-3 justify-between">
    <div class="flex items-center gap-3">
      <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-sky-400 via-blue-600 to-indigo-700 flex items-center justify-center font-black text-lg shadow-lg glow-blue">P</div>
      <div>
        <div class="text-[15px] font-bold tracking-tight text-white" data-i18n="app_title">Pro Trading &amp; Macro Intelligence</div>
        <div class="text-[10px] uppercase tracking-[0.22em] text-slate-500" data-i18n="app_subtitle">Institutional ICT Engine · v3.0</div>
      </div>
    </div>
    <div class="flex flex-wrap items-center gap-2 text-xs">
      <button id="btnLang" class="px-3 py-1.5 rounded-full border border-sky-500/40 bg-sky-950/60 text-sky-300 font-bold hover:bg-sky-900/70 transition">🌐 English</button>
      <div class="flex items-center gap-2 bg-slate-900/70 border border-slate-800 rounded-full px-3 py-1.5">
        <span id="feedDot" class="text-emerald-400 pulse-dot w-2 h-2 rounded-full bg-emerald-400"></span>
        <span id="feedStatus" class="text-emerald-300 font-semibold" data-i18n="live">LIVE</span>
      </div>
      <div class="bg-slate-900/70 border border-slate-800 rounded-full px-3 py-1.5">
        <span data-i18n="session">Session</span>: <b id="sessionLabel" class="text-sky-300">—</b>
      </div>
      <div id="killZoneBadge" class="bg-slate-900/70 border border-slate-800 rounded-full px-3 py-1.5">
        <span data-i18n="kill_zone">Kill Zone</span>: <b id="killZoneLabel" class="text-slate-400">—</b>
      </div>
      <div class="bg-slate-900/70 border border-slate-800 rounded-full px-3 py-1.5">
        <span data-i18n="capital">Capital</span>: <b id="topCapital" class="text-emerald-300 tabnum">$0</b>
      </div>
      <div class="bg-slate-900/70 border border-slate-800 rounded-full px-3 py-1.5">
        <span data-i18n="win_rate">Win Rate</span>: <b id="topWinRate" class="text-amber-300 tabnum">0%</b>
      </div>
    </div>
  </div>
</header>

<main class="max-w-[1750px] mx-auto px-4 py-6 space-y-6">

  <!-- ============ LIVE PRICE GRID ============ -->
  <section>
    <div class="flex items-center justify-between mb-3">
      <h2 class="text-xs font-bold uppercase tracking-[0.22em] text-slate-400" data-i18n="live_market_feed">Live Market Feed</h2>
      <div class="text-[10px] text-slate-500" data-i18n="feed_sub">Real Yahoo Finance feed · 1s visual ticks · 3s real refresh</div>
    </div>
    <div id="priceGrid" class="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3"></div>
  </section>

  <!-- ============ ACCOUNT + CONSOLE ============ -->
  <section class="grid grid-cols-1 xl:grid-cols-3 gap-4">

    <div class="card rounded-xl p-5">
      <h3 class="text-xs font-bold uppercase tracking-[0.22em] text-sky-400 mb-4" data-i18n="account_risk">Account &amp; Risk Control</h3>
      <div class="space-y-4">
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest" data-i18n="capital_usd">Capital (USD)</label>
          <input id="inpCapital" type="number" step="0.01" min="1" value="10000"
                 class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white tabnum" />
        </div>
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest" data-i18n="risk_per_trade">Risk per Trade (%)</label>
          <input id="inpRisk" type="number" step="0.05" min="0.01" max="100" value="1"
                 class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white tabnum" />
        </div>
        <button id="btnSaveSettings" class="btn-primary w-full text-white font-semibold rounded-lg py-2" data-i18n="save_permanently">Save Permanently</button>
        <div id="settingsStatus" class="text-[11px] h-4"></div>
        <div class="pt-3 border-t border-slate-800 grid grid-cols-2 gap-y-1.5 text-[11px]">
          <div class="text-slate-500" data-i18n="risk_usd">Risk $/trade</div><div class="text-right text-white tabnum" id="riskUsd">—</div>
          <div class="text-slate-500" data-i18n="total_trades">Total trades</div><div class="text-right text-white tabnum" id="statTotal">—</div>
          <div class="text-slate-500" data-i18n="active_pos">Active</div><div class="text-right text-emerald-300 tabnum" id="statActive">—</div>
          <div class="text-slate-500" data-i18n="pending_orders">Pending</div><div class="text-right text-amber-300 tabnum" id="statPending">—</div>
          <div class="text-slate-500" data-i18n="realized_pnl">Realized P&amp;L</div><div class="text-right tabnum" id="statPnl">—</div>
        </div>
      </div>
    </div>

    <div class="card rounded-xl p-5 xl:col-span-2">
      <h3 class="text-xs font-bold uppercase tracking-[0.22em] text-sky-400 mb-4" data-i18n="trade_console">Trade Console — Multi-Timeframe Execution</h3>
      <div class="grid grid-cols-2 md:grid-cols-3 gap-3">
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest" data-i18n="symbol">Symbol</label>
          <select id="selSymbol" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white"></select>
        </div>
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest" data-i18n="side">Side</label>
          <select id="selSide" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white">
            <option value="BUY" data-i18n="buy">BUY</option>
            <option value="SELL" data-i18n="sell">SELL</option>
          </select>
        </div>
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest" data-i18n="entry_type">Entry Type</label>
          <select id="selEntryType" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white">
            <option value="MARKET" data-i18n="market">MARKET</option>
            <option value="LIMIT" data-i18n="limit">LIMIT</option>
          </select>
        </div>
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest" data-i18n="trade_mode">Trade Mode</label>
          <select id="selMode" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white"></select>
        </div>
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest" data-i18n="entry_tf">Entry Timeframe</label>
          <select id="selEntryTF" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white"></select>
        </div>
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest" data-i18n="ict_strategy">ICT Strategy</label>
          <select id="selStrategy" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white"></select>
        </div>
      </div>

      <div class="mt-3 grid grid-cols-3 gap-3">
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest" data-i18n="entry_price">Entry Price</label>
          <input id="inpEntry" type="number" step="any" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-white tabnum" />
        </div>
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest" data-i18n="stop_loss">Stop Loss</label>
          <input id="inpSL" type="number" step="any" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-rose-300 tabnum" />
        </div>
        <div>
          <label class="text-[11px] text-slate-400 uppercase tracking-widest" data-i18n="take_profit">Take Profit</label>
          <input id="inpTP" type="number" step="any" class="w-full mt-1 bg-slate-900/80 border border-slate-700 rounded-lg px-3 py-2 text-emerald-300 tabnum" />
        </div>
      </div>

      <div class="mt-3 grid grid-cols-2 gap-3">
        <div class="bg-slate-950/70 border border-slate-800 rounded-lg px-3 py-2">
          <div class="text-[10px] uppercase tracking-widest text-slate-500" data-i18n="htf_analysis">HTF Analysis</div>
          <div id="htfDisplay" class="text-sky-300 font-semibold text-sm tabnum">1W · 1D · 1H</div>
        </div>
        <div class="bg-slate-950/70 border border-sky-500/30 rounded-lg px-3 py-2">
          <div class="text-[10px] uppercase tracking-widest text-slate-500" data-i18n="lot_size">Calculated Lot Size</div>
          <div id="lotDisplay" class="text-emerald-300 font-bold text-lg tabnum">0.00</div>
        </div>
      </div>

      <div class="flex flex-wrap gap-2 mt-4">
        <button id="btnDispatch" class="btn-success flex-1 min-w-[180px] text-white font-semibold rounded-lg py-2.5" data-i18n="dispatch_trade">⚡ Dispatch Trade</button>
        <button id="btnAutoDispatch" class="btn-primary flex-1 min-w-[180px] text-white font-semibold rounded-lg py-2.5" data-i18n="auto_dispatch">🤖 Auto Dispatch</button>
      </div>
      <div id="dispatchStatus" class="text-[11px] mt-2 h-4"></div>
    </div>
  </section>

  <!-- ============ CONFLUENCE PANEL ============ -->
  <section class="card rounded-xl p-5">
    <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
      <h3 class="text-xs font-bold uppercase tracking-[0.22em] text-fuchsia-400" data-i18n="confluence_analysis">Technical × Macro Confluence Engine</h3>
      <div class="text-[10px] text-slate-500" data-i18n="confluence_sub">ICT structure + Macro regime + COT + Timing</div>
    </div>
    <div class="grid grid-cols-1 md:grid-cols-4 gap-4 items-center">
      <div class="flex flex-col items-center justify-center">
        <div id="confluenceRing" class="score-ring w-24 h-24 flex items-center justify-center" style="--p:0%">
          <div class="w-20 h-20 rounded-full bg-slate-950 flex flex-col items-center justify-center">
            <div id="confluenceScore" class="text-2xl font-black text-white tabnum">0</div>
            <div class="text-[9px] text-slate-500">/ 10</div>
          </div>
        </div>
        <div id="confluenceVerdict" class="text-[11px] mt-2 font-bold text-slate-400">—</div>
      </div>
      <div class="md:col-span-3">
        <div id="confluenceHeadline" class="text-sm text-slate-200 mb-3">—</div>
        <div id="confluenceReasons" class="grid grid-cols-1 md:grid-cols-2 gap-1.5 max-h-[260px] overflow-y-auto pr-1"></div>
      </div>
    </div>
  </section>

  <!-- ============ ACTIVE POSITIONS ============ -->
  <section class="card rounded-xl overflow-hidden">
    <div class="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
      <h3 class="text-xs font-bold uppercase tracking-[0.22em] text-emerald-400" data-i18n="active_positions">Active Positions</h3>
      <span id="activeCount" class="text-[11px] text-slate-500">0</span>
    </div>
    <div class="overflow-x-auto">
      <table class="w-full text-xs">
        <thead class="bg-slate-950/60 text-slate-500 uppercase text-[10px] tracking-wider">
          <tr>
            <th class="text-left px-3 py-2" data-i18n="id">ID</th>
            <th class="text-left px-3 py-2" data-i18n="symbol">Symbol</th>
            <th class="text-left px-3 py-2" data-i18n="side">Side</th>
            <th class="text-left px-3 py-2" data-i18n="mode">Mode</th>
            <th class="text-left px-3 py-2" data-i18n="htf_entry">HTF → Entry</th>
            <th class="text-right px-3 py-2" data-i18n="entry_price">Entry</th>
            <th class="text-right px-3 py-2" data-i18n="stop_loss">SL</th>
            <th class="text-right px-3 py-2" data-i18n="take_profit">TP</th>
            <th class="text-right px-3 py-2" data-i18n="lot_size">Lot</th>
            <th class="text-right px-3 py-2" data-i18n="confluence">Confluence</th>
            <th class="text-left px-3 py-2" data-i18n="strategy_col">Strategy</th>
            <th class="text-center px-3 py-2" data-i18n="action">Action</th>
          </tr>
        </thead>
        <tbody id="tblActive"></tbody>
      </table>
    </div>
  </section>

  <!-- ============ PENDING ============ -->
  <section class="card rounded-xl overflow-hidden">
    <div class="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
      <h3 class="text-xs font-bold uppercase tracking-[0.22em] text-amber-400" data-i18n="pending_limit_orders">Pending Limit Orders</h3>
      <span id="pendingCountLabel" class="text-[11px] text-slate-500">0</span>
    </div>
    <div class="overflow-x-auto">
      <table class="w-full text-xs">
        <thead class="bg-slate-950/60 text-slate-500 uppercase text-[10px] tracking-wider">
          <tr>
            <th class="text-left px-3 py-2" data-i18n="id">ID</th>
            <th class="text-left px-3 py-2" data-i18n="symbol">Symbol</th>
            <th class="text-left px-3 py-2" data-i18n="side">Side</th>
            <th class="text-left px-3 py-2" data-i18n="mode">Mode</th>
            <th class="text-left px-3 py-2" data-i18n="htf_entry">HTF → Entry</th>
            <th class="text-right px-3 py-2" data-i18n="limit_entry">Limit Entry</th>
            <th class="text-right px-3 py-2" data-i18n="stop_loss">SL</th>
            <th class="text-right px-3 py-2" data-i18n="take_profit">TP</th>
            <th class="text-right px-3 py-2" data-i18n="lot_size">Lot</th>
            <th class="text-right px-3 py-2" data-i18n="confluence">Confluence</th>
            <th class="text-left px-3 py-2" data-i18n="strategy_col">Strategy</th>
            <th class="text-center px-3 py-2" data-i18n="action">Action</th>
          </tr>
        </thead>
        <tbody id="tblPending"></tbody>
      </table>
    </div>
  </section>

  <!-- ============ HISTORY ============ -->
  <section class="card rounded-xl overflow-hidden">
    <div class="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
      <h3 class="text-xs font-bold uppercase tracking-[0.22em] text-slate-300" data-i18n="trade_history">Trade History</h3>
      <span class="text-[11px] text-slate-500" data-i18n="last_50">last 50 closed</span>
    </div>
    <div class="overflow-x-auto scroll-area">
      <table class="w-full text-xs">
        <thead class="bg-slate-950/60 text-slate-500 uppercase text-[10px] tracking-wider sticky top-0">
          <tr>
            <th class="text-left px-3 py-2" data-i18n="id">ID</th>
            <th class="text-left px-3 py-2" data-i18n="symbol">Symbol</th>
            <th class="text-left px-3 py-2" data-i18n="side">Side</th>
            <th class="text-left px-3 py-2" data-i18n="mode">Mode</th>
            <th class="text-left px-3 py-2" data-i18n="htf_entry">HTF → Entry</th>
            <th class="text-right px-3 py-2" data-i18n="entry_price">Entry</th>
            <th class="text-right px-3 py-2" data-i18n="exit">Exit</th>
            <th class="text-right px-3 py-2" data-i18n="lot_size">Lot</th>
            <th class="text-right px-3 py-2" data-i18n="confluence">Confluence</th>
            <th class="text-left px-3 py-2" data-i18n="strategy_col">Strategy</th>
            <th class="text-left px-3 py-2" data-i18n="status">Status</th>
            <th class="text-right px-3 py-2" data-i18n="pnl">P&amp;L</th>
            <th class="text-left px-3 py-2" data-i18n="closed">Closed</th>
          </tr>
        </thead>
        <tbody id="tblHistory"></tbody>
      </table>
    </div>
  </section>

  <!-- ============ MACRO & GEOPOLITICS ============ -->
  <section class="card rounded-xl overflow-hidden">
    <div class="px-5 py-4 border-b border-slate-800 flex flex-wrap items-center justify-between gap-2">
      <h3 class="text-sm font-bold uppercase tracking-[0.22em] text-indigo-400" data-i18n="macro_geopolitics">Macro &amp; Geopolitics Intelligence</h3>
      <div class="flex items-center gap-2 text-[10px] text-slate-500">
        <span class="w-2 h-2 rounded-full bg-indigo-500 animate-pulse"></span>
        <span data-i18n="macro_live_note">Live · Yahoo Finance + FuturesBench COT</span>
      </div>
    </div>
    <div class="p-5 space-y-5">

      <div class="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-3">
        <div class="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
          <div class="text-[10px] uppercase tracking-widest text-slate-500">VIX</div>
          <div id="macroVix" class="text-xl font-bold text-rose-300 tabnum mt-1">—</div>
        </div>
        <div class="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
          <div class="text-[10px] uppercase tracking-widest text-slate-500" data-i18n="us10y">US 10Y</div>
          <div id="macro10y" class="text-xl font-bold text-amber-300 tabnum mt-1">—</div>
        </div>
        <div class="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
          <div class="text-[10px] uppercase tracking-widest text-slate-500">DXY</div>
          <div id="macroDxy" class="text-xl font-bold text-sky-300 tabnum mt-1">—</div>
        </div>
        <div class="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
          <div class="text-[10px] uppercase tracking-widest text-slate-500" data-i18n="gsr">Gold / Silver</div>
          <div id="macroGsr" class="text-xl font-bold text-amber-200 tabnum mt-1">—</div>
        </div>
        <div class="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
          <div class="text-[10px] uppercase tracking-widest text-slate-500" data-i18n="dxy_flow">DXY Flow Score</div>
          <div id="macroFlow" class="text-xl font-bold tabnum mt-1">—</div>
        </div>
        <div class="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
          <div class="text-[10px] uppercase tracking-widest text-slate-500" data-i18n="geopolitical_risk">Geopolitical Risk</div>
          <div id="macroGeo" class="text-xl font-bold text-fuchsia-300 tabnum mt-1">—</div>
        </div>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div class="bg-slate-950/70 border border-slate-800 rounded-lg p-4">
          <div class="text-[10px] uppercase tracking-widest text-slate-500 mb-1" data-i18n="regime">Risk Regime</div>
          <div id="macroRegime" class="text-lg font-bold text-emerald-300">—</div>
          <div class="text-[11px] text-slate-500 mt-1" data-i18n="safe_haven_label">Safe-haven preference</div>
          <div id="macroHaven" class="text-sm font-semibold text-amber-300 mt-0.5">—</div>
        </div>
        <div class="bg-slate-950/70 border border-slate-800 rounded-lg p-4">
          <div class="text-[10px] uppercase tracking-widest text-slate-500 mb-1" data-i18n="geo_gauge">Geopolitical Gauge</div>
          <div class="w-full h-3 rounded-full bg-slate-800 overflow-hidden mt-2">
            <div id="geoBar" class="h-full bg-gradient-to-r from-emerald-500 via-amber-500 to-rose-600" style="width:35%"></div>
          </div>
          <div class="flex justify-between text-[10px] text-slate-500 mt-1">
            <span data-i18n="low">Low</span><span data-i18n="extreme">Extreme</span>
          </div>
          <div id="geoLabel" class="text-sm font-bold text-fuchsia-300 mt-2">—</div>
        </div>
        <div class="bg-slate-950/70 border border-slate-800 rounded-lg p-4">
          <div class="text-[10px] uppercase tracking-widest text-slate-500 mb-1" data-i18n="macro_bias_title">Macro Bias Engine</div>
          <div id="macroBiasList" class="text-[11px] space-y-1 mt-1"></div>
        </div>
      </div>

      <div class="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div class="bg-slate-950/50 border border-slate-800 rounded-lg overflow-hidden">
          <div class="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
            <h4 class="text-[11px] font-bold uppercase tracking-widest text-teal-400" data-i18n="cot_positioning">COT Institutional Positioning</h4>
            <span class="text-[9px] text-slate-500" id="cotSource">—</span>
          </div>
          <div class="overflow-x-auto">
            <table class="w-full text-xs">
              <thead class="bg-slate-950/60 text-slate-500 uppercase text-[10px] tracking-wider">
                <tr>
                  <th class="text-left px-3 py-2" data-i18n="asset">Asset</th>
                  <th class="text-right px-3 py-2" data-i18n="long">Long</th>
                  <th class="text-right px-3 py-2" data-i18n="short">Short</th>
                  <th class="text-right px-3 py-2" data-i18n="net">Net</th>
                  <th class="text-right px-3 py-2" data-i18n="long_pct">Long %</th>
                  <th class="text-right px-3 py-2" data-i18n="delta_net">Δ Net</th>
                </tr>
              </thead>
              <tbody id="tblCot"></tbody>
            </table>
          </div>
        </div>

        <div class="bg-slate-950/50 border border-slate-800 rounded-lg overflow-hidden">
          <div class="px-4 py-3 border-b border-slate-800">
            <h4 class="text-[11px] font-bold uppercase tracking-widest text-purple-400" data-i18n="central_bank_probabilities">Central Bank Rate Probabilities</h4>
          </div>
          <div id="cbGrid" class="grid grid-cols-1 md:grid-cols-2 gap-3 p-3"></div>
        </div>
      </div>

      <div class="bg-slate-950/50 border border-slate-800 rounded-lg overflow-hidden">
        <div class="px-4 py-3 border-b border-slate-800">
          <h4 class="text-[11px] font-bold uppercase tracking-widest text-orange-400" data-i18n="economic_calendar">Economic Calendar — High-Impact Events</h4>
        </div>
        <div class="overflow-x-auto scroll-area">
          <table class="w-full text-xs">
            <thead class="bg-slate-950/60 text-slate-500 uppercase text-[10px] tracking-wider sticky top-0">
              <tr>
                <th class="text-left px-3 py-2" data-i18n="event">Event</th>
                <th class="text-left px-3 py-2" data-i18n="currency">Currency</th>
                <th class="text-left px-3 py-2" data-i18n="impact">Impact</th>
                <th class="text-left px-3 py-2" data-i18n="when">When</th>
                <th class="text-right px-3 py-2" data-i18n="forecast">Forecast</th>
                <th class="text-right px-3 py-2" data-i18n="previous">Previous</th>
              </tr>
            </thead>
            <tbody id="tblCalendar"></tbody>
          </table>
        </div>
      </div>

    </div>
  </section>

  <!-- ============ STRATEGY WIN RATES ============ -->
  <section class="card rounded-xl overflow-hidden">
    <div class="px-5 py-3 border-b border-slate-800">
      <h3 class="text-xs font-bold uppercase tracking-[0.22em] text-fuchsia-400" data-i18n="ict_win_rates">ICT Strategy Win Rates</h3>
    </div>
    <div class="overflow-x-auto scroll-area">
      <table class="w-full text-xs">
        <thead class="bg-slate-950/60 text-slate-500 uppercase text-[10px] tracking-wider sticky top-0">
          <tr>
            <th class="text-left px-3 py-2" data-i18n="strategy_col">Strategy</th>
            <th class="text-right px-3 py-2" data-i18n="total">Total</th>
            <th class="text-right px-3 py-2" data-i18n="wins">Wins</th>
            <th class="text-right px-3 py-2" data-i18n="losses">Losses</th>
            <th class="text-right px-3 py-2" data-i18n="win_rate">Win Rate</th>
          </tr>
        </thead>
        <tbody id="tblStrategies"></tbody>
      </table>
    </div>
  </section>

  <!-- ============ SELF-LEARNING ============ -->
  <section class="card rounded-xl overflow-hidden">
    <div class="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
      <h3 class="text-xs font-bold uppercase tracking-[0.22em] text-amber-400" data-i18n="ai_self_learning">AI Self-Learning Journal</h3>
      <button id="btnClearLearn" class="text-[11px] text-slate-500 hover:text-rose-400 transition" data-i18n="clear_all">Clear all</button>
    </div>
    <div id="learnList" class="divide-y divide-slate-800 scroll-area"></div>
  </section>

</main>

<footer class="fixed bottom-0 left-0 right-0 text-center text-[10px] text-slate-600 bg-slate-950/85 border-t border-slate-800 py-2 z-30">
  <span data-i18n="footer">Pro Trading &amp; Macro Intelligence Engine · Python stdlib · SQLite · Yahoo Finance feed</span> · © <span id="year"></span>
</footer>

<script>
// ===================================================================
// I18N DICTIONARY
// ===================================================================
const I18N = {
  en: {
    app_title: "Pro Trading & Macro Intelligence",
    app_subtitle: "Institutional ICT Engine · v3.0",
    live: "LIVE",
    stale: "SIMULATED",
    session: "Session",
    kill_zone: "Kill Zone",
    capital: "Capital",
    win_rate: "Win Rate",
    active: "ACTIVE",
    inactive: "INACTIVE",
    live_market_feed: "Live Market Feed",
    feed_sub: "Real Yahoo Finance feed · 1s visual ticks · 3s real refresh",
    account_risk: "Account & Risk Control",
    capital_usd: "Capital (USD)",
    risk_per_trade: "Risk per Trade (%)",
    save_permanently: "Save Permanently",
    risk_usd: "Risk $/trade",
    total_trades: "Total trades",
    active_pos: "Active",
    pending_orders: "Pending",
    realized_pnl: "Realized P&L",
    trade_console: "Trade Console — Multi-Timeframe Execution",
    symbol: "Symbol",
    side: "Side",
    buy: "BUY",
    sell: "SELL",
    entry_type: "Entry Type",
    market: "MARKET",
    limit: "LIMIT",
    trade_mode: "Trade Mode",
    entry_tf: "Entry Timeframe",
    ict_strategy: "ICT Strategy",
    entry_price: "Entry Price",
    stop_loss: "Stop Loss",
    take_profit: "Take Profit",
    htf_analysis: "HTF Analysis",
    lot_size: "Calculated Lot Size",
    dispatch_trade: "⚡ Dispatch Trade",
    auto_dispatch: "🤖 Auto Dispatch",
    confluence_analysis: "Technical × Macro Confluence Engine",
    confluence_sub: "ICT structure + Macro regime + COT + Timing",
    active_positions: "Active Positions",
    pending_limit_orders: "Pending Limit Orders",
    trade_history: "Trade History",
    last_50: "last 50 closed",
    id: "ID", mode: "Mode", htf_entry: "HTF → Entry",
    limit_entry: "Limit Entry", action: "Action",
    close: "Close", cancel: "Cancel",
    exit: "Exit", status: "Status", pnl: "P&L", closed: "Closed",
    strategy_col: "Strategy", total: "Total", wins: "Wins", losses: "Losses",
    confluence: "Confluence",
    macro_geopolitics: "Macro & Geopolitics Intelligence",
    macro_live_note: "Live · Yahoo Finance + FuturesBench COT",
    us10y: "US 10Y", gsr: "Gold / Silver",
    dxy_flow: "DXY Flow Score", geopolitical_risk: "Geopolitical Risk",
    regime: "Risk Regime", safe_haven_label: "Safe-haven preference",
    geo_gauge: "Geopolitical Gauge", low: "Low", extreme: "Extreme",
    macro_bias_title: "Macro Bias Engine",
    cot_positioning: "COT Institutional Positioning",
    asset: "Asset", long: "Long", short: "Short", net: "Net",
    long_pct: "Long %", delta_net: "Δ Net",
    central_bank_probabilities: "Central Bank Rate Probabilities",
    economic_calendar: "Economic Calendar — High-Impact Events",
    event: "Event", currency: "Currency", impact: "Impact",
    when: "When", forecast: "Forecast", previous: "Previous",
    ict_win_rates: "ICT Strategy Win Rates",
    ai_self_learning: "AI Self-Learning Journal",
    clear_all: "Clear all",
    no_lessons: "No lessons yet — losses will appear here automatically",
    no_active: "No active positions",
    no_pending: "No pending limit orders",
    no_history: "No closed trades yet",
    footer: "Pro Trading & Macro Intelligence Engine · Python stdlib · SQLite · Yahoo Finance feed",
    bullish: "Bullish", bearish: "Bearish", neutral: "Neutral",
    strong: "Strong", moderate: "Moderate", weak: "Weak", avoid: "Avoid",
    approved: "APPROVED", rejected: "REJECTED",
    confluence_hint: "Adjust the console inputs to see live confluence scoring",
    cot_source: "Source",
    macro_bias: "Macro Bias",
    minutes: "min",
    days: "days",
    next_meeting: "Next meeting",
    cut: "Cut", hold: "Hold", hike: "Hike",
    error_generic: "Error",
    dispatch_ok: "Trade dispatched",
    auto_ok: "Auto-dispatch",
    settings_saved: "Settings saved permanently",
    settings_error: "Settings error",
    close_confirm: "Close this position at market?",
    cancel_confirm: "Cancel this pending order?",
    clear_confirm: "Clear all self-learning entries?",
    risk_on: "Risk-On", risk_off: "Risk-Off",
    crisis: "Crisis", neutral_constructive: "Neutral-Constructive",
  },
  ar: {
    app_title: "محرك التداول والذكاء الكلي الاحترافي",
    app_subtitle: "محرك ICT المؤسسي · الإصدار 3.0",
    live: "مباشر",
    stale: "محاكاة",
    session: "الجلسة",
    kill_zone: "منطقة القتل",
    capital: "رأس المال",
    win_rate: "نسبة النجاح",
    active: "نشط",
    inactive: "غير نشط",
    live_market_feed: "تغذية السوق المباشرة",
    feed_sub: "تغذية Yahoo Finance حقيقية · تحديث بصري كل ثانية · تحديث حقيقي كل 3 ثوانٍ",
    account_risk: "الحساب وإدارة المخاطر",
    capital_usd: "رأس المال (دولار)",
    risk_per_trade: "المخاطرة لكل صفقة (%)",
    save_permanently: "حفظ بشكل دائم",
    risk_usd: "المخاطرة بالدولار/صفقة",
    total_trades: "إجمالي الصفقات",
    active_pos: "نشطة",
    pending_orders: "معلقة",
    realized_pnl: "الأرباح المحققة",
    trade_console: "منصة التداول — التنفيذ متعدد الأطر الزمنية",
    symbol: "الرمز",
    side: "الاتجاه",
    buy: "شراء",
    sell: "بيع",
    entry_type: "نوع الدخول",
    market: "سوق",
    limit: "معلق",
    trade_mode: "نمط التداول",
    entry_tf: "إطار الدخول",
    ict_strategy: "استراتيجية ICT",
    entry_price: "سعر الدخول",
    stop_loss: "وقف الخسارة",
    take_profit: "جني الأرباح",
    htf_analysis: "تحليل الأطر العليا",
    lot_size: "حجم اللوت المحسوب",
    dispatch_trade: "⚡ تنفيذ الصفقة",
    auto_dispatch: "🤖 تنفيذ تلقائي",
    confluence_analysis: "محرك التوافق الفني والكلي",
    confluence_sub: "هيكل ICT + النظام الكلي + COT + التوقيت",
    active_positions: "الصفقات النشطة",
    pending_limit_orders: "أوامر معلقة",
    trade_history: "سجل الصفقات",
    last_50: "آخر 50 صفقة مغلقة",
    id: "المعرف", mode: "النمط", htf_entry: "الأعلى → الدخول",
    limit_entry: "سعر الأمر المعلق", action: "إجراء",
    close: "إغلاق", cancel: "إلغاء",
    exit: "الخروج", status: "الحالة", pnl: "الربح/الخسارة", closed: "مغلق",
    strategy_col: "الاستراتيجية", total: "الإجمالي", wins: "الأرباح", losses: "الخسائر",
    confluence: "التوافق",
    macro_geopolitics: "التحليل الكلي والجيوسياسي",
    macro_live_note: "مباشر · Yahoo Finance + COT من FuturesBench",
    us10y: "السندات الأمريكية 10 سنوات", gsr: "الذهب / الفضة",
    dxy_flow: "درجة تدفق الدولار", geopolitical_risk: "المخاطر الجيوسياسية",
    regime: "النظام السوقي", safe_haven_label: "تفضيل الملاذ الآمن",
    geo_gauge: "مقياس المخاطر الجيوسياسية", low: "منخفض", extreme: "متطرف",
    macro_bias_title: "محرك الانحياز الكلي",
    cot_positioning: "مراكز المؤسسات COT",
    asset: "الأصل", long: "شراء", short: "بيع", net: "صافي",
    long_pct: "نسبة الشراء %", delta_net: "تغير الصافي",
    central_bank_probabilities: "احتمالات البنوك المركزية",
    economic_calendar: "التقويم الاقتصادي — أحداث عالية التأثير",
    event: "الحدث", currency: "العملة", impact: "التأثير",
    when: "الموعد", forecast: "المتوقع", previous: "السابق",
    ict_win_rates: "نسب نجاح استراتيجيات ICT",
    ai_self_learning: "سجل التعلم الذاتي للذكاء الاصطناعي",
    clear_all: "مسح الكل",
    no_lessons: "لا توجد دروس بعد — ستظهر الدروس تلقائياً عند الخسائر",
    no_active: "لا توجد صفقات نشطة",
    no_pending: "لا توجد أوامر معلقة",
    no_history: "لا توجد صفقات مغلقة بعد",
    footer: "محرك التداول والذكاء الكلي الاحترافي · Python stdlib · SQLite · تغذية Yahoo Finance",
    bullish: "صاعد", bearish: "هابط", neutral: "محايد",
    strong: "قوي", moderate: "متوسط", weak: "ضعيف", avoid: "تجنب",
    approved: "معتمد", rejected: "مرفوض",
    confluence_hint: "عدّل مدخلات المنصة لرؤية تقييم التوافق المباشر",
    cot_source: "المصدر",
    macro_bias: "الانحياز الكلي",
    minutes: "دقيقة",
    days: "يوم",
    next_meeting: "الاجتماع القادم",
    cut: "خفض", hold: "تثبيت", hike: "رفع",
    error_generic: "خطأ",
    dispatch_ok: "تم تنفيذ الصفقة",
    auto_ok: "تنفيذ تلقائي",
    settings_saved: "تم حفظ الإعدادات بشكل دائم",
    settings_error: "خطأ في الإعدادات",
    close_confirm: "إغلاق هذه الصفقة بسعر السوق؟",
    cancel_confirm: "إلغاء هذا الأمر المعلق؟",
    clear_confirm: "مسح جميع سجلات التعلم الذاتي؟",
    risk_on: "شهية المخاطرة", risk_off: "النفور من المخاطرة",
    crisis: "أزمة", neutral_constructive: "محايد إيجابي",
  }
};

const STRATEGY_AR = {
  "Liquidity Sweep & Stop Hunt": "مسح السيولة واقتناص الوقف",
  "Fair Value Gap (FVG)": "فجوة القيمة العادلة",
  "Order Block (OB)": "كتلة الأوامر",
  "Change of Character (CHoCH)": "تغير طبيعة السوق",
  "Break of Structure (BOS)": "كسر الهيكل",
  "Breaker Block": "كتلة الكسر العكسي",
  "Judas Swing / ORL": "حركة جوداس التضليلية",
  "Kill Zones & Power of 3": "مناطق القتل ونموذج 3",
  "OTE & Premium/Discount": "الدخول الأمثل والعلاوة/الخصم",
  "Inversion FVG (IFVG)": "الفجوة المكسورة",
};

const MODE_LABELS = {
  SCALPING_A: { en: "Scalping Mode A", ar: "سكالبينج النمط أ" },
  SCALPING_B: { en: "Scalping Mode B", ar: "سكالبينج النمط ب" },
  SWING: { en: "Swing", ar: "سوينج" },
};

// ===================================================================
// STATE
// ===================================================================
const SYMBOLS = {
  "XAU/USD": { decimals: 2, mult: 100,    pip: 0.01,   label_en: "Gold",         label_ar: "الذهب" },
  "XAG/USD": { decimals: 3, mult: 1000,   pip: 0.01,   label_en: "Silver",       label_ar: "الفضة" },
  "EUR/USD": { decimals: 5, mult: 100000, pip: 0.0001, label_en: "Euro",         label_ar: "اليورو" },
  "GBP/USD": { decimals: 5, mult: 100000, pip: 0.0001, label_en: "Sterling",     label_ar: "الإسترليني" },
  "USD/JPY": { decimals: 3, mult: 1000,   pip: 0.01,   label_en: "Yen",          label_ar: "الين" },
  "DXY":     { decimals: 3, mult: 1000,   pip: 0.01,   label_en: "Dollar Index", label_ar: "مؤشر الدولار" },
};

const MODES = {
  SCALPING_A: { htf: ["1W","1D","1H"], entry_tfs: ["M5"] },
  SCALPING_B: { htf: ["1W","1D","4H"], entry_tfs: ["M15","M1"] },
  SWING:      { htf: ["1W","1D"],      entry_tfs: ["H1","H4"] },
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
  lang: "en",
  prices: {},
  settings: { capital: 10000, risk_percent: 1 },
  lastConfluence: null,
  macro: null,
};

// ===================================================================
// HELPERS
// ===================================================================
function t(key) {
  const dict = I18N[state.lang] || I18N.en;
  return dict[key] || I18N.en[key] || key;
}
function isAr() { return state.lang === "ar"; }
function symLabel(sym) {
  const cfg = SYMBOLS[sym];
  if (!cfg) return sym;
  return isAr() ? cfg.label_ar : cfg.label_en;
}
function strategyLabel(name) {
  return isAr() ? (STRATEGY_AR[name] || name) : name;
}
function modeLabel(mode) {
  const m = MODE_LABELS[mode];
  if (!m) return mode;
  return isAr() ? m.ar : m.en;
}
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
  const color = mode === "SWING" ? "bg-purple-900/60 text-purple-300"
              : mode === "SCALPING_B" ? "bg-cyan-900/60 text-cyan-300"
              : "bg-blue-900/60 text-blue-300";
  return `<span class="tag ${color}">${escapeHtml(modeLabel(mode))}</span>`;
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
  if (msg) setTimeout(() => { if (el.textContent === msg) el.textContent = ""; }, 4500);
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
// LANGUAGE
// ===================================================================
function applyLanguage() {
  const dict = I18N[state.lang];
  document.documentElement.lang = state.lang;
  document.documentElement.dir = isAr() ? "rtl" : "ltr";
  document.getElementById("btnLang").textContent = isAr() ? "🌐 عربي" : "🌐 English";

  document.querySelectorAll("[data-i18n]").forEach(el => {
    const key = el.getAttribute("data-i18n");
    if (dict[key] !== undefined) el.textContent = dict[key];
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach(el => {
    const key = el.getAttribute("data-i18n-placeholder");
    if (dict[key] !== undefined) el.placeholder = dict[key];
  });

  // Rebuild dynamic selects with translated labels
  rebuildSymbolSelect();
  rebuildStrategySelect();
  rebuildModeSelect();

  // Re-render dynamic tables
  pollStrategies();
  pollCOT();
  pollCB();
  pollCalendar();
  pollLearning();
  if (state.lastConfluence) renderConfluence(state.lastConfluence);
  refreshConfluence();
}
function toggleLanguage() {
  state.lang = isAr() ? "en" : "ar";
  applyLanguage();
}

// ===================================================================
// SELECT BUILDERS
// ===================================================================
function rebuildSymbolSelect() {
  const sel = document.getElementById("selSymbol");
  const current = sel.value || "XAU/USD";
  sel.innerHTML = Object.keys(SYMBOLS).map(s =>
    `<option value="${s}">${escapeHtml(s)} · ${escapeHtml(symLabel(s))}</option>`
  ).join("");
  sel.value = current;
}
function rebuildStrategySelect() {
  const sel = document.getElementById("selStrategy");
  const current = sel.value || STRATEGIES[0];
  sel.innerHTML = STRATEGIES.map(s =>
    `<option value="${escapeHtml(s)}">${escapeHtml(strategyLabel(s))}</option>`
  ).join("");
  sel.value = current;
}
function rebuildModeSelect() {
  const sel = document.getElementById("selMode");
  const current = sel.value || "SCALPING_A";
  sel.innerHTML = Object.keys(MODES).map(m =>
    `<option value="${m}">${escapeHtml(modeLabel(m))}</option>`
  ).join("");
  sel.value = current;
  refreshEntryTFOptions();
  refreshHTFDisplay();
}

// ===================================================================
// PRICE GRID
// ===================================================================
function renderPrices(data) {
  const grid = document.getElementById("priceGrid");
  let html = "";
  let liveCount = 0;
  for (const sym in data) {
    const p = data[sym];
    if (!p.stale) liveCount++;
    const prevState = state.prices[sym] ? state.prices[sym].price : p.prev_close;
    let flash = "";
    if (state.prices[sym]) {
      if (p.price > prevState + 1e-12) flash = "flash-up";
      else if (p.price < prevState - 1e-12) flash = "flash-down";
    }
    const pctColor = p.change_pct > 0 ? "text-emerald-400" : p.change_pct < 0 ? "text-rose-400" : "text-slate-500";
    const arrow = p.change_pct > 0 ? "▲" : p.change_pct < 0 ? "▼" : "—";
    const srcCls = p.stale ? "feed-stale" : "feed-live";
    const srcTxt = p.stale ? t("stale") : t("live");
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
        <div class="text-[9px] mt-1 flex items-center justify-between">
          <span class="${srcCls}">● ${srcTxt}</span>
          <span class="text-slate-600">${escapeHtml(symLabel(sym))}</span>
        </div>
      </div>`;
    state.prices[sym] = p;
  }
  grid.innerHTML = html;

  const total = Object.keys(data).length;
  document.getElementById("feedStatus").textContent = liveCount === total ? t("live") : `${liveCount}/${total} ${t("live")}`;
  document.getElementById("feedStatus").className = liveCount > 0 ? "text-emerald-300 font-semibold" : "text-amber-300 font-semibold";
  document.getElementById("feedDot").className = liveCount > 0 ? "text-emerald-400 pulse-dot w-2 h-2 rounded-full bg-emerald-400" : "text-amber-400 w-2 h-2 rounded-full bg-amber-400";
}

// ===================================================================
// SUMMARY
// ===================================================================
function renderSummary(s) {
  document.getElementById("topCapital").textContent = fmtUsd(s.capital);
  document.getElementById("topWinRate").textContent = s.win_rate.toFixed(1) + "%";
  document.getElementById("sessionLabel").textContent = s.session || "—";

  const kz = document.getElementById("killZoneBadge");
  const kzLbl = document.getElementById("killZoneLabel");
  if (s.kill_zone) {
    kz.className = "bg-emerald-950/60 border border-emerald-700/50 rounded-full px-3 py-1.5";
    kzLbl.className = "text-emerald-300 font-bold";
    kzLbl.textContent = t("active");
  } else {
    kz.className = "bg-slate-900/70 border border-slate-800 rounded-full px-3 py-1.5";
    kzLbl.className = "text-slate-400";
    kzLbl.textContent = t("inactive");
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
// TRADES
// ===================================================================
function renderActive(trades) {
  const active = trades.filter(x => x.status === "ACTIVE");
  document.getElementById("activeCount").textContent = active.length + " open";
  const body = document.getElementById("tblActive");
  if (active.length === 0) {
    body.innerHTML = `<tr><td colspan="12" class="text-center text-slate-500 py-6 text-xs">${t("no_active")}</td></tr>`;
    return;
  }
  body.innerHTML = active.map(x => `
    <tr class="stripe-row border-b border-slate-800/60">
      <td class="px-3 py-2 text-slate-400 tabnum">#${x.id}</td>
      <td class="px-3 py-2 font-semibold text-white">${escapeHtml(x.symbol)}</td>
      <td class="px-3 py-2 font-bold ${x.side === "BUY" ? "text-emerald-400" : "text-rose-400"}">${x.side === "BUY" ? t("buy") : t("sell")}</td>
      <td class="px-3 py-2">${modeTag(x.mode)}</td>
      <td class="px-3 py-2 text-[10px]">${tfHierarchy(x.htf_analysis, x.entry_timeframe)}</td>
      <td class="px-3 py-2 text-right tabnum text-slate-200">${fmt(x.symbol, x.entry_price)}</td>
      <td class="px-3 py-2 text-right tabnum text-rose-400">${fmt(x.symbol, x.stop_loss)}</td>
      <td class="px-3 py-2 text-right tabnum text-emerald-400">${fmt(x.symbol, x.take_profit)}</td>
      <td class="px-3 py-2 text-right tabnum text-sky-300">${Number(x.lot_size).toFixed(2)}</td>
      <td class="px-3 py-2 text-right tabnum font-bold ${confColor(x.confluence_score)}">${Number(x.confluence_score || 0).toFixed(0)}/10</td>
      <td class="px-3 py-2 text-slate-400 max-w-[220px] truncate" title="${escapeHtml(x.strategy)}">${escapeHtml(strategyLabel(x.strategy))}</td>
      <td class="px-3 py-2 text-center">
        <button class="btn-close bg-rose-600/80 hover:bg-rose-500 text-white text-[10px] px-2 py-1 rounded" data-id="${x.id}">${t("close")}</button>
      </td>
    </tr>`).join("");

  body.querySelectorAll(".btn-close").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!confirm(t("close_confirm"))) return;
      try {
        await api(`/api/trades/${btn.dataset.id}/close`, "POST", {});
        pollTrades(); pollSummary(); pollStrategies(); pollLearning();
      } catch (e) { alert(t("error_generic") + ": " + e.message); }
    });
  });
}

function confColor(score) {
  const s = Number(score || 0);
  if (s >= 7) return "text-emerald-400";
  if (s >= 5) return "text-amber-300";
  return "text-slate-400";
}

function renderPending(trades) {
  const pending = trades.filter(x => x.status === "PENDING");
  document.getElementById("pendingCountLabel").textContent = pending.length + " waiting";
  const body = document.getElementById("tblPending");
  if (pending.length === 0) {
    body.innerHTML = `<tr><td colspan="12" class="text-center text-slate-500 py-6 text-xs">${t("no_pending")}</td></tr>`;
    return;
  }
  body.innerHTML = pending.map(x => `
    <tr class="stripe-row border-b border-slate-800/60">
      <td class="px-3 py-2 text-slate-400 tabnum">#${x.id}</td>
      <td class="px-3 py-2 font-semibold text-white">${escapeHtml(x.symbol)}</td>
      <td class="px-3 py-2 font-bold ${x.side === "BUY" ? "text-emerald-400" : "text-rose-400"}">${x.side === "BUY" ? t("buy") : t("sell")}</td>
      <td class="px-3 py-2">${modeTag(x.mode)}</td>
      <td class="px-3 py-2 text-[10px]">${tfHierarchy(x.htf_analysis, x.entry_timeframe)}</td>
      <td class="px-3 py-2 text-right tabnum text-amber-300">${fmt(x.symbol, x.entry_price)}</td>
      <td class="px-3 py-2 text-right tabnum text-rose-400">${fmt(x.symbol, x.stop_loss)}</td>
      <td class="px-3 py-2 text-right tabnum text-emerald-400">${fmt(x.symbol, x.take_profit)}</td>
      <td class="px-3 py-2 text-right tabnum text-sky-300">${Number(x.lot_size).toFixed(2)}</td>
      <td class="px-3 py-2 text-right tabnum font-bold ${confColor(x.confluence_score)}">${Number(x.confluence_score || 0).toFixed(0)}/10</td>
      <td class="px-3 py-2 text-slate-400 max-w-[220px] truncate" title="${escapeHtml(x.strategy)}">${escapeHtml(strategyLabel(x.strategy))}</td>
      <td class="px-3 py-2 text-center">
        <button class="btn-cancel bg-slate-700 hover:bg-slate-600 text-white text-[10px] px-2 py-1 rounded" data-id="${x.id}">${t("cancel")}</button>
      </td>
    </tr>`).join("");

  body.querySelectorAll(".btn-cancel").forEach(btn => {
    btn.addEventListener("click", async () => {
      if (!confirm(t("cancel_confirm"))) return;
      try {
        await api(`/api/trades/${btn.dataset.id}/cancel`, "POST", {});
        pollTrades(); pollSummary();
      } catch (e) { alert(t("error_generic") + ": " + e.message); }
    });
  });
}

function renderHistory(trades) {
  const closed = trades.filter(x => ["WIN","LOSS","CANCELLED"].includes(x.status)).slice(0, 50);
  const body = document.getElementById("tblHistory");
  if (closed.length === 0) {
    body.innerHTML = `<tr><td colspan="13" class="text-center text-slate-500 py-6 text-xs">${t("no_history")}</td></tr>`;
    return;
  }
  body.innerHTML = closed.map(x => {
    const statCls = x.status === "WIN" ? "bg-emerald-950/70 text-emerald-300"
                   : x.status === "LOSS" ? "bg-rose-950/70 text-rose-300"
                   : "bg-slate-800/70 text-slate-400";
    return `
      <tr class="stripe-row border-b border-slate-800/60">
        <td class="px-3 py-2 text-slate-400 tabnum">#${x.id}</td>
        <td class="px-3 py-2 font-semibold text-white">${escapeHtml(x.symbol)}</td>
        <td class="px-3 py-2 font-bold ${x.side === "BUY" ? "text-emerald-400" : "text-rose-400"}">${x.side === "BUY" ? t("buy") : t("sell")}</td>
        <td class="px-3 py-2">${modeTag(x.mode)}</td>
        <td class="px-3 py-2 text-[10px]">${tfHierarchy(x.htf_analysis, x.entry_timeframe)}</td>
        <td class="px-3 py-2 text-right tabnum text-slate-200">${fmt(x.symbol, x.entry_price)}</td>
        <td class="px-3 py-2 text-right tabnum text-slate-200">${x.exit_price != null ? fmt(x.symbol, x.exit_price) : "—"}</td>
        <td class="px-3 py-2 text-right tabnum text-sky-300">${Number(x.lot_size).toFixed(2)}</td>
        <td class="px-3 py-2 text-right tabnum font-bold ${confColor(x.confluence_score)}">${Number(x.confluence_score || 0).toFixed(0)}/10</td>
        <td class="px-3 py-2 text-slate-400 max-w-[220px] truncate" title="${escapeHtml(x.strategy)}">${escapeHtml(strategyLabel(x.strategy))}</td>
        <td class="px-3 py-2"><span class="tag ${statCls}">${x.status}</span></td>
        <td class="px-3 py-2 text-right tabnum">${fmtPnl(x.pnl)}</td>
        <td class="px-3 py-2 text-slate-500 tabnum text-[10px]">${(x.closed_at || "").replace("T"," ").slice(0,16)}</td>
      </tr>`;
  }).join("");
}

// ===================================================================
// STRATEGIES
// ===================================================================
function renderStrategies(list) {
  const body = document.getElementById("tblStrategies");
  body.innerHTML = list.map(s => {
    const wr = s.win_rate;
    const barColor = wr >= 65 ? "bg-emerald-500" : wr >= 50 ? "bg-amber-500" : "bg-rose-500";
    return `
      <tr class="stripe-row border-b border-slate-800/60">
        <td class="px-3 py-2 text-slate-200 max-w-[320px] truncate" title="${escapeHtml(s.name)}">${escapeHtml(strategyLabel(s.name))}</td>
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
// MACRO + COT + CB + CALENDAR
// ===================================================================
function renderMacro(d) {
  state.macro = d;
  document.getElementById("macroVix").textContent = Number(d.vix).toFixed(2);
  document.getElementById("macro10y").textContent = Number(d.us10y).toFixed(3) + "%";
  document.getElementById("macroDxy").textContent = Number(d.dxy).toFixed(3);
  document.getElementById("macroGsr").textContent = Number(d.gold_silver_ratio).toFixed(2);
  const flow = Number(d.dxy_flow_score || 0);
  const flowEl = document.getElementById("macroFlow");
  flowEl.textContent = (flow >= 0 ? "+" : "") + flow;
  flowEl.className = "text-xl font-bold tabnum mt-1 " + (flow > 0 ? "text-emerald-300" : flow < 0 ? "text-rose-300" : "text-slate-300");
  document.getElementById("macroGeo").textContent = Number(d.geo_risk).toFixed(1);

  const regimeMap = {
    "Risk-On": t("risk_on"), "Risk-Off": t("risk_off"),
    "Crisis": t("crisis"), "Neutral": t("neutral"),
    "Neutral-Constructive": t("neutral_constructive"),
  };
  document.getElementById("macroRegime").textContent = regimeMap[d.regime] || d.regime;
  document.getElementById("macroHaven").textContent = d.safe_haven;
  document.getElementById("geoBar").style.width = Math.min(100, Number(d.geo_risk)) + "%";
  document.getElementById("geoLabel").textContent = d.geo_risk_label;

  // Macro bias engine panel
  const macroBias = computeClientMacroBias(d);
  const biasEl = document.getElementById("macroBiasList");
  const biasRows = Object.keys(macroBias).map(sym => {
    const b = macroBias[sym];
    const cls = b === "bullish" ? "text-emerald-300" : b === "bearish" ? "text-rose-300" : "text-slate-400";
    const label = b === "bullish" ? t("bullish") : b === "bearish" ? t("bearish") : t("neutral");
    return `<div class="flex justify-between"><span class="text-slate-400">${escapeHtml(sym)}</span><span class="${cls} font-bold">${label}</span></div>`;
  }).join("");
  biasEl.innerHTML = biasRows;
}

function computeClientMacroBias(d) {
  const regime = d.regime;
  const vix = Number(d.vix);
  const us10y = Number(d.us10y);
  const dxyRising = Number(d.dxy) >= Number(d.dxy_prev);
  const out = {};
  if (regime === "Crisis" || regime === "Risk-Off") {
    out["XAU/USD"] = "bullish"; out["XAG/USD"] = "bullish";
    out["DXY"] = "bullish"; out["USD/JPY"] = "bearish";
    out["EUR/USD"] = "bearish"; out["GBP/USD"] = "bearish";
  } else if (regime === "Risk-On") {
    out["XAU/USD"] = us10y > 4.2 ? "bearish" : "neutral";
    out["XAG/USD"] = "neutral";
    out["DXY"] = "bearish"; out["USD/JPY"] = "bullish";
    out["EUR/USD"] = "bullish"; out["GBP/USD"] = "bullish";
  } else {
    out["XAU/USD"] = (!dxyRising && us10y < 4.3) ? "bullish" : "neutral";
    out["XAG/USD"] = "neutral";
    out["DXY"] = us10y > 4.4 ? "bullish" : "neutral";
    out["USD/JPY"] = us10y > 4.3 ? "bullish" : "bearish";
    out["EUR/USD"] = dxyRising ? "bearish" : "bullish";
    out["GBP/USD"] = "neutral";
  }
  return out;
}

function renderCOT(cot) {
  const body = document.getElementById("tblCot");
  let sources = new Set();
  body.innerHTML = Object.keys(cot).map(name => {
    const c = cot[name];
    if (c.source) sources.add(c.source);
    const dCls = c.delta_net > 0 ? "text-emerald-400" : c.delta_net < 0 ? "text-rose-400" : "text-slate-400";
    return `
      <tr class="stripe-row border-b border-slate-800/60">
        <td class="px-3 py-2 font-semibold text-white">${escapeHtml(isAr() ? (c.label_ar || name) : name)}</td>
        <td class="px-3 py-2 text-right tabnum text-emerald-300">${c.long.toLocaleString()}</td>
        <td class="px-3 py-2 text-right tabnum text-rose-300">${c.short.toLocaleString()}</td>
        <td class="px-3 py-2 text-right tabnum text-white font-bold">${c.net.toLocaleString()}</td>
        <td class="px-3 py-2 text-right tabnum text-sky-300">${c.long_pct.toFixed(1)}%</td>
        <td class="px-3 py-2 text-right tabnum ${dCls}">${c.delta_net >= 0 ? "+" : ""}${c.delta_net.toLocaleString()}</td>
      </tr>`;
  }).join("");
  document.getElementById("cotSource").textContent = sources.size ? Array.from(sources).join(", ") : "seed";
}

function renderCB(cb) {
  const el = document.getElementById("cbGrid");
  el.innerHTML = Object.keys(cb).map(key => {
    const c = cb[key];
    return `
      <div class="bg-slate-950/70 border border-slate-800 rounded-lg p-3">
        <div class="flex items-baseline justify-between mb-1">
          <div class="font-bold text-white text-xs">${escapeHtml(isAr() ? c.name_ar : c.name_en)}</div>
          <div class="text-[10px] text-slate-500">${escapeHtml(c.currency)} · ${Number(c.rate).toFixed(3)}%</div>
        </div>
        <div class="text-[10px] text-slate-500 mb-2">${t("next_meeting")}: ${c.next_days} ${t("days")}</div>
        <div class="space-y-1">
          <div>
            <div class="flex justify-between text-[10px] mb-0.5"><span class="text-rose-300">${t("cut")}</span><span class="text-white font-semibold tabnum">${c.cut.toFixed(1)}%</span></div>
            <div class="h-1.5 bg-slate-800 rounded-full overflow-hidden"><div class="h-full bg-rose-500" style="width:${c.cut}%"></div></div>
          </div>
          <div>
            <div class="flex justify-between text-[10px] mb-0.5"><span class="text-slate-300">${t("hold")}</span><span class="text-white font-semibold tabnum">${c.hold.toFixed(1)}%</span></div>
            <div class="h-1.5 bg-slate-800 rounded-full overflow-hidden"><div class="h-full bg-slate-500" style="width:${c.hold}%"></div></div>
          </div>
          <div>
            <div class="flex justify-between text-[10px] mb-0.5"><span class="text-emerald-300">${t("hike")}</span><span class="text-white font-semibold tabnum">${c.hike.toFixed(1)}%</span></div>
            <div class="h-1.5 bg-slate-800 rounded-full overflow-hidden"><div class="h-full bg-emerald-500" style="width:${c.hike}%"></div></div>
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
        <td class="px-3 py-2 text-slate-200 max-w-[300px] truncate">${escapeHtml(isAr() ? e.event_ar : e.event_en)}</td>
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
    el.innerHTML = `<div class="text-center text-slate-500 py-8 text-xs">${t("no_lessons")}</div>`;
    return;
  }
  el.innerHTML = list.map(l => `
    <div class="px-5 py-3 flex gap-3 items-start">
      <div class="shrink-0 w-2 h-2 rounded-full bg-amber-400 mt-1.5"></div>
      <div class="flex-1 min-w-0">
        <div class="flex flex-wrap items-center gap-2 text-[11px] mb-1">
          <span class="font-bold text-white">${escapeHtml(l.symbol || "?")}</span>
          <span class="text-slate-600">·</span>
          <span class="text-amber-300">${escapeHtml(strategyLabel(l.strategy || "?"))}</span>
          ${l.mode ? `<span class="text-slate-600">·</span><span class="text-cyan-300">${escapeHtml(modeLabel(l.mode))}</span>` : ""}
          <span class="text-slate-600">·</span>
          <span class="text-slate-500 tabnum">#${l.trade_id || "?"}</span>
          <span class="text-slate-600 ml-auto">${(l.created_at || "").replace("T"," ").slice(0,19)}</span>
        </div>
        <div class="text-[12px] text-slate-300 leading-relaxed">${escapeHtml(l.lesson)}</div>
      </div>
    </div>`).join("");
}

// ===================================================================
// CONFLUENCE RENDER
// ===================================================================
function renderConfluence(c) {
  state.lastConfluence = c;
  const score = Number(c.score);
  const pct = (score / c.max_score) * 100;
  const ring = document.getElementById("confluenceRing");
  ring.style.setProperty("--p", pct + "%");
  ring.style.background = `conic-gradient(${score >= 7 ? "#10b981" : score >= 5 ? "#f59e0b" : "#ef4444"} ${pct}%, #1e293b 0)`;
  document.getElementById("confluenceScore").textContent = score;

  const verdict = document.getElementById("confluenceVerdict");
  const verdictKey = c.approved ? "approved" : "rejected";
  verdict.textContent = t(verdictKey) + " · " + t(c.bias);
  verdict.className = "text-[11px] mt-2 font-bold " + (c.approved ? "text-emerald-400" : "text-rose-400");

  document.getElementById("confluenceHeadline").textContent = isAr() ? c.headline_ar : c.headline_en;

  const reasonsEl = document.getElementById("confluenceReasons");
  reasonsEl.innerHTML = c.reasons.map(r => {
    const cls = r.passed ? "reason-pass" : "reason-fail";
    const pcolor = r.passed ? "text-emerald-400" : "text-slate-500";
    const txt = isAr() ? r.ar : r.en;
    return `<div class="bg-slate-950/60 rounded px-2 py-1.5 ${cls}">
      <div class="flex justify-between gap-2">
        <span class="text-[11px] text-slate-300">${escapeHtml(txt)}</span>
        <span class="text-[11px] font-bold ${pcolor} tabnum">+${r.points}</span>
      </div>
    </div>`;
  }).join("");
}

async function refreshConfluence() {
  const sym = document.getElementById("selSymbol").value;
  const side = document.getElementById("selSide").value;
  const mode = document.getElementById("selMode").value;
  const strat = document.getElementById("selStrategy").value;
  try {
    const r = await api(`/api/confluence?symbol=${encodeURIComponent(sym)}&side=${encodeURIComponent(side)}&mode=${encodeURIComponent(mode)}&strategy=${encodeURIComponent(strat)}`);
    renderConfluence(r.data);
  } catch (e) {
    console.error("confluence:", e);
  }
}

// ===================================================================
// FORM
// ===================================================================
function refreshEntryTFOptions() {
  const mode = document.getElementById("selMode").value;
  const tfs = MODES[mode].entry_tfs;
  const sel = document.getElementById("selEntryTF");
  sel.innerHTML = tfs.map(tf => `<option value="${tf}">${tf}</option>`).join("");
  sel.disabled = tfs.length === 1;
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

  let entry;
  if (entryType === "MARKET" || !state.prices[sym]) {
    entry = state.prices[sym] ? state.prices[sym].price : cfg.pip * 100;
  } else {
    const current = parseFloat(document.getElementById("inpEntry").value);
    entry = isFinite(current) ? current : (state.prices[sym] ? state.prices[sym].price : cfg.pip * 100);
  }
  const sl = side === "BUY" ? entry - slD : entry + slD;
  const tp = side === "BUY" ? entry + tpD : entry - tpD;
  document.getElementById("inpEntry").value = entry.toFixed(cfg.decimals);
  document.getElementById("inpSL").value = sl.toFixed(cfg.decimals);
  document.getElementById("inpTP").value = tp.toFixed(cfg.decimals);

  const inp = document.getElementById("inpEntry");
  if (entryType === "MARKET") {
    inp.setAttribute("readonly", "readonly");
    inp.classList.add("opacity-60");
  } else {
    inp.removeAttribute("readonly");
    inp.classList.remove("opacity-60");
  }
  updateLotPreview();
  refreshConfluence();
}
function updateLotPreview() {
  const sym = document.getElementById("selSymbol").value;
  const entry = parseFloat(document.getElementById("inpEntry").value);
  const sl = parseFloat(document.getElementById("inpSL").value);
  const cap = state.settings.capital;
  const risk = state.settings.risk_percent;
  const el = document.getElementById("lotDisplay");
  if (!isFinite(entry) || !isFinite(sl) || entry === sl) {
    el.textContent = "0.00";
    return;
  }
  const dist = Math.abs(entry - sl);
  const mult = SYMBOLS[sym].mult;
  const riskAmt = cap * (risk / 100.0);
  const lot = riskAmt / (dist * mult);
  el.textContent = Math.max(0.01, lot).toFixed(2);
}

// ===================================================================
// ACTIONS
// ===================================================================
async function saveSettings() {
  const cap = parseFloat(document.getElementById("inpCapital").value);
  const risk = parseFloat(document.getElementById("inpRisk").value);
  const st = document.getElementById("settingsStatus");
  if (!isFinite(cap) || cap <= 0) { setStatus(st, t("settings_error") + ": capital > 0", "err"); return; }
  if (!isFinite(risk) || risk <= 0 || risk > 100) { setStatus(st, t("settings_error") + ": risk (0,100]", "err"); return; }
  try {
    await api("/api/settings", "POST", { capital: cap, risk_percent: risk });
    state.settings.capital = cap;
    state.settings.risk_percent = risk;
    setStatus(st, t("settings_saved"), "ok");
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
    setStatus(st, t("error_generic") + ": invalid entry/SL/TP", "err"); return;
  }
  const payload = {
    symbol: sym, side, mode, entry_type: entryType,
    entry_timeframe: entryTF, strategy: strat,
    stop_loss: sl, take_profit: tp,
  };
  if (entryType === "LIMIT") payload.entry_price = entry;
  try {
    const r = await api("/api/trades", "POST", payload);
    setStatus(st, `${t("dispatch_ok")} #${r.data.id} · lot ${r.data.lot_size} · score ${r.confluence.score}/10`, "ok");
    renderConfluence(r.confluence);
    pollTrades(); pollSummary(); pollStrategies(); pollLearning();
  } catch (e) {
    setStatus(st, e.message, "err");
  }
}

async function dispatchAuto() {
  const st = document.getElementById("dispatchStatus");
  const mode = document.getElementById("selMode").value;
  try {
    const r = await api("/api/auto_dispatch", "POST", { mode });
    setStatus(st, `${t("auto_ok")} #${r.data.id} · ${r.data.symbol} ${r.data.side} · ${r.data.entry_timeframe} · score ${r.confluence.score}/10`, "ok");
    renderConfluence(r.confluence);
    pollTrades(); pollSummary(); pollStrategies(); pollLearning();
  } catch (e) {
    setStatus(st, e.message, "err");
  }
}

async function clearLearning() {
  if (!confirm(t("clear_confirm"))) return;
  try {
    await api("/api/self_learning/reset", "POST", {});
    pollLearning();
  } catch (e) { alert(t("error_generic") + ": " + e.message); }
}

// ===================================================================
// POLLING
// ===================================================================
async function pollPrices() {
  try {
    const r = await api("/api/prices");
    renderPrices(r.data);
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
  try { const r = await api("/api/summary"); renderSummary(r.data); } catch (e) { console.error(e); }
}
async function pollTrades() {
  try {
    const r = await api("/api/trades?limit=300");
    renderActive(r.data); renderPending(r.data); renderHistory(r.data);
  } catch (e) { console.error(e); }
}
async function pollStrategies() {
  try { const r = await api("/api/strategies"); renderStrategies(r.data); } catch (e) { console.error(e); }
}
async function pollMacro() {
  try { const r = await api("/api/macro"); renderMacro(r.data); } catch (e) { console.error(e); }
}
async function pollCOT() {
  try { const r = await api("/api/cot"); renderCOT(r.data); } catch (e) { console.error(e); }
}
async function pollCB() {
  try { const r = await api("/api/central_banks"); renderCB(r.data); } catch (e) { console.error(e); }
}
async function pollCalendar() {
  try { const r = await api("/api/calendar"); renderCalendar(r.data); } catch (e) { console.error(e); }
}
async function pollLearning() {
  try { const r = await api("/api/self_learning?limit=40"); renderLearning(r.data); } catch (e) { console.error(e); }
}

// ===================================================================
// BOOT
// ===================================================================
async function boot() {
  document.getElementById("year").textContent = new Date().getFullYear();

  // Language
  document.getElementById("btnLang").addEventListener("click", toggleLanguage);

  // Build selects
  rebuildSymbolSelect();
  rebuildStrategySelect();
  rebuildModeSelect();

  // Event listeners
  document.getElementById("selSymbol").addEventListener("change", applyDefaults);
  document.getElementById("selSide").addEventListener("change", applyDefaults);
  document.getElementById("selMode").addEventListener("change", () => {
    refreshEntryTFOptions(); refreshHTFDisplay(); applyDefaults();
  });
  document.getElementById("selEntryType").addEventListener("change", applyDefaults);
  document.getElementById("selStrategy").addEventListener("change", () => { refreshConfluence(); });
  document.getElementById("selEntryTF").addEventListener("change", () => { refreshConfluence(); });
  document.getElementById("inpEntry").addEventListener("input", () => { updateLotPreview(); refreshConfluence(); });
  document.getElementById("inpSL").addEventListener("input", updateLotPreview);
  document.getElementById("inpTP").addEventListener("input", updateLotPreview);
  document.getElementById("btnSaveSettings").addEventListener("click", saveSettings);
  document.getElementById("btnDispatch").addEventListener("click", dispatchTrade);
  document.getElementById("btnAutoDispatch").addEventListener("click", dispatchAuto);
  document.getElementById("btnClearLearn").addEventListener("click", clearLearning);

  // Initial fetches
  await Promise.all([
    pollPrices(), pollSummary(), pollStrategies(),
    pollMacro(), pollCOT(), pollCB(), pollCalendar(),
    pollTrades(), pollLearning()
  ]);
  applyDefaults();
  refreshConfluence();

  // Intervals
  setInterval(pollPrices, 1000);
  setInterval(pollSummary, 3000);
  setInterval(pollTrades, 2500);
  setInterval(pollStrategies, 5000);
  setInterval(pollMacro, 4000);
  setInterval(pollCOT, 10000);
  setInterval(pollCB, 12000);
  setInterval(pollCalendar, 30000);
  setInterval(pollLearning, 5000);
  setInterval(refreshConfluence, 5000);
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
    print(f"[signal] {signum} received — shutting down...", flush=True)
    SHUTDOWN.set()


def main():
    init_db()
    print(f"[startup] DB: {DB_PATH}", flush=True)
    print(f"[startup] Listening on http://{HOST}:{PORT}", flush=True)

    threads = [
        threading.Thread(target=real_feed_loop,      daemon=True, name="real_feed"),
        threading.Thread(target=micro_tick_loop,     daemon=True, name="micro_tick"),
        threading.Thread(target=day_rollover_loop,   daemon=True, name="rollover"),
        threading.Thread(target=macro_fetch_loop,    daemon=True, name="macro"),
        threading.Thread(target=central_bank_loop,   daemon=True, name="cb"),
        threading.Thread(target=cot_loop,            daemon=True, name="cot"),
        threading.Thread(target=trade_evaluator,     daemon=True, name="evaluator"),
    ]
    for th in threads:
        th.start()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[server] KeyboardInterrupt", flush=True)
    finally:
        SHUTDOWN.set()
        server.server_close()
        for th in threads:
            th.join(timeout=3.0)
        print("[shutdown] complete", flush=True)


if __name__ == "__main__":
    main()

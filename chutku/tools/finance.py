"""Stock quotes (X9): Yahoo Finance's public, keyless endpoints, read with the standard library only.

Every quote is cached in data/finance-cache.json, and every answer says when its price is from. When the network or
Yahoo fails, the last known price is given and labelled as such; with nothing cached, Chutku says no price is known.
Indian names prefer the NSE listing (.NS) when Yahoo's search offers one.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import threading
import time
import urllib.parse

from chutku.tools.registry import Risk, Tool, ToolResult, Verification

SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search?quotesCount=8&newsCount=0&q="
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{}?range=1d&interval=1d"
CACHE = Path(__file__).resolve().parents[2] / "data" / "finance-cache.json"
MAX_SYMBOLS, MAX_NAMES = 200, 400
_TICKER = re.compile(r"\^?[A-Z0-9][A-Z0-9&-]{0,14}(?:\.[A-Z]{1,3}|=[A-Z])?")
_KINDS = {"EQUITY", "ETF", "INDEX", "MUTUALFUND"}
_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}
_lock = threading.Lock()


def _key(name):
    return " ".join(str(name).casefold().split())


def _load():
    try:
        data = json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("quotes", {})
    data.setdefault("names", {})
    return data


def _remember(query, quote):
    with _lock:
        data = _load()
        data["quotes"][quote["symbol"]] = quote
        data["names"].pop(_key(query), None)
        data["names"][_key(query)] = quote["symbol"]   # last asked last, so the bound drops the oldest names
        newest = sorted(data["quotes"], key=lambda s: data["quotes"][s].get("fetched", 0), reverse=True)[:MAX_SYMBOLS]
        data["quotes"] = {s: data["quotes"][s] for s in newest}
        names = [(n, s) for n, s in data["names"].items() if s in data["quotes"]]
        data["names"] = dict(names[-MAX_NAMES:])
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        temporary = CACHE.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(temporary, CACHE)   # never a half-written cache


def _cached(query):
    data = _load()
    symbol = data["names"].get(_key(query)) or query.strip().upper()
    return data["quotes"].get(symbol)


def _symbol(query):
    """The Yahoo symbol for a ticker or a company name; the NSE listing first when there is one."""
    from chutku.tools.internet import fetch
    upper = query.strip().upper()
    if _TICKER.fullmatch(upper) and any(mark in upper for mark in ".^="):
        return upper   # an exact listing such as RELIANCE.NS or ^NSEI
    found = json.loads(fetch(SEARCH_URL + urllib.parse.quote(query), accept="application/json")[0]).get("quotes") or []
    found = [q for q in found if isinstance(q, dict) and q.get("symbol") and q.get("quoteType") in _KINDS]
    if not found:
        return None
    wanted = re.sub(r"[^A-Z0-9&-]", "", upper)
    # shortcut: "any NSE listing" can pick the wrong one for a foreign name that also matches an Indian company;
    # add an exchange argument if that is seen live.
    for rule in (lambda q: q["symbol"] == wanted + ".NS", lambda q: q["symbol"] == wanted,
                 lambda q: q["symbol"].endswith(".NS")):
        match = next((q for q in found if rule(q)), None)
        if match:
            return match["symbol"]
    return found[0]["symbol"]


def _quote(symbol):
    from chutku.tools.internet import fetch
    body = json.loads(fetch(CHART_URL.format(urllib.parse.quote(symbol, safe="^=.")), accept="application/json")[0])
    meta = body["chart"]["result"][0]["meta"]
    price, previous = float(meta["regularMarketPrice"]), meta.get("previousClose") or meta.get("chartPreviousClose")
    return {"symbol": str(meta.get("symbol") or symbol)[:20], "name": str(meta.get("longName") or meta.get("shortName")
                                                                       or symbol)[:80],
            "price": price, "currency": str(meta.get("currency") or "")[:5],
            "change_percent": round((price - float(previous)) / float(previous) * 100, 2) if previous else None,
            "market_time": int(meta["regularMarketTime"]), "utc_offset_s": int(meta.get("gmtoffset") or 0),
            "zone": str(meta.get("timezone") or "UTC")[:6], "exchange": str(meta.get("exchangeName") or "")[:20],
            "fetched": int(time.time())}


def _as_of(quote, now=None):
    zone = timezone(timedelta(seconds=quote["utc_offset_s"]))
    when = datetime.fromtimestamp(quote["market_time"], zone)
    today = datetime.fromtimestamp(now if now is not None else time.time(), zone).date()
    return when.strftime("%H:%M ") + quote["zone"] + ("" if when.date() == today else when.strftime(" on %d %b %Y"))


def say(quote, now=None):
    money = _SYMBOLS.get(quote["currency"], quote["currency"] + " ")
    change = "" if quote["change_percent"] is None else f", {quote['change_percent']:+.2f}%"
    return f"{quote['name']} ({quote['symbol']}) {money}{quote['price']:,.2f}{change}, as of {_as_of(quote, now)}"


def _quote_tool(arguments, _context):
    query = arguments["query"].strip()
    try:
        symbol = _symbol(query)
        if symbol is None:
            return ToolResult({"error": f"Yahoo Finance knows no listed company or symbol called {query}."},
                              Verification.FAIL)
        quote = _quote(symbol)
    except (OSError, ValueError, KeyError, TypeError, IndexError, ZeroDivisionError) as error:
        cached = _cached(query)
        if cached is None:
            return ToolResult({"error": f"No price is known for {query}: the quote could not be loaded ({error}) "
                                        "and none was saved before."}, Verification.FAIL)
        why = "Offline" if isinstance(error, OSError) and "HTTP" not in str(error) else "Yahoo gave no live price"
        return ToolResult({"query": query, "quote": cached, "stale": True,
                           "reply": f"{why}, last known price: {say(cached)}."}, Verification.PASS)
    try:
        _remember(query, quote)
    except OSError:
        pass   # the live answer is still right; only the offline fallback misses this one
    return ToolResult({"query": query, "quote": quote, "stale": False, "reply": say(quote) + ".",
                       "source": "Yahoo Finance"}, Verification.PASS)


def _validate(arguments):
    if set(arguments) != {"query"} or not isinstance(arguments["query"], str) \
            or not 1 <= len(arguments["query"].strip()) <= 60:
        raise ValueError("Give a stock symbol or company name (1-60 characters).")


def register_finance_tools(registry):
    registry.register(Tool("finance.quote", "Latest stock price for a symbol or company name (e.g. 'RELIANCE.NS', "
        "'TCS', 'Apple'), with the time the price is from; Indian names use NSE. Offline it gives the last known "
        "price and says how old it is.",
        Risk.OBSERVATION, _quote_tool, _validate, reversibility="not_applicable",
        argument_schema={"type": "object", "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 60}},
                         "required": ["query"], "additionalProperties": False},
        success_predicate="price_with_market_time_returned", required_capability="internet.read", network_egress=True))

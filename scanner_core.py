import requests

BASES = ["https://api.binance.com", "https://data-api.binance.vision"]
TIMEFRAMES = ["1h", "1d"]
MIN_VOLUME_USDT = 5_000_000
MAX_SPREAD_PCT = 0.15
DEPTH_PCT = 1.0
MIN_DEPTH_USDT = 50_000
MAX_SYMBOLS = 100
TOP_N = 15
ALERT_MIN_SCORE = 7
ALERT_TOP_N = 5
STABLES = {"USDC", "FDUSD", "TUSD", "BUSD", "DAI", "USDP", "EUR", "EURI", "USD1", "AEUR", "XUSD"}


def get(path, params=None):
    last = "unknown error"
    for base in BASES:
        try:
            r = requests.get(base + path, params=params, timeout=15)
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}"
        except Exception as e:
            last = str(e)
    raise RuntimeError(last)


def ema(values, n):
    a = 2 / (n + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(a * v + (1 - a) * out[-1])
    return out


def rsi(closes, n=14):
    a = 1 / n
    out, au, ad = [50.0], None, None
    for k in range(1, len(closes)):
        d = closes[k] - closes[k - 1]
        u, dn = max(d, 0.0), max(-d, 0.0)
        au = u if au is None else a * u + (1 - a) * au
        ad = dn if ad is None else a * dn + (1 - a) * ad
        out.append(100.0 if ad == 0 else 100 - 100 / (1 + au / ad))
    return out


def analyze(closes, vols):
    if len(closes) < 60:
        return 0, []
    i = len(closes) - 2
    e20, e50 = ema(closes, 20), ema(closes, 50)
    macd = [a - b for a, b in zip(ema(closes, 12), ema(closes, 26))]
    hist = [a - b for a, b in zip(macd, ema(macd, 9))]
    r = rsi(closes)[i]
    base = sum(vols[i - 20:i]) / 20
    vr = vols[i] / base if base > 0 else 0
    score, notes = 0, []
    if e20[i] > e50[i]:
        score += 1
        notes.append("EMA20>EMA50")
    if closes[i] > e20[i]:
        score += 1
        notes.append("price>EMA20")
    if hist[i] > 0 and hist[i] > hist[i - 1]:
        score += 1
        notes.append("MACD rising")
    if 40 <= r <= 65:
        score += 1
        notes.append(f"RSI {r:.0f}")
    elif r < 30:
        notes.append(f"RSI {r:.0f} oversold")
    if vr > 1.5:
        score += 1
        notes.append(f"vol x{vr:.1f}")
    return score, notes


def klines(symbol, interval, limit=120):
    data = get("/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit})
    return [float(k[4]) for k in data], [float(k[5]) for k in data]


def liquidity(symbol):
    ob = get("/api/v3/depth", {"symbol": symbol, "limit": 100})
    bids = [(float(p), float(q)) for p, q in ob["bids"]]
    asks = [(float(p), float(q)) for p, q in ob["asks"]]
    bid, ask = bids[0][0], asks[0][0]
    mid = (bid + ask) / 2
    spread = (ask - bid) / mid * 100
    lo, hi = mid * (1 - DEPTH_PCT / 100), mid * (1 + DEPTH_PCT / 100)
    bd = sum(p * q for p, q in bids if p >= lo)
    ad = sum(p * q for p, q in asks if p <= hi)
    return spread, bd, ad


def scan(progress=None):
    say = progress or (lambda m: None)
    say("Loading market list...")
    tickers = get("/api/v3/ticker/24hr")
    pairs = []
    for t in tickers:
        s = t["symbol"]
        if not s.endswith("USDT") or s[:-4] in STABLES:
            continue
        qv = float(t.get("quoteVolume") or 0)
        if qv >= MIN_VOLUME_USDT:
            pairs.append((s, qv))
    pairs.sort(key=lambda x: x[1], reverse=True)
    pairs = pairs[:MAX_SYMBOLS]

    results = []
    for n, (sym, qv) in enumerate(pairs, 1):
        say(f"Analyzing {n}/{len(pairs)}: {sym}")
        try:
            spread, bd, ad = liquidity(sym)
            if spread > MAX_SPREAD_PCT or min(bd, ad) < MIN_DEPTH_USDT:
                continue
            total, det = 0, {}
            for tf in TIMEFRAMES:
                closes, vols = klines(sym, tf)
                s, notes = analyze(closes, vols)
                total += s
                det[tf] = ", ".join(notes)
            results.append({"symbol": sym, "score": total, "vol": qv, "spread": spread,
                            "bid_depth": bd, "ask_depth": ad, "details": det})
        except Exception:
            continue
    results.sort(key=lambda r: r["score"], reverse=True)
    return results


def format_results(results, top=TOP_N):
    if not results:
        return "No liquid coins passed the filters."
    lines = []
    for r in results[:top]:
        lines.append(f"{r['symbol']}  score {r['score']}/10\n"
                     f"vol24h ${r['vol']/1e6:.1f}M | spread {r['spread']:.3f}%\n"
                     f"depth bid ${r['bid_depth']/1e3:.0f}K / ask ${r['ask_depth']/1e3:.0f}K\n"
                     f"1h: {r['details']['1h']}\n1d: {r['details']['1d']}\n")
    return "\n".join(lines)


def send_telegram(token, chat_id, results):
    if not token or not chat_id:
        return "Telegram not configured"
    picks = [r for r in results if r["score"] >= ALERT_MIN_SCORE][:ALERT_TOP_N]
    if not picks:
        return "No coin reached alert score"
    text = "Binance Scanner (1h + 1d)\n\n" + format_results(picks, ALERT_TOP_N)
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat_id, "text": text}, timeout=15)
        return "Telegram alert sent"
    except Exception as e:
        return f"Telegram error: {e}"

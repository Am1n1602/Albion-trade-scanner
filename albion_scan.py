"""Albion Online (East) trade scanner: city-to-city transport and in-city order flips.

Advisory only: it prints opportunities, you trade by hand (in-game automation breaks ToS).
Fees assume no Premium: 2.5% order setup, 8% sales tax.
"""
import argparse, gzip, json, os, re, sys, time, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

HOST = "https://east.albion-online-data.com"
ITEMS_URL = "https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/formatted/items.txt"
ITEMS_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "items.txt")
BM = "Black Market"  # in Caerleon; sell-only: players can only sell into its buy orders
CITIES = ["Bridgewatch", "Fort Sterling", "Lymhurst", "Martlock", "Thetford", "Caerleon", "Brecilien", BM]
OUTLANDS = {"Arthurs Rest", "Merlyns Rest", "Morganas Rest"}  # black-zone rest towns (--outlands)
RISKY = {"Caerleon", "Brecilien", BM} | OUTLANDS  # reached through red/black zones or mists
SETUP, TAX = 0.025, 0.08


# --- profit math (per unit) ---
def fast_exit(src_sell, dst_buy):      # instant buy at X, instant sell into buy order at Y
    return dst_buy * (1 - TAX) - src_sell

def patient_exit(src_sell, dst_sell):  # instant buy at X, list sell order at Y (undercut 1)
    return (dst_sell - 1) * (1 - TAX - SETUP) - src_sell

def flip(buy, sell):                   # buy order (outbid 1) then sell order (undercut 1), same city
    cost = (buy + 1) * (1 + SETUP)
    return (sell - 1) * (1 - TAX - SETUP) - cost, cost


def get(path, params):
    url = f"{HOST}{path}?{urllib.parse.urlencode(params, safe=',')}"
    req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip", "User-Agent": "albion_scan"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
            time.sleep(0.4)  # stays under 180 req/min
            return json.loads(body)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 2:
                raise
            time.sleep(30)


def load_items():
    if not os.path.exists(ITEMS_CACHE):
        urllib.request.urlretrieve(ITEMS_URL, ITEMS_CACHE)
    ids, names = [], {}
    with open(ITEMS_CACHE, encoding="utf-8") as f:
        for line in f:
            parts = [p.strip() for p in line.split(":", 2)]
            if len(parts) == 3 and re.match(r"T[2-8]_", parts[1]) and "QUESTITEM" not in parts[1]:
                ids.append(parts[1])
                names[parts[1]] = parts[2] + (" ." + parts[1].split("@")[1] if "@" in parts[1] else "")
    return ids, names


def town(name):
    """API names rest towns "<X> Smugglers Network" and returns every den with them; keep only the rest towns."""
    short = name.replace(" Smugglers Network", "")
    return short if short == name or short in OUTLANDS else None


def batches(ids, path_prefix):
    batch, length = [], len(HOST) + len(path_prefix) + 200  # 200 = room for the query string
    for i in ids:
        if batch and length + len(i) + 1 > 4000:
            yield batch
            batch, length = [], len(HOST) + len(path_prefix) + 200
        batch.append(i)
        length += len(i) + 1
    if batch:
        yield batch


def fetch_prices(ids, max_age_h):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - timedelta(hours=max_age_h)
    prices = {}  # (item, quality) -> {city: (sell_min, buy_max, age_h)}
    chunks = list(batches(ids, "/api/v2/stats/prices/.json"))
    for n, chunk in enumerate(chunks, 1):
        print(f"\rprices {n}/{len(chunks)}", end="", file=sys.stderr)
        rows = get(f"/api/v2/stats/prices/{','.join(chunk)}.json",
                   {"locations": ",".join(CITIES), "qualities": "1,2,3,4,5"})
        for r in rows:
            sd = datetime.fromisoformat(r["sell_price_min_date"])
            bd = datetime.fromisoformat(r["buy_price_max_date"])
            s = r["sell_price_min"] if r["sell_price_min"] and sd >= cutoff else 0
            b = r["buy_price_max"] if r["buy_price_max"] and bd >= cutoff else 0
            if s or b:
                age = (now - min(d for d, v in ((sd, s), (bd, b)) if v)).total_seconds() / 3600
                if town(r["city"]):
                    prices.setdefault((r["item_id"], r["quality"]), {})[town(r["city"])] = (s, b, age)
    print(file=sys.stderr)
    return prices


def screen(prices, mode, min_roi):
    out = []
    for (item, q), by_city in prices.items():
        for x, (sx, bx, ax) in by_city.items():
            if x == BM:  # can't buy from or flip on the Black Market
                continue
            if mode in ("flip", "both") and sx and bx:
                p, cost = flip(bx, sx)
                out.append(dict(item=item, q=q, src=x, dst=x, buy=bx + 1, sell=sx - 1, exit="flip",
                                unit=p, cost=cost, roi=p / cost, age=ax, check=sx - 1))
            if mode not in ("transport", "both") or not sx:
                continue
            for y, (sy, by, ay) in by_city.items():
                if y == x:
                    continue
                if by:
                    p = fast_exit(sx, by)
                    out.append(dict(item=item, q=q, src=x, dst=y, buy=sx, sell=by, exit="instant",
                                    unit=p, cost=sx, roi=p / sx, age=max(ax, ay), check=by))
                if sy and y != BM:
                    p = patient_exit(sx, sy)
                    out.append(dict(item=item, q=q, src=x, dst=y, buy=sx, sell=sy - 1, exit="order",
                                    unit=p, cost=sx, roi=p / sx, age=max(ax, ay), check=sy - 1))
    return sorted((o for o in out if o["roi"] >= min_roi), key=lambda o: -o["unit"])


def fetch_history(items):
    since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    hist = {}  # (item, q, city) -> (avg daily volume, avg price)
    for chunk in batches(sorted(items), "/api/v2/stats/history/.json"):
        rows = get(f"/api/v2/stats/history/{','.join(chunk)}.json",
                   {"locations": ",".join(CITIES), "date": since, "time-scale": 24})
        for r in rows:
            d = r["data"]
            if d and town(r["location"]):
                vol = sum(x["item_count"] for x in d)
                hist[(r["item_id"], r["quality"], town(r["location"]))] = (
                    vol / 7, sum(x["avg_price"] * x["item_count"] for x in d) / max(vol, 1))
    return hist


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["transport", "flip", "both"], default="both")
    ap.add_argument("--items", help="comma-separated item IDs (default: all T2-T8)")
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--budget", type=int, default=1_000_000, help="silver per trade")
    ap.add_argument("--max-age", type=float, default=6, help="ignore prices older than N hours")
    ap.add_argument("--min-roi", type=float, default=0.10)
    ap.add_argument("--safe-only", action="store_true", help="skip Caerleon/Black Market/Brecilien/outland routes")
    ap.add_argument("--outlands", action="store_true", help="add Arthur's/Merlyn's/Morgana's Rest (black zone)")
    ap.add_argument("--bm-only", action="store_true", help="only Black Market flips (city -> Black Market)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    if a.bm_only:
        a.mode = "transport"  # Black Market trades are always transport, never in-city flips
    if a.outlands:
        CITIES.append("Merlyns Rest")  # this name returns all smuggler networks ("Arthurs Rest" is unknown to the API)
    ids, names = load_items()
    if a.items:
        ids = a.items.split(",")
    prices = fetch_prices(ids, a.max_age)
    cands = [c for c in screen(prices, a.mode, a.min_roi)
             if not (a.safe_only and {c["src"], c["dst"]} & RISKY) and not (a.bm_only and c["dst"] != BM)]
    hist = fetch_history({c["item"] for c in cands}) if cands else {}

    rows = []
    for c in cands:
        vol, avg = hist.get((c["item"], c["q"], c["dst"]), (0, 0))
        if not vol and c["dst"] in OUTLANDS and c["exit"] == "instant":
            # rest towns have almost no history; a buy order is real silver, but its size isn't in the API
            # ponytail: arbitrary 10-unit cap, check the buy order's quantity in-game
            c["vol"], c["qty"] = 0, min(10, int(a.budget // c["cost"]))
            rows.append(c)
            continue
        if vol < 1 or c["check"] > 1.25 * avg:  # illiquid, or exit price >25% above 7-day average (bait listing)
            continue
        if c["exit"] == "flip" and c["buy"] < 0.5 * avg:  # lowball buy order: won't fill
            continue
        c["vol"], c["qty"] = vol, min(int(vol * 0.10), int(a.budget // c["cost"]))
        if c["qty"] >= 1:
            rows.append(c)
    rows.sort(key=lambda c: -c["unit"] * c["qty"])

    hdr = f"{'item':<34}{'q':>2} {'route':<29}{'buy@':>9}{'sell@':>9} {'exit':<8}{'unit':>8}{'ROI':>6}{'vol/d':>9}{'qty':>7}{'trip':>10}{'age h':>6}"
    print(hdr)
    print("-" * len(hdr))
    for c in rows[:a.top]:
        route = c["src"] if c["src"] == c["dst"] else f"{c['src']}->{c['dst']}"
        risky = " RISKY" if {c["src"], c["dst"]} & RISKY else ""
        print(f"{names.get(c['item'], c['item'])[:33]:<34}{c['q']:>2} {route[:28]:<29}{c['buy']:>9,}{c['sell']:>9,} "
              f"{c['exit']:<8}{c['unit']:>8,.0f}{c['roi']:>6.0%}{c['vol']:>9,.0f}{c['qty']:>7,}{c['unit'] * c['qty']:>10,.0f}{c['age']:>6.1f}{risky}")
    if not rows:
        print("no opportunities: try --max-age 24, lower --min-roi, or refresh markets with the Albion Data Client")


def selftest():
    assert abs(fast_exit(1000, 1100) - 12) < 1e-9          # 1100*0.92 - 1000
    assert fast_exit(1000, 1086) < 0 < fast_exit(1000, 1088)  # break-even ~1.087x
    assert abs(patient_exit(1000, 1201) - 74) < 1e-9       # 1200*0.895 - 1000
    assert patient_exit(1000, 1117) < 0 < patient_exit(1000, 1119)  # break-even ~1.117x
    p, cost = flip(999, 1201)                               # buy@1000, sell@1200
    assert cost == 1025 and abs(p - 49) < 1e-9
    assert flip(999, 1145)[0] < 0 < flip(999, 1147)[0]      # break-even ~1.145x
    print("selftest ok")


if __name__ == "__main__":
    main()

# Albion Trade Scanner

A command-line tool that finds profitable silver trades on the **Albion Online East (Asia) server**. It reads live, crowdsourced market prices and lists, ranked by expected profit:

- **In-city flips:** buy low with a buy order, then sell high with a sell order, in the same city.
- **City-to-city transport:** buy in one city and sell in another.
- **Black Market flips:** buy gear in a city and sell it to the Black Market in Caerleon.

It covers T2–T8 items, every enchantment level (.0–.4) and every quality. Fees are calculated as for a player without Premium.

> **Advisory only.** The scanner prints opportunities; you place every trade by hand in-game. Bots, macros or anything else that automates game input break Albion's Terms of Service and get accounts banned.

---

## Contents
- [Project files](#project-files)
- [How it works](#how-it-works)
- [Setup](#setup)
- [Quick start](#quick-start)
- [Command-line options](#command-line-options)
- [Reading the output](#reading-the-output)
- [Markets covered](#markets-covered)
- [Fees and profit math](#fees-and-profit-math)
- [Built-in filters](#built-in-filters)
- [Trading workflow](#trading-workflow)
- [Limitations](#limitations)
- [Troubleshooting](#troubleshooting)
- [Customising](#customising)

---

## Project files

| File | Purpose |
|---|---|
| `albion_scan.py` | The whole tool: data fetching, profit math, filters and output. Uses only the Python standard library. |
| `items.txt` | List of item IDs and names, downloaded automatically from [ao-data/ao-bin-dumps](https://github.com/ao-data/ao-bin-dumps) on the first run. |
| `README.md` | This file. |

---

## How it works

```
items.txt (T2–T8 IDs)
      │
      ▼
1. Current prices ── /api/v2/stats/prices ── best sell and buy order per item, quality and market
      │                                       (prices older than --max-age are dropped)
      ▼
2. Screen ── every flip and every A→B route ── profit after fees; keep ROI ≥ --min-roi
      │
      ▼
3. 7-day history ── /api/v2/stats/history ── daily volume and average price for each candidate
      │                                       (illiquid, bait-priced and lowball trades are dropped)
      ▼
4. Rank by profit per trip (unit profit × suggested quantity) and print the table
```

- **Data source:** [Albion Online Data Project](https://www.albion-online-data.com/) at `east.albion-online-data.com`. Players upload prices from their own game client, so freshness depends on someone having recently opened that market.
- **API limits:** 180 requests per minute. The scanner waits 0.4 s between calls and retries automatically if it gets rate-limited (HTTP 429). A full scan makes roughly 100–150 requests and takes **about 1.5–2 minutes**.

---

## Setup

1. **Python 3.10 or newer.** No packages to install.
2. **Albion Data Client.** Download it from [albion-online-data.com](https://www.albion-online-data.com/) and keep it running while you play.
   - Every market you open in-game uploads its prices instantly.
   - The East server has few uploaders, so without the client most prices are hours old.
3. Done. `items.txt` downloads itself on the first run.

---

## Quick start

```bash
# Everything: flips and transport, safe and risky routes
python albion_scan.py
```
```bash
# Safe zones only, at most 500k silver per trade
python albion_scan.py --safe-only --budget 500000
```
```bash
# Black Market flips only
python albion_scan.py --bm-only
```
```bash
# Flips inside one city, no travel
python albion_scan.py --mode flip
```
```bash
# Re-check specific items right before trading
python albion_scan.py --items T5_HEAD_PLATE_SET1,T6_MAIN_SWORD
```
```bash
# Add the black-zone outland rest towns
python albion_scan.py --outlands --mode transport
```

---

## Command-line options

| Option | Default | Meaning |
|---|---|---|
| `--mode flip\|transport\|both` | `both` | Which strategies to scan. |
| `--bm-only` | off | Show only Black Market trades (city → Black Market). Sets `--mode transport`. |
| `--outlands` | off | Add Arthur's, Merlyn's and Morgana's Rest (black zone). |
| `--safe-only` | off | Hide every route that touches Caerleon, the Black Market, Brecilien or the outlands. Don't combine with `--bm-only`, or nothing is shown. |
| `--budget N` | `1000000` | Silver you are willing to put into one trade. Limits the suggested quantity. |
| `--max-age H` | `6` | Ignore prices older than H hours. |
| `--min-roi R` | `0.10` | Minimum return on capital (0.10 = 10%). |
| `--top N` | `30` | Number of rows to print. |
| `--items ID,ID,…` | all T2–T8 | Scan only these item IDs. Find IDs in `items.txt`; enchanted items use `@n`, e.g. `T6_MAIN_SWORD@2`. |
| `--selftest` | | Run the built-in checks of the profit formulas and exit. |

---

## Reading the output

```
item                     q route                       buy@    sell@ exit      unit  ROI   vol/d  qty     trip age h
Expert's Knight Boots    1 Bridgewatch->Black Market  4,064   10,428 instant  5,530 136%    479   47  259,899   4.9 RISKY
Pine Planks              1 Bridgewatch                  301      465 flip       108  35% 43,085 3,241 348,894   4.6
```

| Column | Meaning |
|---|---|
| `item` | Item name. A suffix `.1`–`.4` is the enchantment level. |
| `q` | Quality: 1 Normal, 2 Good, 3 Outstanding, 4 Excellent, 5 Masterpiece. |
| `route` | A single city is a flip; `A->B` means carry from A to B. |
| `buy@` | The price you pay. |
| `sell@` | The price you sell at. |
| `exit` | How you sell; see the next table. |
| `unit` | Profit per item after all fees. |
| `ROI` | `unit` divided by the capital per item. |
| `vol/d` | Average units traded per day at the destination over the past 7 days. |
| `qty` | Suggested quantity: at most 10% of daily volume, and no more than your budget allows. |
| `trip` | `unit × qty`, the expected profit for the whole trade. Rows are sorted by this. |
| `age h` | Age, in hours, of the oldest price used. |
| `RISKY` | The route crosses a red or black zone, where you can lose all your cargo (full loot). |

| Exit | What to do |
|---|---|
| `flip` | In that city, place a **buy order** at `buy@`. When it fills, place a **sell order** at `sell@`. |
| `instant` | Buy from sell orders in A, carry the items to B and **sell straight into B's buy orders**. You are paid immediately. |
| `order` | Buy in A, carry the items to B and **list a sell order** at `sell@`. The margin is higher, but you wait for a buyer. |

---

## Markets covered

| Market | Zone | Notes |
|---|---|---|
| Bridgewatch, Fort Sterling, Lymhurst, Martlock, Thetford | Safe (blue/yellow) | The core markets. Each city has refining and crafting bonuses, which push prices apart between cities. |
| Caerleon | Red zone route | `RISKY`. Its market is often priced differently because of the danger of getting there. |
| **Black Market** (in Caerleon) | Red zone route | **Sell only**, through `instant` exits. Players can't buy from it. Quality must match the row's `q`. |
| Brecilien | Mists | `RISKY`. |
| Arthur's, Merlyn's and Morgana's Rest | Black zone | **Only with `--outlands`.** `RISKY`. See the note below. |
| Portal towns, other smuggler's dens | | Not covered: the data project has no usable prices for them. |

**Note on the outland rest towns:**
- Price data is sparse, and there is almost no trade history.
- Trades where a rest town is the *source* (usually outland resources sold in royal cities) are filtered normally.
- Trades *into* a rest town can't be checked against history. Only `instant` exits are shown, capped at 10 units. Check the buy order's size in-game.

---

## Fees and profit math

Fees assumed (no Premium):
- **Setup fee: 2.5%** when you place any buy or sell order.
- **Sales tax: 8%** on every sale, including instant sells and sales to the Black Market.
- **Instant buy** from an existing sell order: no fee.

Notation: `S` is the lowest sell order and `B` the highest buy order in a market.

| Trade | Profit per unit | Profitable when |
|---|---|---|
| `instant` (X → Y) | `0.92 × B_Y − S_X` | `B_Y > 1.087 × S_X` |
| `order` (X → Y) | `0.895 × (S_Y − 1) − S_X` | `S_Y > 1.117 × S_X` |
| `flip` (one city) | `0.895 × (S − 1) − 1.025 × (B + 1)` | `S > 1.145 × B` |

For orders, the scanner assumes you outbid the best buy by 1 silver and undercut the best sell by 1 silver.

`python albion_scan.py --selftest` checks these formulas and their break-even points.

---

## Built-in filters

| Filter | Why |
|---|---|
| Prices older than `--max-age` are dropped | Stale prices are the biggest source of fake opportunities. |
| ROI below `--min-roi` is dropped | Leaves room for the market moving while you travel. |
| Destination has no trades in the past 7 days → dropped | Nobody would buy. |
| Exit price more than 25% above the 7-day average → dropped | Catches bait and troll listings. |
| Flip buy order below 50% of the 7-day average → dropped | A lowball buy order never fills. |
| Quantity capped at 10% of daily volume | Avoids flooding a thin market. |

---

## Trading workflow

1. **Scan.** Start the Albion Data Client, then run the scanner, for example `python albion_scan.py --bm-only`.
2. **Pick a row.** Prefer a low `age h`, a high `vol/d` and a believable ROI. A 300% ROI on 2 units a day is almost always a trap.
3. **Verify in-game.**
   - Open the source market and the destination market. The Data Client uploads fresh prices.
   - Re-run the scan for that item, e.g. `python albion_scan.py --items T5_SHOES_PLATE_SET1`.
   - Check the **order book depth**: are there enough units near `buy@` and `sell@`?
4. **Trade small first.** Buy part of `qty` and confirm the exit works.
5. **Transport safely.**
   - For `RISKY` routes, carry only what you can afford to lose and split large loads across trips.
   - Watch your mount's carrying weight; the scanner doesn't account for it.
6. **Sell.** Use the exit the row specifies.

Good starting points:
- **No risk:** flips in one city with `--mode flip --safe-only`. Refined materials (planks, leather, cloth, metal bars) have the most volume.
- **Most profit:** `--bm-only`. Gear bought in Bridgewatch or Lymhurst and sold to the Black Market often returns 25–100%+, but you must survive the trip into Caerleon.

---

## Limitations

- **Crowdsourced data.** A price is only as fresh as the last time someone opened that market with the Data Client.
- **Only the best price is visible.** The API gives the top of the order book, not how many units sit at that price. Always check depth in-game.
- **Same-quality matching only.** Higher-quality items can often fill lower-quality buy orders, but the scanner doesn't count this.
- **Not modelled:** item weight, mount capacity, travel time, gold–silver timing, crafting and refining margins.
- **East server only.** The host is set in `HOST` at the top of `albion_scan.py`.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `no opportunities` | Use `--max-age 24` or a lower `--min-roi`, or browse a few markets with the Data Client running and scan again. |
| Every row is old (`age h` > 5) | Nobody has uploaded recently. Open the relevant markets yourself with the Data Client running. |
| `HTTP Error 429` | Rate limited. The scanner retries automatically; if it keeps happening, wait a minute. |
| A new item from a patch is missing | Delete `items.txt`; it downloads again on the next run. |
| `--bm-only --safe-only` shows nothing | Expected: the Black Market is inside Caerleon, which is always `RISKY`. |

---

## Customising

All settings are constants at the top of `albion_scan.py`:

| Change | Edit |
|---|---|
| You have **Premium** | `TAX = 0.04` |
| Play on another server | `HOST = "https://west.albion-online-data.com"` or `"https://europe.albion-online-data.com"` |
| Different tiers | The pattern `r"T[2-8]_"` in `load_items()` |
| Bait filter (25%), lowball filter (50%), quantity cap (10%) | The numbers in `main()` |

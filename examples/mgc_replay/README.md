# Try an offline MGC replay

A standalone, dependency-free simulator for **one MGC contract**. Start with
synthetic bars, then import a normalized local CSV. It never calls Databento,
Jev, a broker, or an order endpoint. **Demo results are not Jev performance.**

## Quick start

From the repository root, using Python 3.9+:

```sh
python3 examples/mgc_replay/replay.py --demo --output /tmp/mgc-replay-demo.html
open /tmp/mgc-replay-demo.html
python3 -m unittest discover -s examples/mgc_replay -p 'test_*.py'
```

The self-contained HTML works offline: play/pause, playback speed, scrubber,
close-price and equity charts, and completed trades. Future bars and trades are
hidden until reached by playback; the expandable metadata includes a deliberately
labeled whole-window range, which is hindsight information, not profit.

## Import your completed MGC bars

```sh
python3 examples/mgc_replay/replay.py --csv /absolute/path/mgc.csv \
  --stop-ticks 8 --target-ticks 12 --slippage-ticks 1 --fee-per-side 1.00 \
  --output /tmp/mgc-replay-local.html
```

Required CSV headers and sample format (these two rows illustrate the format,
not enough history for a five-bar signal):

```csv
timestamp,symbol,open,high,low,close,volume
2026-01-05T14:30:00Z,MGCG26,2700.0,2701.0,2699.0,2700.1,100
2026-01-05T14:31:00Z,MGCG26,2700.1,2701.2,2699.8,2700.8,120
```

Use UTC or explicit-offset **bar-open timestamps**, in strictly increasing order,
one consistent interval, completed bars only, and one actual MGC contract (no
cross-roll concatenation). Prices are decimal USD per troy ounce, not Databento
raw integer price units. The loader validates finite positive tick-aligned OHLC,
OHLC bounds, timestamps, volume and single-symbol consistency. It does not verify
exchange provenance, contract identity, trading calendars, interval regularity or
whether bars are genuinely complete. Those remain import responsibilities.

## What the simulation means

| Component | Rule |
|---|---|
| Instrument economics | MGC tick = $0.10/oz; $1 per contract per tick |
| Signal | Deterministic five-bar close momentum, threshold 3 ticks; NOT Jev |
| Timing | Only closed preceding bars enter the signal; execute at next bar open |
| Position | One contract, one position, no pyramiding or signal-based reversal |
| Entry | Market fill at open plus adverse configured slippage |
| Stop | Fixed ticks from fill; adverse gap fills at open, plus adverse slippage |
| Target | Simulated limit at target; no favorable gap improvement |
| Ambiguity | When both stop and target are touched in a bar, stop wins |
| Costs | Explicit fee per side; adverse slippage on entry, stops and final exit |
| End | Force any open position closed; no new entry on final bar |
| Equity | $10,000 starting cash, close-marked unrealized P&L, fees when incurred |

Prices and execution calculations use integer ticks; money uses Decimal. UI JSON
converts final amounts to numbers for display. No randomness or model confidence
is fabricated. The baseline is a plumbing check, **not a recommended strategy**.

OHLC does not reveal intrabar ordering or actual fills. Targets assume full fills;
queue position, spread dynamics, liquidity, latency, exchange halts, margin,
liquidation, funding, contract rolls and capital-based entry restrictions are not
modeled. Default fees are illustrative, not a broker quote. Drawdown is measured
at bar closes, not intrabar. A large whole-window move is not a captured return.
The synthetic fixture cannot establish profitability or predictive power.

## Next integration gates

1. **Databento:** confirm authorized credential source, MGC contract, date range,
   bar interval and an explicit download cost cap. Query metadata/cost estimate
   first; obtain any further required approval before downloading. Normalize
   returned prices and bar timestamps into the CSV contract above, preserve
   original dataset/schema/contract provenance and reject mixed/rolled symbols.
   Nothing in this MVP reads credentials or performs a paid request.
2. **Jev:** verify the current TypeSafe HTTP/SDK contract before implementing an
   opt-in adapter. Send only the closed prefix; retain immutable input, model
   version, response and timing. Enforce a request/token budget and cache replay
   judgments. Missing, failed or invalid judgments must mean WAIT. Model confidence
   is not a win probability and must never bypass risk rules. No live adapter is
   included; live docs were unavailable during this implementation.
3. Compare a frozen Jev policy with this baseline on unseen periods, with identical
   fills/costs. Validate on multiple regimes before any paper/live integration.

Reference entry points: [TypeSafe docs](https://docs.typesafe.ai/),
[Databento docs](https://databento.com/docs), and
[CME Micro Gold specifications](https://www.cmegroup.com/markets/metals/precious/e-micro-gold.contractSpecs.html).

## Verification and rollback

```sh
python3 -m unittest discover -s examples/mgc_replay -p 'test_*.py'
python3 examples/mgc_replay/replay.py --demo --output /tmp/mgc-replay-demo.html
python3 -m compileall -q examples/mgc_replay
```

Tests cover tick precision, input rejection, closed-prefix causality, next-open
execution, long/short stop ambiguity and gaps, fees, limit targets, and forced exit.
Remove only `examples/mgc_replay` to roll back: the main application is untouched.

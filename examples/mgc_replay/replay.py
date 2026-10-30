"""Offline MGC replay: synthetic/local data, deterministic signals, simulated fills."""
import argparse
import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

TICK = Decimal('0.10')
TICK_VALUE = Decimal('1.00')


@dataclass(frozen=True)
class Bar:
    timestamp: str
    symbol: str
    open: int
    high: int
    low: int
    close: int
    volume: int


def ticks(value):
    try:
        price = Decimal(str(value))
        units = price / TICK
        if not price.is_finite() or price <= 0 or units != units.to_integral_value():
            raise ValueError('Prices must be positive finite multiples of 0.10')
        return int(units)
    except (InvalidOperation, OverflowError) as exc:
        raise ValueError('Invalid price') from exc


def load_csv(path):
    """Input times are bar OPEN timestamps; all bars must be completed."""
    bars = []
    previous = None
    with Path(path).open(newline='', encoding='utf-8-sig') as source:
        reader = csv.DictReader(source)
        required = {'timestamp', 'symbol', 'open', 'high', 'low', 'close', 'volume'}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('CSV requires: ' + ', '.join(sorted(required)))
        for line, row in enumerate(reader, 2):
            try:
                moment = datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00'))
                if moment.tzinfo is None or (previous is not None and moment <= previous):
                    raise ValueError('Timestamps must be timezone-aware and strictly increasing')
                symbol = row['symbol'].strip()
                if not symbol or (bars and symbol != bars[0].symbol):
                    raise ValueError('Exactly one nonempty instrument is required')
                values = [ticks(row[key]) for key in ('open', 'high', 'low', 'close')]
                opening, high, low, close = values
                if low > min(opening, close) or high < max(opening, close) or low > high:
                    raise ValueError('Invalid OHLC bounds')
                volume = int(row['volume'])
                if volume < 0:
                    raise ValueError('Volume must be a nonnegative integer')
                bars.append(Bar(moment.astimezone(timezone.utc).isoformat(), symbol,
                                opening, high, low, close, volume))
                previous = moment
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValueError(f'CSV line {line}: {exc}') from exc
    if len(bars) < 2:
        raise ValueError('At least two completed bars are required')
    return bars


def demo_bars():
    """Deliberately synthetic fixture, not historical MGC or a return forecast."""
    start = datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc)
    price = 27000
    bars = []
    for i in range(180):
        drift = (2, -2, 0)[(i // 30) % 3]
        close = price + drift + (i * 7 % 5 - 2)
        bars.append(Bar((start + timedelta(minutes=i)).isoformat(), 'MGC-SYNTHETIC',
                        price, max(price, close) + 3, min(price, close) - 3,
                        close, 50 + i * 13 % 180))
        price = close
    return bars


def baseline(closed):
    """Five-bar momentum; receives only bars closed before execution."""
    if len(closed) < 5:
        return 0
    change = closed[-1].close - closed[-5].close
    return 1 if change >= 3 else -1 if change <= -3 else 0


def simulate(bars, stop_ticks=8, target_ticks=12, slippage_ticks=1,
             fee=Decimal('1.00'), signal=baseline):
    if stop_ticks <= 0 or target_ticks <= 0 or slippage_ticks < 0:
        raise ValueError('Stop/target must be positive; slippage must be nonnegative')
    if not fee.is_finite() or fee < 0:
        raise ValueError('Fee must be finite and nonnegative')
    cash = Decimal('10000.00')
    position = None
    frames, trades = [], []
    for i, bar in enumerate(bars):
        # Immutable prefix excludes the current bar and every future bar.
        decision = signal(tuple(bars[:i]))
        if decision not in (-1, 0, 1):
            raise ValueError('Signal must be -1, 0, or 1')
        if position is None and decision and i < len(bars) - 1:
            entry = bar.open + decision * slippage_ticks
            position = {'side': decision, 'entry': entry, 'entry_index': i,
                        'stop': entry - decision * stop_ticks,
                        'target': entry + decision * target_ticks}
            cash -= fee
        if position:
            p = position
            side = p['side']
            long = side == 1
            stop_gap = bar.open <= p['stop'] if long else bar.open >= p['stop']
            stop_hit = bar.low <= p['stop'] if long else bar.high >= p['stop']
            target_hit = bar.high >= p['target'] if long else bar.low <= p['target']
            exit_price, reason = None, None
            # Conservatively resolve OHLC ambiguity: an adverse stop wins.
            if stop_gap:
                exit_price, reason = bar.open - side * slippage_ticks, 'gap stop'
            elif stop_hit:
                exit_price, reason = p['stop'] - side * slippage_ticks, 'stop'
            elif target_hit:
                exit_price, reason = p['target'], 'target (simulated limit)'
            elif i == len(bars) - 1:
                exit_price, reason = bar.close - side * slippage_ticks, 'end of replay'
            if exit_price is not None:
                gross = Decimal(side * (exit_price - p['entry'])) * TICK_VALUE
                cash += gross - fee
                trades.append({**p, 'exit_index': i, 'exit': exit_price, 'reason': reason,
                               'gross': float(gross), 'net': float(gross - 2 * fee)})
                position = None
        unrealized = Decimal(0) if position is None else Decimal(
            position['side'] * (bar.close - position['entry'])) * TICK_VALUE
        frames.append({'timestamp': bar.timestamp, 'price': bar.close / 10,
                       'equity': float(cash + unrealized), 'signal': decision,
                       'position': 0 if position is None else position['side']})
    return {'frames': frames, 'trades': trades,
            'metadata': {'instrument': bars[0].symbol, 'bars': len(bars),
                         'strategy': 'Deterministic five-bar momentum; NOT Jev',
                         'tick_size': str(TICK), 'tick_value_usd': str(TICK_VALUE),
                         'contracts': 1, 'initial_cash_usd': 10000,
                         'stop_ticks': stop_ticks, 'target_ticks': target_ticks,
                         'slippage_ticks_per_market_fill': slippage_ticks,
                         'fee_usd_per_side': str(fee),
                         'execution': 'Next bar open; stop-first; simulated target limit',
                         'whole_window_range_ticks': max(b.high for b in bars) - min(b.low for b in bars)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--demo', action='store_true')
    source.add_argument('--csv', type=Path)
    parser.add_argument('--output', type=Path, default=Path('mgc-replay.html'))
    parser.add_argument('--stop-ticks', type=int, default=8)
    parser.add_argument('--target-ticks', type=int, default=12)
    parser.add_argument('--slippage-ticks', type=int, default=1)
    parser.add_argument('--fee-per-side', type=Decimal, default=Decimal('1.00'))
    args = parser.parse_args()
    try:
        bars = demo_bars() if args.demo else load_csv(args.csv)
        result = simulate(bars, args.stop_ticks, args.target_ticks,
                          args.slippage_ticks, args.fee_per_side)
        result['metadata']['source'] = 'SYNTHETIC DEMO' if args.demo else 'USER LOCAL CSV (unverified provenance)'
        result['metadata']['source_sha256'] = None if args.demo else hashlib.sha256(args.csv.read_bytes()).hexdigest()
        # Escape HTML-sensitive characters, including malicious CSV instrument names.
        payload = json.dumps(result, allow_nan=False).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
        template = Path(__file__).with_name('template.html').read_text()
        args.output.write_text(template.replace('__REPLAY_DATA__', payload), encoding='utf-8')
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(f'Wrote {args.output.resolve()} — {len(bars)} bars, {len(result["trades"])} simulated trades; NOT Jev results')


if __name__ == '__main__':
    main()

import csv
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from replay import Bar, baseline, demo_bars, load_csv, simulate, ticks


def bar(i, opening=100, high=103, low=97, close=100):
    return Bar(f'2026-01-05T14:{i:02d}:00+00:00', 'MGCG26', opening, high, low, close, 1)


class ReplayTests(unittest.TestCase):
    def test_exact_tick_quantization(self):
        self.assertEqual(ticks('2700.10'), 27001)
        for value in ('2700.11', 'NaN', 'Infinity', '-1', '0'):
            with self.assertRaises(ValueError):
                ticks(value)

    def test_signal_receives_closed_prefix_and_future_cannot_change_past(self):
        bars = demo_bars()
        seen = []

        def spy(prefix):
            seen.append(prefix)
            return baseline(prefix)

        full = simulate(bars, signal=spy)
        for i, prefix in enumerate(seen):
            self.assertEqual(prefix, tuple(bars[:i]))
        changed = bars[:90] + [bar(0, 500, 503, 497, 500)] * 90
        self.assertEqual(full['frames'][:90], simulate(changed)['frames'][:90])

    def test_entry_next_open_not_signal_close(self):
        bars = [bar(0), bar(1, 120, 123, 117, 122), bar(2, 122, 124, 120, 123)]
        result = simulate(bars, signal=lambda prefix: int(len(prefix) == 1))
        trade = result['trades'][0]
        self.assertEqual((trade['entry_index'], trade['entry']), (1, 121))
        self.assertEqual(trade['reason'], 'end of replay')
        self.assertEqual(trade['net'], -1)  # exit 122, entry 121, two $1 fees
        self.assertEqual(result['frames'][-1]['equity'], 9999)

    def test_same_bar_stop_wins_for_both_sides(self):
        for side in (1, -1):
            bars = [bar(0), bar(1, 100, 120, 80, 100), bar(2)]
            result = simulate(bars, signal=lambda prefix: side if len(prefix) == 1 else 0)
            self.assertEqual(result['trades'][0]['reason'], 'stop')
            self.assertEqual(result['trades'][0]['net'], -11)

    def test_adverse_gap_fills_at_open_with_slippage(self):
        for side, gap in ((1, 70), (-1, 130)):
            bars = [bar(0), bar(1), bar(2, gap, gap+2, gap-2, gap)]
            result = simulate(bars, signal=lambda prefix: side if len(prefix) == 1 else 0)
            trade = result['trades'][0]
            self.assertEqual(trade['reason'], 'gap stop')
            self.assertEqual(trade['exit'], gap-side)
            self.assertEqual(trade['net'], -34)

    def test_target_is_fixed_limit_and_fees_are_exact(self):
        bars = [bar(0), bar(1), bar(2, 115, 118, 114, 115)]
        result = simulate(bars, fee=Decimal('0.37'), signal=lambda prefix: int(len(prefix) == 1))
        self.assertEqual(result['trades'][0]['exit'], 113)
        self.assertEqual(result['trades'][0]['net'], 11.26)
        self.assertEqual(result['frames'][-1]['equity'], 10011.26)

    def test_single_position_and_terminal_flat(self):
        result = simulate(demo_bars(), stop_ticks=10000, target_ticks=10000)
        self.assertEqual(len(result['trades']), 1)
        self.assertEqual(result['frames'][-1]['position'], 0)

    def test_invalid_config(self):
        for options in ({'stop_ticks': 0}, {'target_ticks': -1}, {'slippage_ticks': -1},
                        {'fee': Decimal('NaN')}, {'fee': Decimal('-1')}):
            with self.assertRaises(ValueError):
                simulate(demo_bars(), **options)

    def test_csv_validation(self):
        fields = ['timestamp', 'symbol', 'open', 'high', 'low', 'close', 'volume']
        first = ['2026-01-05T14:30:00Z', 'MGCG26', '2700', '2701', '2699', '2700.1', '10']
        second = ['2026-01-05T14:31:00Z', *first[1:]]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bars.csv'

            def write(rows):
                with path.open('w', newline='') as target:
                    writer = csv.writer(target)
                    writer.writerow(fields)
                    writer.writerows(rows)

            write([first, second])
            self.assertEqual(load_csv(path)[0].close, 27001)
            for column, value in ((0, first[0]), (0, '2026-01-05T14:31:00'),
                                  (1, 'MGCJ26'), (2, 'NaN'), (3, '2690'),
                                  (4, '2800'), (5, '2700.11'), (6, '-1')):
                invalid = second.copy()
                invalid[column] = value
                write([first, invalid])
                with self.assertRaises(ValueError):
                    load_csv(path)
            write([first])
            with self.assertRaises(ValueError):
                load_csv(path)


if __name__ == '__main__':
    unittest.main()

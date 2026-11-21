"""Recompute the published synthetic decision references from their as-of evidence."""
import json
import re
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from mara.decision_gold import replay


CASES = Path(__file__).resolve().parents[1] / 'resources' / 'decision-gold'
NUMBER = r'([\d,]+(?:\.\d+)?)'


def case_material(case_id):
    folder = CASES / case_id
    case = replay(json.loads((folder / 'input.json').read_text(encoding='utf-8')))
    gold = json.loads((folder / 'gold.json').read_text(encoding='utf-8'))
    records = {row['series_id']: row['text'] for row in case['records']}
    return case, gold, records


def amounts(text, pattern):
    return [Decimal(value.replace(',', '')) for value in re.findall(pattern, text)]


def trade_shares(text):
    sold = re.search(r'X (\d+)주 매도', text)
    bought = re.search(r'B (\d+)주 매수', text)
    return int(sold[1]) if sold else 0, int(bought[1]) if bought else 0


class GoldArithmeticTests(unittest.TestCase):
    def test_fx_lots_and_cash_buffers(self):
        case, gold, records = case_material('fx-lot-reserve')
        spot, = amounts(records['fx_terms'], NUMBER + '원')
        markup, = amounts(records['fx_terms'], NUMBER + '%')
        rate = spot * (1 + markup / 100)
        lot_price, order_fee = amounts(records['lot_terms'], NUMBER + ' USD')
        extra, = amounts(records['possible_expense'], NUMBER + '원')
        reserve = case['constraints']['minimum_krw_cash']
        minimum, = amounts(case['persona']['objective'], '최소 ' + NUMBER + ' lot')
        self.assertIn(f'{rate:,.0f} KRW/USD', gold['required'][0])

        feasible = []
        for option in case['alternatives']:
            n = int(option.split()[0])
            cost = rate * (n * lot_price + order_fee) if n else 0
            balance = case['holdings']['cash'] - cost
            if n:
                quoted_pair = rf'{n} lot은 {cost:,.0f}원(?: 지출)?·{balance:,.0f}원'
                self.assertRegex(gold['required'][1], quoted_pair)
            if n >= minimum and balance >= reserve:
                feasible.append(n)
                if balance < reserve + extra:
                    self.assertIn(f'{reserve + extra - balance:,.0f}원 부족', gold['required'][2])
                    self.assertIn(f'{balance - reserve:,.0f}원 초과', ' '.join(gold['acceptable']))
        self.assertCountEqual(feasible, [int(row.split()[0]) for row in gold['acceptable']])

    def test_spendable_cash_at_deadline(self):
        case, gold, records = case_material('settlement-window')
        deadline = date.fromisoformat(case['constraints']['deadline'][:10])
        opening = case['holdings']['cash']
        floor = case['constraints']['required_cash_usd']
        self.assertIn('결제되지 않았어요', records['invoice_status'])
        self.assertIn(f'초과분은 {opening - floor:,} USD', gold['required'][0])
        feasible = ['현금 유지'] if opening >= floor else []
        for symbol, series in [('N', 'note_terms'), ('F', 'fund_terms')]:
            terms = records[series]
            price, fee, *payoff = amounts(terms, NUMBER + ' USD')
            month, day = map(int, re.search(r'(\d+)월 (\d+)일', terms).groups())
            first_redemption = date(deadline.year, month, day)
            self.assertGreater(first_redemption, deadline)
            balance = opening - price - fee
            shortfall = floor - balance
            claim = rf'{symbol}1 주문 뒤 (?:기일 현금 )?{balance:,.0f} USD로 {shortfall:,.0f} USD 부족'
            self.assertRegex(gold['required'][0], claim)
            if balance >= floor:
                feasible.append(f'{symbol} 1 lot 매수')
            if payoff:
                gain = payoff[0] - price - fee
                self.assertIn(f'만기 이익 {gain:,.0f} USD', gold['required'][2])
        self.assertEqual(set(case['alternatives']), {'현금 유지', 'N 1 lot 매수', 'F 1 lot 매수'})
        self.assertEqual(feasible, ['현금 유지'])
        self.assertEqual(len(gold['acceptable']), 1)
        self.assertIn(f'현금 {opening:,} USD를 유지', gold['acceptable'][0])

    def test_issuer_cap_after_costs(self):
        case, gold, records = case_material('lookthrough-cap')
        price, = amounts(records['tradable_marks'], NUMBER + ' USD')
        sale_fee, sale_tax, buy_fee = amounts(records['charges'], NUMBER + ' USD')
        upper_pct, = amounts(records['basket_x_range'], '~' + NUMBER + '%')
        holdings = case['holdings']
        limit = Decimal(str(case['constraints']['maximum_issuer_X_fraction']))
        feasible = []
        for option in case['alternatives']:
            sold, bought = trade_shares(option)
            fees = (sale_fee if sold else 0) + sale_tax * sold + (buy_fee if bought else 0)
            cash = holdings['cash'] + (sold - bought) * price - fees
            direct = (holdings['positions']['X'] - sold) * price
            basket = (holdings['positions']['B'] + bought) * price
            nav = direct + basket + cash
            exposure = direct + basket * upper_pct / 100
            fraction = exposure / nav
            if fraction <= limit:
                feasible.append((sold, bought))
                row, = [row for row in gold['acceptable'] if trade_shares(row) == (sold, bought)]
                self.assertIn(f'비용 {fees:,.0f} USD, 순자산 {nav:,.0f} USD, 현금 {cash:,.0f} USD', row)
                self.assertIn(f'{exposure:,.0f}/{nav:,.0f} = {fraction:.4%}', row)
            else:
                required = ' '.join(gold['required'])
                self.assertIn(f'{fraction:.4%}' if sold else f'{fraction:.2%}', required)
                if bought:
                    self.assertIn(f'현금 {cash:,.0f} USD, 순자산 {nav:,.0f} USD', required)
                    scenario_pct, = amounts(required, NUMBER + '% 가정에서는')
                    scenario = (direct + basket * scenario_pct / 100) / nav
                    self.assertIn(f'가정에서는 {scenario:.4%}', required)
        self.assertCountEqual(feasible, [trade_shares(row) for row in gold['acceptable']])

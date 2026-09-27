import pandas as pd

from module_stock.service.stock_realtime_service import StockRealtimeService


class _FakeCollection:
    """模拟pymongo集合：按date排序返回预置快照文档。"""

    def __init__(self, docs):
        self._docs = list(docs)

    def find(self, query, projection):
        return self

    def sort(self, field, direction):
        self._docs = sorted(self._docs, key=lambda doc: doc['date'], reverse=direction == -1)
        return self

    def limit(self, count):
        return self._docs[:count]


class _FakeAdvData:
    def __init__(self, frame):
        self.data = frame


class _FakeQA:
    """模拟QUANTAXIS：返回预置日线DataFrame或None。"""

    def __init__(self, frame):
        self._frame = frame

    def QA_fetch_stock_day_adv(self, code, start, end):
        return None if self._frame is None else _FakeAdvData(self._frame)


def test_extract_record_normalizes_vol_and_date():
    row = {
        'code': '000001',
        'price': 10.5,
        'vol': 12345.0,
        'date': '2026-09-25 15:00:00',
        'open': 10.2,
        'amount': 999,
    }
    record = StockRealtimeService._extract_realtime_record(row, fallback_date='2026-09-27')

    assert record is not None
    assert record['code'] == '000001'
    assert record['date'] == '2026-09-25'
    assert record['price'] == 10.5
    assert record['volume'] == 12345.0
    assert record['amount'] == 999
    assert 'high' not in record  # 缺省字段不写入


def test_extract_record_falls_back_to_close_and_fallback_date():
    row = {'code': '000001', 'close': 9.9}
    record = StockRealtimeService._extract_realtime_record(row, fallback_date='2026-09-27')

    assert record is not None
    assert record['price'] == 9.9
    assert record['date'] == '2026-09-27'


def test_extract_record_returns_none_without_code_or_price():
    assert StockRealtimeService._extract_realtime_record({'price': 1.0}, fallback_date='2026-09-27') is None
    assert StockRealtimeService._extract_realtime_record({'code': '000001'}, fallback_date='2026-09-27') is None


def test_evaluate_signal_rules():
    # MA=10.0，突破阈值1.01：只有严格高于10.1才触发买入
    assert StockRealtimeService._evaluate_signal(10.2, 10.0, 5, 1.01)[0] == '买入'
    assert StockRealtimeService._evaluate_signal(10.1, 10.0, 5, 1.01)[0] == '持有'
    assert StockRealtimeService._evaluate_signal(10.05, 10.0, 5, 1.01)[0] == '持有'
    assert StockRealtimeService._evaluate_signal(9.9, 10.0, 5, 1.01)[0] == '卖出'


def test_analyze_signal_combines_daily_history_with_realtime_close():
    frame = pd.DataFrame(
        {
            'date': ['2026-09-21', '2026-09-22', '2026-09-23', '2026-09-24'],
            'close': [10.0, 10.0, 10.0, 10.0],
        }
    )
    record = {'code': '000001', 'date': '2026-09-25', 'price': 10.2}

    signal = StockRealtimeService._analyze_signal(_FakeQA(frame), _FakeCollection([]), record, 5, 1.01)

    assert signal is not None
    assert signal['signal'] == '买入'
    assert signal['ma'] == 10.04  # (10.0 * 4 + 10.2) / 5


def test_analyze_signal_skips_without_enough_history():
    frame = pd.DataFrame({'date': ['2026-09-24'], 'close': [10.0]})
    record = {'code': '000001', 'date': '2026-09-25', 'price': 10.2}

    signal = StockRealtimeService._analyze_signal(_FakeQA(frame), _FakeCollection([]), record, 5, 1.01)

    assert signal is None


def test_history_uses_realtime_snapshots_as_fallback():
    docs = [
        {'date': '2026-09-24', 'price': 10.0},
        {'date': '2026-09-23', 'price': 10.0},
        {'date': '2026-09-22', 'price': 10.0},
        {'date': '2026-09-21', 'price': 10.0},
    ]

    history = StockRealtimeService._load_history_closes(
        _FakeQA(None), _FakeCollection(docs), '000001', before_date='2026-09-25', limit=4
    )

    assert history == [
        ('2026-09-21', 10.0),
        ('2026-09-22', 10.0),
        ('2026-09-23', 10.0),
        ('2026-09-24', 10.0),
    ]


def test_history_prefers_stock_day_over_realtime_snapshot():
    docs = [{'date': '2026-09-24', 'price': 9.0}]
    frame = pd.DataFrame({'date': ['2026-09-24'], 'close': [10.0]})

    history = StockRealtimeService._load_history_closes(
        _FakeQA(frame), _FakeCollection(docs), '000001', before_date='2026-09-25', limit=4
    )

    assert history == [('2026-09-24', 10.0)]


def test_history_ignores_invalid_prices():
    docs = [{'date': '2026-09-24', 'price': None}]
    frame = pd.DataFrame({'date': ['2026-09-23'], 'close': [float('nan')]})

    history = StockRealtimeService._load_history_closes(
        _FakeQA(frame), _FakeCollection(docs), '000001', before_date='2026-09-25', limit=4
    )

    assert history == []


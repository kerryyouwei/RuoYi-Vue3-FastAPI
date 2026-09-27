from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from exceptions.exception import ServiceException
from module_stock.dao.stock_strategy_dao import StockStrategyDao
from module_stock.entity.vo.stock_strategy_vo import StrategyRunRequest
from module_stock.service.stock_strategy_service import StockStrategyService


@pytest.fixture
def strategy_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / 'strategies'
    directory.mkdir()
    (directory / '__init__.py').write_text('', encoding='utf-8')
    (directory / 'base.py').write_text('', encoding='utf-8')
    (directory / 'mean_revert.py').write_text(
        '"""均值回归说明。"""\nDISPLAY_NAME = "均值回归"\nCATEGORY = "research"\nclass Strategy: pass\n',
        encoding='utf-8',
    )
    (directory / 'broken.py').write_text('def nope(:\n', encoding='utf-8')
    monkeypatch.setattr('module_stock.service.stock_strategy_service._STRATEGY_DIR', directory)
    return directory


@pytest.mark.asyncio
async def test_strategy_scan_only_returns_valid_plugins(strategy_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def empty_summaries(db):
        return {}

    monkeypatch.setattr(StockStrategyDao, 'summaries', empty_summaries)
    strategies = await StockStrategyService.list_strategies(object())

    assert len(strategies) == 1
    assert strategies[0].name == 'mean_revert'
    assert strategies[0].display_name == '均值回归'
    assert strategies[0].category == 'research'


def test_strategy_name_cannot_escape_strategy_directory(strategy_dir: Path) -> None:
    with pytest.raises(ServiceException):
        StockStrategyService._file('../secrets')


def test_run_request_rejects_invalid_code_and_date_range() -> None:
    with pytest.raises(ValidationError):
        StrategyRunRequest(strategyName='ma', code='abc', start='2024-02-01', end='2024-01-01')


def test_strategy_params_are_validated_and_converted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        StockStrategyService,
        '_load_parameters',
        staticmethod(
            lambda strategy_name: [
                {'name': 'period', 'default': 14, 'type': 'int'},
                {'name': 'threshold', 'default': 0.5, 'type': 'float'},
                {'name': 'enabled', 'default': True, 'type': 'bool'},
            ]
        ),
    )

    assert StockStrategyService._coerce_strategy_params(
        'rsi',
        {'period': '20', 'threshold': '0.75', 'enabled': 'false'},
    ) == {'period': 20, 'threshold': 0.75, 'enabled': False}

    with pytest.raises(ServiceException):
        StockStrategyService._coerce_strategy_params('rsi', {'unknown': 1})
    with pytest.raises(ServiceException):
        StockStrategyService._coerce_strategy_params('rsi', {'period': '2.5'})


def test_run_detail_contains_replay_parameters() -> None:
    run = SimpleNamespace(
        run_id='run-1',
        strategy_name='ma',
        code='000001',
        start_date='2024-01-01',
        end_date='2024-02-01',
        initial_cash=100000,
        commission_rate='0.0003',
        stamp_tax_rate='0.001',
        benchmark_code=None,
        strategy_params={'short_period': 5},
        status='success',
        progress=100,
        error_message=None,
        summary={'returnRate': 0.1},
        curves={'dates': []},
        trades=[],
        run_logs=['done'],
        create_time=None,
    )

    detail = StockStrategyService._status_model(run, detail=True)

    assert detail.strategy_name == 'ma'
    assert detail.code == '000001'
    assert detail.strategy_params == {'short_period': 5}
    assert detail.logs == ['done']


def test_non_finite_metrics_are_not_persisted() -> None:
    assert StockStrategyService._finite(None) is None
    assert StockStrategyService._finite(float('nan')) is None
    assert StockStrategyService._finite(float('inf')) is None
    assert StockStrategyService._finite(1.25) == 1.25


# -*- coding: utf-8 -*-
"""Типизированная модель сделки и вспомогательные утилиты.

Единственный источник правды по схеме сделки. Никаких магических индексов:
все поля — именованные атрибуты датакласса. Направление сделки хранится явно
(enum `Direction`), а не выводится эвристикой по SL/TP.
"""
from dataclasses import dataclass
from enum import Enum


class Direction(str, Enum):
    """Направление позиции. str-подкласс, поэтому сравнивается и сериализуется как строка."""
    LONG = "LONG"
    SHORT = "SHORT"


class AssetType(str, Enum):
    """Тип инструмента. STOCK — акция (по умолчанию), FUTURE — фьючерс FORTS."""
    STOCK = "STOCK"
    FUTURE = "FUTURE"


TRADE_SYSTEMS = ['Average MA', 'MACD']


def trade_system_name(value):
    """Человекочитаемое имя торговой системы по её индексу."""
    try:
        idx = int(value or 0)
    except (TypeError, ValueError):
        idx = 0
    if 0 <= idx < len(TRADE_SYSTEMS):
        return TRADE_SYSTEMS[idx]
    return TRADE_SYSTEMS[0]


@dataclass
class Deal:
    """Сделка дневника. Поля соответствуют колонкам таблицы (0–11) + currency/direction."""
    ticker: str = ""
    stock_price: float = 0.0
    amount: float = 0.0
    open_date: str = ""
    init_price: float = 0.0
    take_profit: float = 0.0
    stop_loss: float = 0.0
    trade_system: int = 0
    result: str = ""
    close_date: str = ""
    whats_next: str = ""
    notes: str = ""
    currency: str = ""
    direction: Direction = Direction.LONG
    # Фьючерсы (asset_type=FUTURE): amount = число контрактов, цены — в
    # единицах котировки (для BR — $/bbl), расчёты — в рублях.
    asset_type: AssetType = AssetType.STOCK
    point_value: float = 0.0   # ₽ за 1.0 изменения цены на контракт
    margin: float = 0.0        # ГО на контракт (₽), зафиксированное при входе
    expiry: str = ""           # последний день торгов, ISO

    @property
    def is_open(self) -> bool:
        return not self.close_date

    @property
    def is_future(self) -> bool:
        return self.asset_type == AssetType.FUTURE


def infer_direction(deal) -> Direction:
    """Прежняя эвристика направления по SL/TP. Только для миграции старых данных.

    В новых сделках направление задаётся явно в форме (кнопка Long/Short).
    """
    price = deal.stock_price
    if deal.stop_loss:
        return Direction.SHORT if deal.stop_loss > price else Direction.LONG
    if deal.take_profit:
        return Direction.SHORT if deal.take_profit < price else Direction.LONG
    return Direction.LONG

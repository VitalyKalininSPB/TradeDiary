# -*- coding: utf-8 -*-
"""Риск-план сделки для Simple Mode (чистая математика, без Qt).

Пользователь сам задаёт entry price и stop-loss; модуль считает риск и
проверяет лимиты, ничего не меняя в сделке. Стоп обязателен и должен
соответствовать направлению (LONG: stop < entry; SHORT: stop > entry).

`usd_rate` — конвертация цены сделки в USD: price_usd = price / usd_rate.
Для USD-сделок usd_rate=1.0, для RUB — markets.fetch_usd_rate().
`multiplier` — для фьючерсов point value (₽ за пункт цены на контракт):
цена $/bbl × multiplier = ₽ на контракт, дальше / usd_rate -> USD.
"""
import math

STRONG_RISK_PCT = 2.0  # более сильное предупреждение (>2% equity)

_WARN_NOTIONAL = 'Position exceeds ${:,.0f} maximum per idea.'
_WARN_RISK_LIMIT = ('Risk exceeds your per-trade limit. Reduce quantity or '
                    'review your stop-loss.')
_WARN_RISK_STRONG = ('Risk exceeds {:.0f}% of equity. Reduce quantity or '
                     'review your stop-loss.')
_ERR_STOP_REQUIRED = 'Stop-loss is required.'
_ERR_STOP_LONG = 'Stop-loss must be below entry for Long.'
_ERR_STOP_SHORT = 'Stop-loss must be above entry for Short.'
_ERR_ENTRY = 'Entry price must be positive.'
_ERR_AMOUNT = 'Quantity must be positive.'


def validate_stop(direction, entry, stop):
    """Ошибка по stop-loss или None.

    LONG: stop строго ниже entry; SHORT: stop строго выше entry.
    Отсутствующий/неположительный stop — тоже ошибка.
    """
    if stop is None or stop <= 0:
        return _ERR_STOP_REQUIRED
    if entry is None or entry <= 0:
        return None  # ошибка entry отдельно
    if direction == 'SHORT':
        if stop <= entry:
            return _ERR_STOP_SHORT
    else:
        if stop >= entry:
            return _ERR_STOP_LONG
    return None


def compute_metrics(entry, stop, amount, multiplier=1.0):
    """Базовые риск-метрики сделки (в валюте сделки).

    `multiplier` — стоимость 1.0 изменения цены на единицу количества.
    Для акций 1.0; для фьючерса — point value контракта (₽ за пункт), тогда
    risk_per_share = риск на контракт, position_value = номинал в ₽.
    """
    multiplier = multiplier or 1.0
    rps = abs(entry - stop) * multiplier
    return {
        'risk_per_share': rps,
        'position_value': entry * multiplier * amount,
        'risk_at_stop': rps * amount,
    }


def risk_pct(risk_usd, equity_usd):
    """Риск на стопе в % от total equity (USD). None при невалидном equity."""
    if equity_usd is None or equity_usd <= 0:
        return None
    return risk_usd / equity_usd * 100.0


def quantity_from_notional(desired_usd, entry_price_usd):
    """Количество акций из желаемой суммы позиции (USD): floor(desired/entry)."""
    if desired_usd is None or desired_usd <= 0:
        return None
    if entry_price_usd is None or entry_price_usd <= 0:
        return 0
    return math.floor(desired_usd / entry_price_usd)


def build_risk_plan(entry, stop, amount, direction, total_equity_usd,
                    usd_rate=1.0, desired_notional_usd=None,
                    max_notional_usd=10000.0, max_risk_pct=1.0,
                    multiplier=1.0):
    """Полный риск-план сделки.

    Возвращает dict:
      metrics             — risk_per_share, position_value, risk_at_stop
                            (в валюте сделки);
      position_value_usd  — стоимость позиции в USD;
      risk_at_stop_usd    — риск на стопе в USD;
      risk_pct            — риск в % от equity (None, если equity <= 0);
      quantity_from_notional — floor(desired_notional_usd / entry_usd);
      blockers            — обязательные ошибки (стоп/сторона/количество/цена);
      warnings            — предупреждения лимитов (не блокируют);
      ok                  — True, если blockers пуст.
    """
    stop_err = validate_stop(direction, entry, stop)
    blockers = []
    if stop_err:
        blockers.append(stop_err)
    if entry is None or entry <= 0:
        blockers.append(_ERR_ENTRY)
    if amount is None or amount <= 0:
        blockers.append(_ERR_AMOUNT)

    multiplier = multiplier or 1.0
    price_usd = (entry * multiplier / usd_rate) if (entry and usd_rate) else 0.0
    metrics = compute_metrics(entry or 0.0, stop or 0.0, amount or 0.0,
                              multiplier)
    position_value_usd = amount * price_usd if amount and price_usd else 0.0
    risk_at_stop_usd = metrics['risk_at_stop'] / usd_rate if usd_rate else 0.0

    warnings = []
    if max_notional_usd and position_value_usd > max_notional_usd:
        warnings.append(_WARN_NOTIONAL.format(max_notional_usd))
    pct = risk_pct(risk_at_stop_usd, total_equity_usd)
    if pct is not None:
        if max_risk_pct and pct > max_risk_pct:
            warnings.append(_WARN_RISK_LIMIT)
        if pct > STRONG_RISK_PCT:
            warnings.append(_WARN_RISK_STRONG.format(STRONG_RISK_PCT))

    return {
        'metrics': metrics,
        'position_value_usd': position_value_usd,
        'risk_at_stop_usd': risk_at_stop_usd,
        'risk_pct': pct,
        'quantity_from_notional': quantity_from_notional(
            desired_notional_usd, price_usd),
        'blockers': blockers,
        'warnings': warnings,
        'ok': not blockers,
    }
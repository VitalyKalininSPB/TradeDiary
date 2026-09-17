# -*- coding: utf-8 -*-
"""Глобальные настройки лимитов риска для Simple Mode.

QSettings-синглтон (аналог simple_mode_settings.py): значения помнятся между
запусками, сигнал `changed(bool)` для перерисовки открытых форм.
"""
from PySide6 import QtCore

_ORG = 'TradeDiary'
_APP = 'TradeDiary'
_KEY_NOTIONAL = 'risk/max_notional_per_idea_usd'
_KEY_RISK = 'risk/max_risk_per_trade_pct'
_DEFAULT_NOTIONAL = 10000.0  # максимум на одну идею (USD)
_DEFAULT_RISK = 1.0          # риск на стопе в % от equity


class _RiskSettings(QtCore.QObject):
    changed = QtCore.Signal(bool)

    def __init__(self):
        super().__init__()
        self._settings = None

    def _s(self):
        # Лениво: QSettings корректнее создавать после QApplication.
        if self._settings is None:
            self._settings = QtCore.QSettings(_ORG, _APP)
        return self._settings

    def max_notional_per_idea_usd(self):
        try:
            return float(self._s().value(_KEY_NOTIONAL, _DEFAULT_NOTIONAL,
                                         type=float))
        except (TypeError, ValueError):
            return _DEFAULT_NOTIONAL

    def set_max_notional_per_idea_usd(self, value):
        self._s().setValue(_KEY_NOTIONAL, float(value))
        self.changed.emit(True)

    def max_risk_per_trade_pct(self):
        try:
            return float(self._s().value(_KEY_RISK, _DEFAULT_RISK,
                                         type=float))
        except (TypeError, ValueError):
            return _DEFAULT_RISK

    def set_max_risk_per_trade_pct(self, value):
        self._s().setValue(_KEY_RISK, float(value))
        self.changed.emit(True)


_instance = _RiskSettings()


def max_notional_per_idea_usd():
    return _instance.max_notional_per_idea_usd()


def max_risk_per_trade_pct():
    return _instance.max_risk_per_trade_pct()


def set_max_notional_per_idea_usd(value):
    _instance.set_max_notional_per_idea_usd(value)


def set_max_risk_per_trade_pct(value):
    _instance.set_max_risk_per_trade_pct(value)


def settings_changed():
    return _instance.changed
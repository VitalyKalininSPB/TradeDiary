# -*- coding: utf-8 -*-
"""Глобальная настройка Simple Mode (помнится между запусками).

Простой QObject-синглтон с сигналом `changed(bool)`: переключение в любом
окне мгновенно перерисовывает открытую карточку тикера приложения.
"""
from PySide6 import QtCore

_ORG = 'TradeDiary'
_APP = 'TradeDiary'
_KEY = 'ui/simple_mode'
_DEFAULT = True  # Simple Mode — режим по умолчанию (отлаживаем его первым).


class _SimpleMode(QtCore.QObject):
    changed = QtCore.Signal(bool)

    def __init__(self):
        super().__init__()
        self._settings = None

    def _s(self):
        # Лениво: QSettings корректнее создавать после QApplication.
        if self._settings is None:
            self._settings = QtCore.QSettings(_ORG, _APP)
        return self._settings

    def is_enabled(self):
        return self._s().value(_KEY, _DEFAULT, type=bool)

    def set_enabled(self, on):
        on = bool(on)
        self._s().setValue(_KEY, on)
        self.changed.emit(on)


_instance = _SimpleMode()


def is_simple_enabled():
    return _instance.is_enabled()


def set_simple_enabled(on):
    _instance.set_enabled(on)


def simple_changed():
    return _instance.changed
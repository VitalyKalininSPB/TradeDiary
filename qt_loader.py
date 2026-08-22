# -*- coding: utf-8 -*-
from PySide6.QtCore import QFile, QObject
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QMainWindow, QWidget


def _copy_attrs(source, widget):
    for obj in [source] + source.findChildren(QObject):
        name = obj.objectName()
        if name:
            setattr(widget, name, obj)


def loadUi(filepath, widget):
    ui_file = QFile(filepath)
    ui_file.open(QFile.ReadOnly)
    loader = QUiLoader()
    loaded = loader.load(ui_file)
    ui_file.close()
    if loaded is None:
        raise RuntimeError("Failed to load UI file: %s" % filepath)

    _copy_attrs(loaded, widget)
    widget.setWindowTitle(loaded.windowTitle())

    if isinstance(loaded, QMainWindow):
        widget.setCentralWidget(loaded.centralWidget())
        widget.setMenuBar(loaded.menuBar())
        widget.setStatusBar(loaded.statusBar())
    else:
        if isinstance(widget, QWidget):
            loaded.setParent(widget)
            loaded.move(0, 0)
            widget.resize(loaded.size())

    return loaded

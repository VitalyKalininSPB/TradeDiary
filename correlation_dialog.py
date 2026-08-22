# -*- coding: utf-8 -*-
import numpy as np
import seaborn as sns
import matplotlib
matplotlib.use('QtAgg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from PySide6.QtWidgets import QDialog, QVBoxLayout


class CorrelationDialog(QDialog):
    def __init__(self, tickers, corr_matrix, portfolio_corr, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Correlation Matrix')
        self.resize(720, 680)
        tickers = [str(t) for t in tickers]

        fig = Figure(figsize=(6.5, 6.5), dpi=100)
        fig.patch.set_facecolor('#1e1f24')
        canvas = FigureCanvas(fig)
        ax = fig.add_subplot(111)
        ax.set_facecolor('#1e1f24')
        sns.heatmap(np.asarray(corr_matrix, dtype=float), annot=True, fmt='.2f',
                    cmap='coolwarm', vmin=-1, vmax=1, square=True,
                    xticklabels=tickers, yticklabels=tickers, ax=ax,
                    cbar_kws={'label': 'daily return correlation'})
        ax.set_xticklabels(ax.get_xticklabels(), rotation=45, ha='right')
        ax.set_yticklabels(ax.get_yticklabels(), rotation=0)
        ax.set_title('Pairwise correlation (portfolio: {:.2f})'.format(portfolio_corr),
                     color='#dcdce0')
        ax.tick_params(colors='#dcdce0')
        for side in ('bottom', 'left', 'top', 'right'):
            ax.spines[side].set_color('#43464f')
        cbar = ax.collections[0].colorbar
        cbar.ax.tick_params(colors='#dcdce0')
        if cbar.ax.get_ylabel():
            cbar.ax.set_ylabel(cbar.ax.get_ylabel(), color='#dcdce0')

        layout = QVBoxLayout(self)
        layout.addWidget(canvas)

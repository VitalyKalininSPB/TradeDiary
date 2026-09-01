# -*- coding: utf-8 -*-
import numpy as np
import matplotlib
matplotlib.use('QtAgg')
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

        matrix = np.asarray(corr_matrix, dtype=float)
        im = ax.imshow(matrix, cmap='coolwarm', vmin=-1, vmax=1, aspect='equal')
        ax.set_xticks(range(len(tickers)))
        ax.set_yticks(range(len(tickers)))
        ax.set_xticklabels(tickers, rotation=45, ha='right')
        ax.set_yticklabels(tickers, rotation=0)
        ax.set_title('Pairwise correlation (portfolio: {:.2f})'.format(portfolio_corr),
                     color='#dcdce0')
        ax.tick_params(colors='#dcdce0')

        # Числа в ячейках (annotate вручную, как в seaborn heatmap).
        for i in range(len(tickers)):
            for j in range(len(tickers)):
                val = matrix[i, j]
                if not np.isfinite(val):
                    continue
                # Цвет текста: тёмный на светлых краях, светлый в тёмной середине.
                color = '#111' if abs(val) < 0.55 else '#eee'
                ax.text(j, i, '{:.2f}'.format(val), ha='center', va='center',
                        color=color, fontsize=9)

        cbar = fig.colorbar(im, ax=ax, label='daily return correlation')
        cbar.ax.tick_params(colors='#dcdce0')
        cbar.ax.set_ylabel('daily return correlation', color='#dcdce0')

        layout = QVBoxLayout(self)
        layout.addWidget(canvas)

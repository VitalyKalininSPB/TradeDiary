# AGENTS.md — TradeDiary

Десктоп-приложение для ведения торгового дневника на **PySide6 (Qt6)** + **matplotlib**.
Python 3.12.3. Код на русском/английском (комментарии и строки). Тёмная тема.

## Запуск и проверка

```bash
# venv (обязательно — системный python не содержит PySide6):
source /home/vitaly/Finance/TradeDiary/.qtcreator/Python_3_12_3venv/bin/activate
bash run.sh            # = python main.py

# Быстрая проверка синтаксиса и headless-запуск диалогов:
python -m py_compile main.py macro_dialog.py index_dialog.py
QT_QPA_PLATFORM=offscreen python -c "...диалоги..."   # offscreen, без окна
```

Тест-фреймворка нет. Проверяй компиляцию + сборку диалогов в `QT_QPA_PLATFORM=offscreen`.
**Верни результат** — загрузка главного окна и конструкторы диалогов должны быть
быстрыми (тысячные доли секунды), это контролируется потоками (см. ниже).

## ВАЖНО: данные всегда в фоновом потоке

Это ключевое правило проекта (введено последними коммитами). **Никогда не делай
сеть / чтение БД / пересчёт на UI-потоке.** Сначала рисуем из кэша (мгновенно),
потом досчитываем в фоне.

- Обновлять виджеты можно только на главном потоке → поток **эмитит сигнал**, слот применяет.
- Поток должен завершиться до закрытия окна: в `closeEvent` вызывай `thread.wait(5000)`,
  иначе Qt ругается «QThread: Destroyed while thread is still running».
- Держи ссылку на поток в `self._loader` / `self._macroThread`, чтобы не собрал GC.

Готовые паттерны (переиспользуй, не изобретай заново):

- **`_ChartLoaderThread(QThread)` в `macro_dialog.py`** — универсальный загрузчик серий.
  `items = [(series_id, loader_callable)]`, эмитит `row_loaded(series_id, dates, values, note)`
  на каждую серию и `load_done`. Используется в `MacroDialog` и `IndexDialog`
  (`_on_row_loaded` находит таб по `series_id` и зовёт `tab.set_data`).
- **`_MacroRefreshThread(QThread)` в `main.py`** — для термометра главного окна.
  Эмитит `finished_ok(score, note, regime)` → `_applyMacro`/`_applyRegimeIcon`.
  Первичная отрисовка — из DB-кэшей (`_load_score_cached`, `_load_regime_cached`),
  потом фоновый пересчёт.

## Кэширование (всё в SQLite, с TTL)

Никогда не дёргай сеть при каждом открытии. Два файла БД в корне репо (генерируются).

**`macro_cache.db`** — макро- и индексные данные:
- `macro_series`: FRED-серии (dates,values). `_load_cached`/`_save_cached`, `CACHE_TTL_HOURS=24` (macro_dialog.py).
- `macro_score_cache`: готовый результат термометра (score,note). `_load_score_cached`/`_save_score_cached`, `_SCORE_TTL_HOURS=24`. Входная точка — `compute_macro_score_cached()`.
- `macro_regime`: результат режима bull/bear/neutral для индекса. `_load_regime_cached`/`_save_regime_cached`/`_regime_cached`, `_REGIME_REFRESH_DAYS=2` (index_dialog.py).

**`price_history.db`** — цены бумаг (price_history.py): `price_history` (close) и
`ohlc_history` (свечи). `WINDOW_DAYS=90` (корреляция), `CHART_DAYS=730` (MA-чарт).

**`logos/`** — скачанные логотипы компаний и иконки `bull.png`/`bear.png` (Twemoji).
`logo.py`: `logo_pixmap()`, `placeholder_pixmap()`.

## Терминология (важно для поиска по промтам)

- **«Градусник»** / макро температура / thermometer = `macroProgressBar` +
  `macroRegimeLabel` в главном окне. Шкала `[-10;+10]` risk-on/off из FRED
  (см. `compute_macro_score` в macro_dialog.py). Плюс рядом иконка быка/медведя.
- **Режим рынка** = иконка быка/медведя по «цена vs 200-дневная SMA» (`_regime` в
  index_dialog.py). На главном окне считается по NASDAQ100.
- **«Коза»** = помощник `GoatAssistant` в qualitative_dialog.py (Clippy-аналог с
  пузырём-советом). На главном окне показывается через `_show_advice_goat()` в
  main.py при добавлении сделки. Совет может быть динамическим (см. поздний цикл).
- **Фаза рынка (GDP)** = `_gdp_phase` в macro_dialog.py: классификация цикла по
  росту реального ВВП (GDPC1) — Ранний рост / Спелость / Закат / Рецессия
  (с англ. названиями). Выводится в QLabel внизу таба GDP в MacroDialog.
- **Поздний цикл (late cycle)** = `_late_cycle`/`late_cycle_signal` в macro_dialog.py:
  GPDI (Gross Private Domestic Investment) падает, а потребкредит CCSA держится →
  экономика в позднем цикле, S&P 500 близок к пику. Сигнал считается в фоне в
  `_MacroRefreshThread` (main.py), хранится в `self._late_cycle`, при активации коза
  советует переложиться из Tech/Consumer Discretionary в защиту (Utilities,
  Consumer Staples, Healthcare). В табе GDP это показывается красным QLabel.

## Карта модулей

- `main.py` (1080+ строк): `TradeDiary(QMainWindow)` — главное окно; `TableModel`
  (таблица сделок, 15 колонок, 12/13/14 = кнопки Chart/Candles/Delete); чтение/запись
  `diary.xml`; термометры макро и корреляции; риск-модель `RISK_BY_CORR`; обработчики кнопок.
- `macro_dialog.py`: `compute_macro_score` (весовой `_SCORERS`, `math.tanh`, `_MOMENTUM_DAYS=90`,
  `_YOY_DAYS=365`), `compute_macro_score_cached`, `_IndicatorTab` (общий виджет графика —
  с опцией `show_regime`), `MacroDialog`, `_ChartLoaderThread`.
- `index_dialog.py`: `_regime`/`_regime_icon`/`_regime_cached`, `IndexDialog` (NAS100/SP500/DAX).
  Источники: FRED или Yahoo (DAX). Есть текстовые подсказки про опережение NASDAQ.
- `price_history.py`: бэкфилл истории, корреляция.
- `markets.py`: цены MOEX/WORLD, курс USD, `market_currency`, `convert_usd`.
- `ma_chart_dialog.py`: SMA20/50, «золотые/смертельные кресты».
- `candles_dialog.py`: свечной график по OHLC.
- `correlation_dialog.py`: тепловая карта (seaborn).
- `qualitative_dialog.py`: GoatAssistant (Clippy-аналог), опционально QtWebEngine.
- `deal_history.py`: история сделок. `DealDialog.py`/`EditDealDialog.py`: формы сделки,
  `Deal`, `DirectionType`, `TRADE_SYSTEMS`.

## UI и генерация

- `.ui` файлы (`form.ui`, `deal.ui`, `editdeal.ui`) загружаются в рантайме через
  `qt_loader.loadUi("form.ui", self)` (копирует objectName → атрибуты).
- `ui_*.py` — сгенерированные PySide6-артефакты, обычно в репо.

## Стиль и конвенции

- `matplotlib.use('QtAgg')` + `FigureCanvasQTAgg` в каждом диалоге с графиком.
- Тёмная тема: `_BG='#1e1f24'`, `_TXT='#dcdce0'`, `_GRID='#43464f'`.
- Диалоги немодальные: `dlg.setAttribute(WA_DeleteOnClose)`, регистрируются в
  `self._dialogs_set()` главного окна.
- Не добавляй лишние комментарии; следуй стилю соседних строк.
- **Безопасность**: в `opencode.json` лежит API-ключ DeepSeek — не выводи его в логи/коммиты.

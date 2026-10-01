# AGENTS.md — TradeDiary

Десктоп-приложение для ведения торгового дневника на **PySide6 (Qt6)** + **matplotlib**.
Python 3.12.3. Код на русском/английском (комментарии и строки). Тёмная тема.

## Запуск и проверка

```bash
# venv (обязательно — системный python не содержит PySide6):
source /home/vitaly/Finance/TradeDiary/.qtcreator/Python_3_12_3venv/bin/activate
bash run.sh            # = python main.py

# Быстрая проверка синтаксиса и headless-запуск диалогов:
python -m py_compile main.py macro_dialog.py index_dialog.py pivots.py yield_curve.py
QT_QPA_PLATFORM=offscreen python -c "...диалоги..."   # offscreen, без окна
```

Тест-фреймворка нет. Проверяй компиляцию + сборку диалогов в `QT_QPA_PLATFORM=offscreen`.
**Верни результат** — загрузка главного окна и конструкторы диалогов должны быть
быстрыми (тысячные доли секунды), это контролируется потоками (см. ниже).

**ВАЖНО (со следующей сессии): не запускай авто-захват WebView-тест**
(тест, который через `webView.page().toHtml()`/`runJavaScript` проверяет
автозахват содержимого Quality Assessment из встроенного браузера в
`qualitative_dialog._finalize_report_view`). В offscreen он
ненадёжен: веб-движок не догружает страницу и возвращает пустую/урезанную
разметку, тест зависает или даёт ложный результат. Форматирование тезиса
Quality Assessment в проде сохраняется через ручную кнопку «Quality result»
(rich-text/HTML), а авто-захват — best-effort и не тестируется в offscreen.

## ВАЖНО: НИКОГДА не перезаписывать пользовательскую базу

**Абсолютный запрет.** Пользовательские данные (`diary.db`, `catalyst.db`,
`watchlist.json`, `idea_log.db`, `earnings_cache.db` и прочие файлы в корне репо) —
это живая база пользователя, а не тестовый фикстур. Её потеря недопустима.

- **Никогда не конструируй `TradeDiary()` в тестах/скриптах на реальном репо**:
  `TradeDiary.__init__` читает `diary.db`, а `closeEvent` вызывает `save_diary(...)`,
  полностью перезаписывая базу. Именно так была потеряна база (инцидент 30.09.2026).
- Любой тест, трогающий БД, обязан работать на **временной копии** (tmp-файл /
  `tempfile.TemporaryDirectory`) или с monkeypatch `persistence.DB_PATH` / `XML_PATH`.
  Никогда не пиши в боевые `*.db` из тестов.
- Не запускай скрипты, вызывающие `save()`/`closeEvent`, против рабочей копии.
- Если сомневаешься — сначала сделай резервную копию `cp diary.db /tmp/opencode/`.
- Перед любыми действиями проверь, не запущено ли приложение (`ps aux | grep main.py`):
  работающий процесс держит старую версию данных в памяти и при закрытии перезапишет файл.

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
  Эмитит `finished_ok(score, note, regime, late_cycle)` → `_onMacroRefreshed`
  (слот сохраняет `self._late_cycle`, зовёт `_applyMacro`/`_applyRegimeIcon`).
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
- **Точки перегиба** = `pivot_indices` в pivots.py: значимые развороты тренда
  (сглаживание + смена знака наклона + локальный порог). Возвращает `(index, sign)`:
  `sign=+1` — впадина (ставка начала расти → **SELL S&P, красный**),
  `sign=-1` — пик (ставка начала падать → **BUY S&P, зелёный**).
  В MacroDialog включаются чекбоксом «Точки перегиба» (по умолчанию активен на
  табе Real Interest Rate (Ex-Ante)).
- **Real Interest Rate (Ex-Ante)** = ряд FRED `REAINTRATREARAT10Y` — ожидаемая
  (ex-ante) реальная процентная ставка Кливлендского ФРС (горизонт 10 лет):
  номинальные доходности минус модельная ожидаемая инфляция, без ценовых шоков
  сырья и краткосрочной паники трейдеров. Это сигнальный таб Buy/Sell S&P по
  точкам перегиба; имеет `explainLabel` с пояснением.
- **Катализатор** = событие, способное двинуть акцию (catalyst.py). У события
  есть: дата (напоминание за сутки), оценка 0–5 по **отчётливости** (не по
  благоприятности! направление — отдельное поле +/−/±), описание и **ожидание**
  (какой исход/метрика будет позитивным/негативным сюрпризом).

## Earnings Snapshot (SEC EDGAR)

**Продукт-решение:** компактный блок «Earnings» в RecommendationDialog
(Quantitative Assessment) — ровно по последним 4 отдельным кварталам US-компании:
Revenue, Net income, Diluted EPS, OCF, Capex, FCF, Cash, Total debt, Net debt,
Net margin. Цель — быстрый взгляд «как манал квартальная динамика» без чтения
десяти страниц 10-Q. Данные тянутся из SEC EDGAR (Company Facts API, XBRL),
никогда не из Yahoo/FMP.

- Реализация: `earnings_snapshot.py` — чистый модуль (requests, без Qt/matplotlib):
  `build_earnings_snapshot(ticker)` → результат. `compute_snapshot(ticker, cik,
  facts_doc)` — чистая математика для тестов. Кэш `earnings_cache.db` (kv, TTL 24ч):
  тикер→CIK, факты по CIK, готовые снапшоты. Результат: `{ticker, cik, source,
  as_of_filed_date, status (complete|partial|insufficient|unavailable),
  missing_metrics, warnings, derived_metrics, source_coverage, quarters[]}`.
- Quarter = «отдельный квартал»: прямой XBRL-факт duration 55–150 дн. (Q) —
  `available`; иначе разность накопительных (H1 150–210, 9M 210–330, FY 330–400):
  H1−Q1, 9M−H1, FY−9M — `derived`. Для одного периода приоритет прямого 3M.
  **EPS не вычитается** (не аддитивен): только прямой 3M-факт, иначе `missing`.
- Значения никогда не подставляются нулями: нет данных → `null`/`status=missing`.
  fallback-теги: revenue `SalesRevenueNet`/`Revenues` (важно: `Revenues` =
  total revenues, семантически шире), OCF `...ContinuingOperations`. Capex
  (outflow < 0) нормализуется в положительный; fcf = ocf − capex;
  net_debt = total_debt − cash; net_margin = net_income / revenue.
- Status: `complete` (все базовые метрики из 4), `partial` (есть база ≥ частично,
  но что-то из cash-flow/debt/cash отсутствует или EPS неполон), `insufficient`
  (менее 2 базовых из 4), `unavailable` (тикер не найден в SEC).
- SEC: требуется UA `TradeDiary/1.0 (trading-diary project; contact@example.com)`
  (иначе 403), rate limit ≤10 req/s реализован в модуле. Restated/сравнительные
  факты: дедуп по (start,end) → последний `filed`; `fy` как `min fy` по дате конца.
- UI: `EarningsPanel` + `_EarningsLoaderThread(QThread)` в `recommendation_panel.py`
  (таб «Earnings»). **Поток фоновый, сеть вне UI-потока**; `closeEvent`
  RecommendationDialog → `_earningsPanel.shutdown()` (`thread.wait(5000)`).
  Показывается последний квартал + кнопка «Показать 4 квартала» (таблица).
  При `status != complete` — красное предупреждение «Часть отчётных показателей
  недоступна; вывод ограничен».
- Тесты: `tests/test_earnings_snapshot.py` (unit, синтетические факты) и
  `tests/test_earnings_snapshot_integration.py` (CRC, живой SEC, skip без сети).

## Simple Mode карточки тикера

**Продукт-решение:** ближайший месяц отлаживаем ТОЛЬКО Simple Mode. Full
Analysis и остальные экраны не развиваем, не перегружаем простую карточку.

- Simple Mode = краткая карточка тикера, отвечает ровно на 3 вопроса:
  1) есть ли преимущество относительно peers;
  2) насколько надёжны данные;
  3) что делать дальше.
- Вердикты: **Candidate** / **Watchlist** / **Skip** / **Нет данных**.
  Это эвристики v1, а не «истинная стоимость» (пороги — константы в
  `simple_mode.py`): `rel_eps >= +5` п.п. (преимущество) / `<= -5` п.п. (Skip);
  дороговизна = `pct_pe > 70` ИЛИ `forward_pe >= 1.30 × медианы сектора` (OR);
  дешевизна = `pct_pe < 30` ИЛИ `forward_pe <= 0.77 × медианы` — НЕ повышает
  вердикт без подтверждения (защита от value trap).
- **Candidate** требует подтверждающий слой (сюрпризы по отчётам / тренд
  маржи YoY / ревизии trailing→forward P/E). Без него — Watchlist даже при
  сильном rel_eps (пример CRC: rel_eps +20.5 п.п., но 0 слоёв → Watchlist).
- Карточка использует ТОЛЬКО реально присутствующие поля строки `e`
  (сокращённый row ручного анализа тикера не содержит `net_margin`, `roic`,
  `debt_equity`, `company_score`, `label`, `rank`, `flags`, `contribs`,
  `relative_profitability`, `momentum`). Полный скор/ранг не имитируется.
- **Watchlist-CTA «Открыть Details сейчас»**: для нейтрального Watchlist,
  если есть количественный сигнал, рекомендация открыть существующий Details
  (это НЕ Buy-сигнал). Триггеры в `_watchlist_trigger` (simple_mode.py),
  результат в `card['action']` и `card['watchlist_trigger']`:
  1) **существенное превосходство EPS** `_eps_outperform`: benchmark — медиана
     прямых peers (в модели — `sector_median_eps_growth`), сравнивается один
     период: `feg >= benchmark + 2.0` п.п. И `feg >= benchmark * 1.20`. Если
     benchmark <= 0% — только абсолютный `+2.0` п.п., сигнал помечается
     «низкая/отрицательная база — требуется проверка в Details»;
  2) рост не хуже (`rel >= 0`) И valuation не дороже (не `expensive`);
  3) сильное отчётное подтверждение: `surprise_avg >= +5%` ИЛИ
     `net_margin_yoy >= +3` п.п.;
  4) существенное противоречие (сильный рост + дорого, или рост + отрицательные
     сюрпризы/маржа).
  Если ни один не сработал — прежняя рекомендация (ждать тех. сетап / новый
  отчёт / катализатор). Вердикт Watchlist и UI не меняются (только текст
  action и логика CTA).
- Катализатор: `catalyst.summary_for(ticker)`; 0 событий → «Катализатор: не
  обнаружен системой» (НЕ «нет катализатора»). Число событий и ближайшая
  дата показываются строкой.
- Earnings: только честные даты. Прошедшую дату — «Последний отчёт: … N дн.
  назад»; будущую — «Следующий отчёт: … · до отчёта: N дн.». Дату «~+90 дней»
  НЕ генерируем; нет даты → «ожидается по календарю».
- Реализация: `simple_mode.py` (чистая математика, без Qt) +
  `simple_mode_settings.py` (QSettings-синглтон с сигналом `changed(bool)`),
  виджет `SimpleModePanel` в `recommendation_panel.py`. Режим глобальный:
  тумблер `⚡ Simple Mode` в правом верхнем углу главного окна (main.py),
  применяется ко всей карточке тикера (RecommendationDialog и
  RecommendationPanel), запоминается между запусками.
- **Кнопка «Add to Watchlist»** в RecommendationDialog (экран анализа компании):
  идемпотентное добавление в `watchlist.json` БЕЗ Quant (`watchlist.add`). Если
  тикер уже в watchlist — кнопка disabled с текстом «In Watchlist»
  (`watchlist_contains`). **Quant отмечается отдельной кнопкой «Mark Quant passed»**
  (`_mark_quant_passed`): сохраняет Quant-скор (`set_quant_snapshot`) или ставит
  ручную отметку (`set_quant_passed`), если скор недоступен; после прохождения —
  disabled с текстом «Quant ✓ passed». Так добавление в список и прохождение Quant
  независимы. Ошибка сохранения → понятное сообщение.
  Тесты: `tests/test_watchlist_add.py`.

## Карта модулей

- `main.py` (1080+ строк): `TradeDiary(QMainWindow)` — главное окно; `Position` +
  `TableModel` — таблица показывает **одну строку на тикер** (открытые сделки
  агрегируются: сумма Amount, средневзвешенные init/текущая цена, общий P&L в
  `Result`); 14 колонок, 12/13 = кнопки Chart(candles)/MA (кнопки Delete нет);
  чтение/запись `diary.db`; термометры макро и корреляции; риск-модель
  `RISK_BY_CORR`; обработчики кнопок.
- `macro_dialog.py`: `compute_macro_score` (весовой `_SCORERS`, `math.tanh`, `_MOMENTUM_DAYS=90`,
  `_YOY_DAYS=365`), `compute_macro_score_cached`, `_IndicatorTab` (общий виджет графика —
  с опцией `show_regime`, чекбоксом «Точки перегиба» и `explainLabel`),
  `MacroDialog`, `_ChartLoaderThread`.
- `pivots.py`: **чистый математический модуль** (без Qt/matplotlib, только numpy) — поиск
  значимых точек перегиба тренда `pivot_indices(values, dates, window_frac, range_frac,
  min_gap_days, local_days)`. Возвращает `(index, sign)` (sign: +1 впадина→SELL, -1 пик→BUY).
  Порог — от **локального** размаха (trailing `local_days`), поэтому находит 4–8-месячные
  циклы даже на фоне большого секулярного тренда. Используется в `_IndicatorTab._redraw`
  (macro_dialog.py); любой другой график может импортировать и рисовать маркеры по тем же
  индексам.
- `index_dialog.py`: `_regime`/`_regime_icon`/`_regime_cached`, `IndexDialog` (NAS100/SP500/DAX).
  Источники: FRED или Yahoo (DAX). Есть текстовые подсказки про опережение NASDAQ.
- `price_history.py`: бэкфилл истории, корреляция.
- `markets.py`: цены MOEX/WORLD, курс USD, `market_currency`, `convert_usd`.
- `ma_chart_dialog.py`: SMA20/50, «золотые/смертельные кресты».
- `candles_dialog.py`: свечной график по OHLC.
- `correlation_dialog.py`: тепловая карта (seaborn).
- `qualitative_dialog.py`: GoatAssistant (Clippy-аналог), опционально QtWebEngine.
  На последнем этапе вместо [Finish] — две кнопки **[Qual passed ✓]** /
  **[Qual not passed ✗]** (`_confirm_qual`): «passed» сохраняет Qual-снапшот
  (`_save_qual(force=True)`), «not passed» снимает его (`watchlist.clear_qual`).
  Тесты: `tests/test_qual_flow.py`.
- `catalyst.py` / `catalyst_dialog.py`: катализаторы по тикерам. `catalyst.py` —
  чистое SQLite-хранилище `catalyst.db` (таблица `catalyst_events`: ticker, date,
  score 0-5, direction +/−/±, description, expectation, notified) + `due_events(1)`/
  `mark_notified` для напоминания «за сутки до даты» (и просроченные).
  `catalyst_dialog.py` — менеджер событий тикера (тикер фиксирован, открывается
  из Watchlist): таблица событий, `CatalystEventDialog` (календарь, звёзды,
  ожидание). В watchlist есть таб «Events» (все события, Add/Edit/Delete) и
  колонка Catalyst (живая суммарка из `catalyst.summary_for`, двойной клик —
  редактировать).
- **Напоминания катализаторов**: `_CatalystReminderThread` в main.py — на старте +
  часовой QTimer (реальные `due_events`: напоминание за сутки до даты и
  просроченные). Катализатор-уведомления идут через очередь `_notify_queue` и
  показываются **с красным крестиком подтверждения** (`GoatAssistant(ok_button=True)`,
  сигнал `confirmed`): пользователь явно подтверждает прочтение, только потом
  показывается следующее; пока есть активное/очередное подтверждение, обычные
  уведомления Козы подавляются (`_show_advice_goat`).
- `deal_history.py`: история сделок. `DealDialog.py`/`EditDealDialog.py`: формы сделки,
  `Deal`, `DirectionType`, `TRADE_SYSTEMS`.
- `simple_mode.py`: **чистый модуль** (без Qt) Simple Mode карточки тикера:
  `build_simple_card(e, catalyst)` → вердикт (Candidate/Watchlist/Skip/Нет данных),
  3 факта, качество данных, строка катализатора, earnings, действие (пороги — константы).
- `simple_mode_settings.py`: QSettings-синглтон Simple Mode (`is_simple_enabled`,
  `set_simple_enabled`, сигнал `changed(bool)`); виджет `SimpleModePanel` и интеграция
  Simple/Full в `recommendation_panel.py`, тумблер `⚡ Simple Mode` в main.py (top right).
- **Technical timing** (Simple Mode, Этап 1 + ядро Этапа 2):
  - `technical_timing.py`: **чистый модуль** (без Qt). `compute_indicators(closes)` →
    SMA50/200, RSI(14) Wilder, MACD(12,26,9); `build_timing(ticker, dates, closes,
    direction)` → статус (ready/wait/reassess/no_data) + reason (RU) + мягкий warning.
    Логика: конфликты для long = цена<SMA200 / death cross / MACD bearish (для short —
    зеркально); 0 → **READY**, 1 → **WAIT**, 2–3 → **REASSESS**; RSI/растянутость НЕ
    блокирует (только warning при READY). SQLite `technical_timing.db` (kv, TTL 24ч),
    `load_timing`/`load_any_timing`/`save_timing`/`is_fresh`. `compute_fresh(ticker)` —
    фоновый пересчёт (сеть через `price_history`, вызывать ТОЛЬКО из потока).
  - `technical_timing_dialog.py`: блок «Technical timing — Daily» (Trend/Momentum/
    Status/Reason/Warning) + сигналы `open_trade_plan`/`view_chart`. Внизу — ручное
    напоминание «Проверить: дата» ([Напомнить]/[Снять]) через `tech_reminders`.
  - `tech_reminders.py`: **чистый модуль** (без Qt) — ручные напоминания «проверить
    тех. статус». SQLite `tech_reminders.db` (id, ticker, due_date, note, notified),
    одно напоминание на тикер (заменяет прежнее): `add`/`for_ticker`/`next_for`/
    `remove`/`remove_for_ticker`/`due_events`/`mark_notified`/`reminder_text`.
    Подхватывается `_CatalystReminderThread` (main.py) вместе с катализаторами:
    коза напоминает с подтверждением (красный крестик). Тесты:
    `tests/test_tech_reminders.py` (9, временная БД).
  - `watchlist_dialog.py`: колонка **Tech** (цветной статус), кнопка **Technical**,
    двойной клик по колонке; `_TechnicalTimingThread` (фоновый пересчёт, `cancel()`),
    `_open_trade_plan` (DealDialog с контекстом, Long по умолчанию), `_view_chart`.
    Колонки **Quant ✓ / Qual ✓**: клик по лампочке 💡 снимает прохождение (Yes/No),
    клик по пустой Quant-ячейке отмечает Quant вручную (`watchlist.set_quant_passed`),
    `watchlist.clear_quant`/`clear_qual`. `WatchlistEntryDialog(show_quant=True)` —
    чекбокс «Quant Assessment пройден (вручную)» в Add/Edit. Ручная отметка
    (`entry['quant_passed']`) учитывается гейтом сделки (`watchlist.is_quant_passed`)
    и НЕ требуется для прохождения Qual.
  - `DealDialog.py`: блок «Technical context» (только чтение из БД, без пересчёта) +
    кнопка Chart; `loadTechnicalContext(ticker, hint=False)` — при `hint=True` и мягком
    warning показывает подсказку козы (`_show_goat`). Вызывается из `tickerChanged`
    и `setMode`; кнопка «Open trade plan» в Watchlist зовёт с `hint=True`.
  - Тесты: `tests/test_technical_timing.py` (13, синтетические ряды).
- **Журнал идей** (`idea_log.py` + `idea_log.db`): append-only SQLite-лог каждого
  прогона для будущей аналитики. Схема фиксирована, `PRAGMA user_version = 1`.
  Пишется автоматически при открытии сделки (`main.py: longClicked/shortClicked`,
  `watchlist_dialog._open_trade_plan`) и при закрытии (`main.py: editClicked`).
  **Технический снимок (цена vs SMA200, MACD, RSI, статус) фиксируется на дату
  входа и НЕ пересчитывается** (анти-look-ahead). Фундаментальный снимок — из
  кэша `company_metrics` (sector_quant.db), без сети. Исход: days, final_pnl_pct,
  max_adverse_move_pct. `annotate_idea_by_ticker` дозаполняет вероятность/риск/
  источник; `export_csv` — выгрузка. Данные не удаляются; повторный лог той же
  идеи обновляет снимки, не дублирует. Тесты: `tests/test_idea_log.py` (9).

## S&P 500: инструменты и прокси доходности (важно для backtest-запросов)

Прямого торгуемого инструмента на S&P 500 на MOEX сейчас **нет** (проверено):

- ETF на S&P 500 **делистированы с MOEX после 2022**: `TSPX` (Т-Капитал США 500),
  `AKSP` (Альфа S&P 500), `SBSP` (Первая — Американские акции) — свечи обрываются
  в 2021–2023, marketdata пустая.
- Остались только **iNAV — расчётные цены паёв (не торгуемые)**: `SBSPA`/`SBSPB`
  (Первая — Америк. акции, USD/RUB), `AKSPA` (Альфа), `RCUSA`/`RCUSB` (Райффайзен),
  `TSPVA`/`TSPVB` — свечей у них нет.
- **СПБ Биржа недоступна из этого окружения**: `spbexchange.ru` и `iss.spbex.ru`
  не резолвятся (сетевые таймауты), веб-поиск тоже 403. Не рассчитывать на неё.

Рабочий **прокси для доходности S&P 500 в рублях**:
- индекс S&P 500 — FRED `SP500` (USD, кэшируется в `macro_cache.db` через `_fred`);
- курс USD/RUB — исторические свечи MOEX `USD000UTSTOM`
  (`https://iss.moex.com/iss/engines/currency/markets/selt/boards/CETS/securities/USD000UTSTOM/candles.json`).
- Сигналы BUY/SELL для бэктеста — `compute_mlrci_full()` в `mlrci.py`
  (STRONG BUY = зелёный ▲, STRONG SELL = красный ▼ на табе MLRCI).

Пример расчёта (с 01.01.2024, 500 000 ₽, сигналы MLRCI: BUY 20.02.2024 → SELL 07.08.2026):
S&P 4769.83 → 7709.96 (+61.6%), но USD/RUB 90.7 → 81.78 (−9.8%) → чистая доходность
**+45.7%** (728 717 ₽) против +55.0% у «купи и держи» до 28.08.2026.

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
- **Архитектурные решения и «что НЕ делаем»** — живой журнал
  `ARCHITECTURE_DECISIONS.md` (AGENTS.md — только операционное).
- **Безопасность**: в `opencode.json` лежит API-ключ DeepSeek — не выводи его в логи/коммиты.

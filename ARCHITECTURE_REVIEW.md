# Архитектурный анализ TradeDiary

> Десктоп-приложение для ведения торгового дневника на PySide6 + matplotlib.
> Обзор подготовлен как ревью архитектуры кандидата: что хорошо, что мешает росту,
> где риски и куда двигаться. Дата анализа: 01.09.2026.

---

## TL;DR

**TradeDiary — грамотно устроенный однопользовательский десктоп-инструмент** с
честной дисциплиной по потокам (фоновая загрузка, отрисовка из кэша) и аккуратным
кэшированием. Сильная сторона — чистое выделение вычислительного ядра (`pivots.py`,
функции-калькуляторы в `mlrci.py`, `yield_curve.py`, `macro_dialog.py`).

Главный долг — **модель данных**: сделки хранятся как голые списки строк с
магическими индексами (`row[4]`, `row[12]`), без схемы и типов, а `Deal` объявлен
без `__init__` (поля класса — общий мутабельный стейт). Это порождает дублирование
логики (направление сделки выводится эвристикой в двух местах) и мешает тестам.

Объём: **~7 200 строк Python, 24 модуля**. Слой презентации, прикладной логики,
доменной математики и доступа к данным **физически разделены по файлам**, но
`main.py` (1 093 строки) остаётся «божественным классом» — UI + персистенция +
риск-модель + корреляция + макро в одном месте.

---

## 1. Контекст и назначение

| Аспект | Значение |
|---|---|
| Тип | Однопользовательское десктоп-приложение (offline-first, данные из сети кэшируются) |
| Пользователь | Частный трейдер, дневник сделок + макро-аналитика рынка США |
| Платформа | Linux (окружение разработки), Qt6 десктоп |
| Язык/рантайм | Python 3.12.3 |
| Зависимости | PySide6 6.11, matplotlib 3.11, numpy 2.5, seaborn 0.13, requests 2.34 |
| Внешние данные | FRED, MOEX ISS, Yahoo Finance, Stooq, Parqet, Wikipedia, Google favicons |

Ключевая особенность: приложение **не блокируется сетью** — окно отрисовывается из
SQLite-кэша мгновенно, а свежие данные досчитываются в фоновом потоке.

---

## 2. Технологический стек

| Слой | Технология | Комментарий |
|---|---|---|
| GUI | PySide6 (Qt6), `.ui`-файлы + ручная верстка | два способа построения UI (см. §9) |
| Графики | matplotlib (backend `QtAgg`, `FigureCanvasQTAgg`) | в каждом диалоге с графиком |
| Числа | numpy | векторизация, `pivot_indices`, z-score, SMA |
| Сеть | requests | с таймаутами и `User-Agent` |
| Хранение | SQLite (2 файла) + XML (`diary.xml`) + файлы `logos/` | см. §6 |
| Тепловая карта | seaborn | единственное место использования |
| Веб-рендер | PySide6 QtWebEngine (опционально) | `qualitative_dialog.py` |

---

## 3. Высокоуровневая архитектура

```
                        ┌──────────────────────────────┐
                        │   Presentation (PySide6)     │
                        │  TradeDiary, dialogs, tabs   │
                        └──────────────┬───────────────┘
                                       │ Qt signal/slot (только UI-поток)
                        ┌──────────────▼───────────────┐
                        │   Application logic          │
                        │  риск-модель, корреляция,     │
                        │  макро-градусник, режим рынка │
                        └──────────────┬───────────────┘
                    ┌──────────────────┼────────────────────┐
                    ▼                  ▼                    ▼
        ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
        │  Domain (чистая │  │  Data access     │  │  Внешние данные │
        │  математика)    │  │  (кэш + fetch)   │  │  FRED/MOEX/Yahoo │
        │  pivots, mlrci, │  │  _fred/_cached,  │  │  /Stooq/Parqet/  │
        │  ntfs, scoring  │  │  price_history,  │  │  Wikipedia       │
        │  (numpy, без Qt)│  │  markets, logo   │  │                  │
        └─────────────────┘  └─────────────────┘  └─────────────────┘
                  ▲                    │
                  └── SQLite (macro_cache.db, price_history.db) ──┘
```

Ключевой принцип: **сеть/БД/пересчёт — только в фоновых `QThread`**, результат
возвращается сигналом; UI-поток только применяет готовые значения.

---

## 4. Слои и их границы

### 4.1 Слой представления
- `main.py` — `TradeDiary(QMainWindow)`, `TableModel`, `_MacroRefreshThread`.
- Диалоги: `macro_dialog.py`, `index_dialog.py`, `ma_chart_dialog.py`,
  `candles_dialog.py`, `correlation_dialog.py`, `qualitative_dialog.py`,
  `deal_history.py`, `DealDialog.py`, `EditDealDialog.py`.
- Табы: `yield_curve.py`, `credit_spread.py`, `vix_tab.py`, `mlrci.py` (класс `MlrcTab`).
- Вспомогательные виджеты: `qt_loader.py`, `logo.py` (рендер QPixmap), `ui_*.py` (генерённые).

### 4.2 Прикладная логика
- Риск-модель по корреляции: `RISK_BY_CORR`, `_riskPercentForCorr`, `recalcSlTpClicked` (main.py).
- Портфельная корреляция: `refreshCorrelation`, `_assetWeightsUsd` (main.py) + `build_correlation` (price_history.py).
- Термометр: `compute_macro_score` → `compute_macro_score_cached` (macro_dialog.py).

### 4.3 Доменная математика (без Qt/matplotlib)
- `pivots.py` — **чистый numpy**-модуль поиска точек перегиба `pivot_indices`.
- `mlrci.py` — `compute_net_liquidity`, `compute_mlrci_full`, `compute_signals`, `_zscore`.
- `yield_curve.py` — `compute_ntfs_series`, `_ntfs_value` (бутстрэп кривой).
- `macro_dialog.py` — `compute_macro_score`, `_gdp_phase`, `_late_cycle`, `_SCORERS`.
- `ma_chart_dialog.py` — `analyze_death_crosses`, `_smooth`, `_crosses`.

### 4.4 Доступ к данным и внешние интеграции
- `macro_dialog.py` — `_fred`, `_load_cached`, `_save_cached` (кэш FRED-серий).
- `index_dialog.py` — `_yahoo`, `_regime_cached` (источник DAX + режим рынка).
- `price_history.py` — `ensure_history`, `ensure_ohlc`, `build_correlation`.
- `markets.py` — `fetch_usd_rate`, `fetch_moex_price`, `fetch_world_price`, `market_currency`.
- `logo.py` — многоступенчатый фолбэк логотипов (Parqet → Wikipedia → favicon → letter-avatar).

---

## 5. Карта модулей

| Модуль | LOC | Слой | Ответственность |
|---|---:|---|---|
| `macro_dialog.py` | 1366 | Презентация + домен + данные | Макро-дашборд: скор-модель, `_IndicatorTab`, `_ChartLoaderThread`, кэш FRED |
| `main.py` | 1093 | Презентация + прикладная логика | Главное окно, `TableModel`, риск/корреляция, XML-персистенция |
| `mlrci.py` | 665 | Домен + презентация | Композит MLRCI + вкладка с оверлеем S&P |
| `yield_curve.py` | 509 | Домен + презентация | Кривая доходности + NTFS + STRONG BUY/SELL-правило |
| `ma_chart_dialog.py` | 418 | Презентация + домен | SMA-график, золотые/смертельные кресты, анализ |
| `logo.py` | 387 | Данные + презентация | Логотипы с кэшем на диске/в памяти |
| `qualitative_dialog.py` | 382 | Презентация | Качественная оценка + `GoatAssistant` (Clippy) |
| `price_history.py` | 377 | Данные | Кэш цен/OHLC, корреляция, бэкфилл |
| `index_dialog.py` | 294 | Презентация + данные | Индексы NASDAQ100/SP500/DAX, режим bull/bear |
| `DealDialog.py` | 269 | Презентация + домен | Форма сделки, `Deal`, `DirectionType`, `RiskManager`, `FutureUtil` |
| `credit_spread.py` | 182 | Презентация | BBB-доходность vs 10Y Treasury |
| `vix_tab.py` | 168 | Презентация | VIX с зонами паники |
| `candles_dialog.py` | 161 | Презентация | Свечной график |
| `deal_history.py` | 155 | Презентация | Таблица истории + генерация фейковой истории |
| `markets.py` | 113 | Данные | Цены MOEX/WORLD, курс USD, определение рынка |
| `pivots.py` | 100 | Домен | **Чистая математика** точек перегиба |
| `EditDealDialog.py` | 64 | Презентация | Редактирование сделки |
| `correlation_dialog.py` | 42 | Презентация | Тепловая карта seaborn |
| `qt_loader.py` | 36 | Инфраструктура | `loadUi` + копирование objectName → атрибуты |

`ui_*.py` (generated, ~430 строк суммарно) — сгенерированные PySide6-артефакты.

---

## 6. Модель данных и персистенция

### 6.1 Сделки (слабое место)

```python
# main.py:640 — строка сделки это список из 13 строк:
row = [ticker, stockPrice, stocksAmount, openDate, initPrice,
       takeProfit, stopLoss, tradeSystem, result, closeDate,
       whatsNext, analysisNotes, currency]
```

Проблемы:
- **Магические индексы** по всему коду (`row[0]`, `row[4]`, `row[6]`, `row[12]`) —
  легко «оторвать» при рефакторинге.
- **`Deal` (DealDialog.py:30) объявлен без `__init__`** — все поля являются
  *атрибутами класса*, а не экземпляра. Для скаляров это «работает», но это общий
  мутабельный стейт и анти-паттерн (в т.ч. отмечен в `refac.txt`).
- **Направление сделки не хранится** и выводится эвристикой по SL/TP. Логика
  **продублирована** в `main.py:_dealDirection` (843) и `deal_history.py:_rowMeta` (131).
- Поля перевозятся строками; валидация чисел через `try/except float(...)` в каждом месте.

### 6.2 Хранилище

| Хранилище | Формат | Назначение | TTL |
|---|---|---|---|
| `diary.xml` | XML (ручная запись `minidom`) | баланс + сделки | — |
| `macro_cache.db` | SQLite | FRED-серии, скоринг, режим | 24 ч / 48 ч |
| `price_history.db` | SQLite | цены (close) и OHLC | ~730 дн окно |
| `logos/` | файлы + dict в памяти | логотипы | без TTL |

`diary.xml` — самый «сырой» кусок: ручной `writexml`, нет схемы, нет обработки
ошибок при сохранении, баланс пишется с 13 знаками после запятой. XML избыточен
для таких плоских данных (SQLite или JSON были бы надёжнее и проще).

### 6.3 Кэширование (сильная сторона)

Три уровня кэша с разной семантикой, всё на SQLite с TTL:

1. `macro_series` — сырые FRED-серии (`_load_cached`/`_save_cached`, `CACHE_TTL_HOURS=24`).
2. `macro_score_cache` — готовый результат градусника (`_SCORE_TTL_HOURS=24`).
3. `macro_regime` — bull/bear для индекса (`_REGIME_REFRESH_DAYS=2`).
4. `price_history` / `ohlc_history` — цены бумаг (`WINDOW_DAYS=90`, `CHART_DAYS=730`).
5. `logos/` — логотипы на диске + `_cached` dict с `threading.Lock`.

Паттерн «прочитал свежий кэш → мгновенно отрисовал → фоново обновил» реализован
последовательно (`compute_macro_score_cached`, `_regime_cached`). Это прямое
воплощение правила из `AGENTS.md` «данные всегда в фоновом потоке».

---

## 7. Модель потоков и конкурентность

### 7.1 Паттерны (образцовые для PySide6)

```python
class _ChartLoaderThread(QThread):          # macro_dialog.py:1060
    row_loaded = Signal(object, object, object, str)   # (series_id, dates, values, note)
    load_done  = Signal()
    def run(self):
        for series_id, loader in self._items:  # items = [(id, callable)]
            try:    dates, values = loader(series_id)
            except: dates, values, note = [], [], 'Error: ...'
            self.row_loaded.emit(series_id, dates, values, note)
        self.load_done.emit()
```

- **`_ChartLoaderThread`** — универсальный загрузчик серий; используется в
  `MacroDialog._load_all` и `IndexDialog._load_all`. Слот `_on_row_loaded`
  маршрутизирует по `series_id` в нужный таб.
- **`_MacroRefreshThread`** (main.py:192) — пересчёт градусника + режима NASDAQ;
  первичная отрисовка из кэша, затем фоновый пересчёт.
- **Жизненный цикл потока**: в каждом `closeEvent` вызывается `thread.wait(5000)`,
  ссылка на поток хранится в `self._loader`/`self._macroThread` (защита от GC).

### 7.2 Нарушения правила «сеть только в фоне»

Несколько путей всё же ходят в сеть на UI-потоке (главное окно/диалоги):

1. `main.py:__init__` → `setupCorrelation()` → `ensure_history()` → сеть.
2. `main.py:recalcBalance()` → `markets.fetch_usd_rate()` → сеть.
3. `DealDialog.tickerChanged()` → `market_currency()` → два сетевых запроса
   (частично сглажено debounce 700 мс).
4. `logo_pixmap()` в `DealDialog.setLogo()` — сеть на UI-потоке.

Это не «блокирующие» загрузки уровня окна, но противоречат заявленному принципу
и при недоступной сети дают подтормаживание. Для ревью важно это зафиксировать.

### 7.3 Кэш курса USD

`markets._fetch_usd_rate_cached` (markets.py:14) мемоизирует курс через атрибут
функции **без инвалидации и без блокировки** — курс берётся один раз за сессию.
Для внутридневного дневника это упрощение, но курс может устареть в течение долгой сессии.

---

## 8. Доменная логика (качество реализации)

### 8.1 `pivots.py` — эталонный модуль
Чистый numpy без Qt/matplotlib. `pivot_indices` использует центрированную MA,
смену знака наклона, **локальный** размах (trailing-окно) вместо глобального и
календарный минимум-гэп — благодаря чему находит 4–8-месячные циклы на фоне
векового тренда. Отлично документирован, пригоден к переиспользованию любым графиком.

### 8.2 Скор-модель градусника (`compute_macro_score`)
Взвешенная сумма субоценок (веса `_SCORERS` суммируются в 1), нормировка через
`math.tanh`, два горизонта (`_MOMENTUM_DAYS=90`, `_YOY_DAYS=365`). При пропуске
серии — нормализация на сумму фактически использованных весов (корректно).
Каждая серия обёрнута в `try/except` (падение одной не валит весь скоринг).

### 8.3 Составные индикаторы
- **MLRCI** (mlrci.py) — композит из 5 опережающих индикаторов, z-score на
  trailing-окне 5 лет, взвешивание с флипом знака, сжатие `tanh` в [-100;+100].
  Сигналы STRONG BUY/SELL — конъюнкция «≥3 из 5» условий (намеренно, вместо жёсткого
  AND, что подтверждено бэктестом в комментарии).
- **NTFS** (yield_curve.py) — бутстрэп spot-ставок из par-кривой и форвардная ставка
  3M через 18 мес; честная финансовая математика.
- **Режим рынка** (index_dialog.py `_regime`) — цена vs 200-SMA с зоной
  нечувствительности ±2% (анти-флаппинг).
- **Поздний цикл** (`_late_cycle`) — GPDI падает, потребкредит держится.

Доменная логика **не связана с UI** и уже хорошо вынесена в функции — это главный
аргумент за то, что код можно тестировать и развивать.

---

## 9. UI-архитектура и паттерны

### 9.1 Два способа построения UI (несогласованность)
1. **`.ui` + `qt_loader.loadUi`** — `form.ui`, `deal.ui`, `editdeal.ui`
   (`qt_loader` копирует `objectName` → атрибуты виджета).
2. **Программная верстка** — `macro_dialog`, `index_dialog`, все табы
   (`_YieldCurveTab`, `MlrcTab`, `VixTab`, `CreditSpreadTab`), `qualitative_dialog`.

Оба способа соседствуют без явного правила. Для новых графиков выбран
программный путь (удобнее компоновка + чекбоксы/комбо), но единой конвенции нет.

### 9.2 Хорошие паттерны
- **Немодальные диалоги**: `WA_DeleteOnClose` + регистрация в `self._open_dialogs`
  (множество), чтобы несколько графиков были открыты одновременно; очистка по `destroyed`.
- **`TableModel` (QAbstractTableModel)** — кнопки Chart/Candles/Delete как
  `setIndexWidget` + `_rebuildChartButtons`, пересбор по `modelReset`.
- **Кастомные виджеты** `StarRating`, `StageScale`, `GoatAssistant` — на `QPainter`,
  аккуратно, без лишних ассетов (кроме картинок).
- **Тёмная тема** единым `DARK_QSS` + константы `_BG`/`_TXT`/`_GRID`, согласованные цвета.

### 9.3 Дублирование в навигации графиков
Блоки zoom/pan/скролл/выделение интервала (`_sync_scrollbar`, `_on_scrollbar`,
`_on_scroll`, `_on_press`, `_on_motion`, `_on_release`, `_on_double`, `_fit_y`,
`_set_band`, `_axis`) **почти дословно скопированы** между `_IndicatorTab`
(macro_dialog.py) и `MlrcTab` (mlrci.py) — ~120 строк дубля. Это кандидат на
вынос в общий базовый класс виджета-графика.

---

## 10. Внешние источники данных

| Источник | Модуль | Что берётся |
|---|---|---|
| FRED (fredgraph.csv) | `macro_dialog._fetch_fred` | макро, ставки, спреды, индексы, VIX |
| MOEX ISS | `markets`, `price_history` | котировки, свечи, курс USD/RUB |
| Yahoo Finance | `markets`, `price_history`, `index_dialog` | мировые цены, DAX, история |
| Stooq | `markets`, `price_history` | фолбэк для US-истории |
| Parqet / Wikipedia / Google favicons | `logo.py` | логотипы (каскадный фолбэк) |

Все вызовы с таймаутами, `raise_for_status`, `try/except`; ошибки сети не роняют UI.
Есть примечания в коде о недоступных источниках (S&P-ETF на MOEX делистированы,
SPB-биржа недоступна, ISM закрыт) — ценно, что ограничения зафиксированы, а не «заметены».

---

## 11. Сильные стороны

1. **Дисциплина потоков** — фоновая загрузка + отрисовка из кэша, корректный
   `wait()` при закрытии, ссылки на потоки хранятся. Это нетривиально и сделано чисто.
2. **Кэширование с TTL** на всех уровнях, включая кэш готового результата скоринга.
3. **Чистое доменное ядро** — `pivots.py` и функции-калькуляторы без Qt-зависимостей;
   логику можно тестировать без GUI.
4. **Защитное программирование** — каждая серия/запрос в `try/except`, падение данных
   не роняет UI; UI всегда показывает заглушку вместо краша.
5. **Отличная документация** — `AGENTS.md` (терминология, правила, карта модулей),
   docstring'и у ключевых функций, осмысленные комментарии про *почему*.
6. **Переиспользуемые паттерны** — `_ChartLoaderThread` (универсальный загрузчик),
   `_IndicatorTab` (общий виджет графика с опциями `show_regime`/`show_phase`/`show_pivots`).
7. **Зафиксированные решения и ограничения** — про S&P-прокси, недоступные источники,
   пороги сигналов (с бэктест-обоснованием).

---

## 12. Слабые стороны и технический долг

| # | Проблема | Локация | Severity |
|---|---|---|---|
| 1 | Модель сделки — список строк, магические индексы | `main.py` повсеместно | **High** |
| 2 | `Deal` без `__init__` (поля класса = общий стейт) | `DealDialog.py:30` | **High** |
| 3 | `main.py` — «божественный класс» (UI+данные+риск+корреляция+макро) | `main.py` (1093) | **High** |
| 4 | Дублирование `_dealDirection` / навигация графиков | `main.py`+`deal_history.py`; `_IndicatorTab`+`MlrcTab` | Medium |
| 5 | Нет тестов и CI | весь проект | **High** |
| 6 | Сеть на UI-потоке в ряде путей | `setupCorrelation`, `tickerChanged`, `recalcBalance`, `setLogo` | Medium |
| 7 | Ручная XML-персистенция без схемы и обработки ошибок | `main.py:closeEvent` | Medium |
| 8 | `print()`-отладка вместо логгера | повсеместно | Low |
| 9 | Захардкоженные абсолютные пути | `GOAT_IMAGE` (`/home/vitaly/...`), `clippy.png` | Medium |
| 10 | Мёртвый/заглушечный код | `updatePricesClicked` (URL 2023 г.), `quantitiveAssessmentClicked`, `generate_fake_history`, `deal.cpp`/`deal.h`/`data.csv` | Low |
| 11 | Мемоизация курса USD без инвалидации/лока | `markets._fetch_usd_rate_cached` | Low |
| 12 | Фьючерсы с хардкодом `pointPrice`, `TODO` | `DealDialog.FutureUtil` | Low |
| 13 | Устаревшие вызовы (`utcfromtimestamp` — deprecated) | `price_history.py` | Low |
| 14 | seaborn ради одной тепловой карты (тяжёлая зависимость) | `correlation_dialog.py` | Low |
| 15 | Смешение рус/англ в идентификаторах и UI | повсеместно | Info |

---

## 13. Риски

- **Целостность данных**: сохранение `diary.xml` без атомарной записи и без обработки
  сбоя — при падении во время записи данные можно потерять.
- **Гонки/свежесть**: мемоизированный курс и логотип-кэш без инвалидации.
- **Расширяемость**: добавление поля в сделку = правка магических индексов в ~10 местах
  (высокий риск «оторвать» при росте).
- **Сопровождаемость**: отсутствие тестов при нетривиальной доменной математике
  (пивоты, NTFS, MLRCI) — регрессии не будут пойманы.
- **Секреты**: `opencode.json` с API-ключом лежит в репо (в `.gitignore`, но файл есть).

---

## 14. Что можно улучшить — конкретные предложения

Ниже — не «хотелки», а готовые к применению рефакторинги. Каждый пункт описан
по схеме: **проблема → как улучшить → конкретика/код → что это даёт**.

### 14.1 Модель сделки: `@dataclass` с явным направлением

**Проблема.** Сделка — список строк `self.data` с магическими индексами, направление
выводится эвристикой в двух файлах.

**Как улучшить.** Завести типизированный датакласс с явным `direction` и хранить
его везде вместо списка.

```python
# deals.py (новый модуль)
from dataclasses import dataclass, field
from enum import Enum

class Direction(Enum):
    LONG = "LONG"
    SHORT = "SHORT"

@dataclass
class Deal:
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
    direction: Direction = Direction.LONG   # явное поле, а не эвристика
```

**Что даёт:** убирает ~10 мест с `row[idx]`, `_dealDirection`/`_rowMeta` исчезают,
`TableModel.data()` получает имена вместо индексов. Направление задаётся в
`DealDialog` (кнопка Long/Short), а не угадывается по SL/TP.

### 14.2 Хранение: XML → SQLite (или JSON с атомарной записью)

**Проблема.** `closeEvent` пишет XML руками, без атомарности и обработки сбоя.

**Как улучшить.** Минимальная замена без смены парадигмы — атомарная запись JSON:

```python
import json, os, tempfile

def save_diary(path, payload):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)          # атомарная замена
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
```

**Лучше по-взрослому** — единый `diary.db` (SQLite): таблица `deals` с колонками,
`balance` отдельной строкой. Тогда уходят `minidom`-парсинг и ручная сериализация,
а запись в БД можно делать по одной строке (без переписывания всего файла).

**Что даёт:** устойчивость к падению во время сохранения, лёгкие миграции схемы,
проще читать/фильтровать историю.

### 14.3 Развязка `main.py` (божественный класс)

**Проблема.** 1093 строки: UI + XML + риск + корреляция + макро + курс валют.

**Как улучшить.** Вынести в модуль `services.py` (или пакет `services/`):

```python
# services.py
class RiskService:
    def risk_pct(self, portfolio_corr): ...      # из RISK_BY_CORR
    def recalc_sl_tp(self, deals, equity, corr): ...

class CorrelationService:
    def build(self, open_tickers): ...           # из refreshCorrelation

class PersistenceService:
    def load(self) -> list[Deal]: ...
    def save(self, deals, balance): ...
```

`TradeDiary` оставить только: сборку виджетов, слоты, запуск потоков и вызовы
сервисов. Кнопки становятся однострочными: `self.deals = self._persistence.load()`.

**Что даёт:** `main.py` ~300–400 строк; сервисы тестируются без GUI; понятная
зона ответственности для новых разработчиков.

### 14.4 Тесты на чистое ядро (быстрый выигрыш)

**Проблема.** Нет ни одного теста; доменная математика (пивоты, NTFS, MLRCI)
нетривиальна и уже готова к тестам — она без Qt.

**Как улучшить.** `pytest` + пара фикстур с синтетическими рядами:

```python
# tests/test_pivots.py
import numpy as np
from pivots import pivot_indices

def test_finds_peak_and_trough():
    x = np.linspace(0, 4 * np.pi, 500)
    values = np.sin(x)                 # известные пик/впадина
    pts = pivot_indices(values, min_points=8)
    signs = [s for _, s in pts]
    assert -1 in signs and +1 in signs  # есть и пик, и впадина
```

Аналогично: `compute_ntfs_series` (на искусственной кривой), `compute_mlrci`
(стабильность z-score), `_regime` (границы ±2%), `analyze_death_crosses` (известный
ряд с падением после креста), `_gdp_phase` (4 режима).

**Что даёт:** регрессионная сетка на самую ценную логику; далее можно в CI
(`pytest` + headless-сборка диалогов в `QT_QPA_PLATFORM=offscreen`, как уже описано
в `AGENTS.md`).

### 14.5 Убрать дублирование навигации графиков

**Проблема.** ~120 строк zoom/pan/скролл/выделение почти дословно повторены в
`_IndicatorTab` и `MlrcTab`.

**Как улучшить.** Общий базовый класс виджета-графика:

```python
# chart_widget.py
class BaseChartTab(QWidget):
    """Общая навигация: скроллбар, зум колесом, выделение интервала, двойной клик."""
    def _sync_scrollbar(self): ...
    def _on_scroll(self, ev): ...
    def _on_press / _on_motion / _on_release / _on_double(self, ev): ...
    def _fit_y(self, ax): ...
    def _set_band(self, a, b): ...
    def _axis(self): ...
```

`_IndicatorTab` и `MlrcTab` наследуют `BaseChartTab` и реализуют только
`_redraw()` + специфичные данные. `_YieldCurveTab`/`VixTab`/`CreditSpreadTab` могут
тоже переехать позже.

**Что даёт:** один источник правды для навигации; багфикс в одном месте; меньше
кода на сопровождение.

### 14.6 Сеть с UI-потока — в фон

**Проблема.** `setupCorrelation`/`ensure_history`, `recalcBalance`/`fetch_usd_rate`,
`tickerChanged`/`market_currency`, `setLogo` — сеть на главном потоке.

**Как улучшить.**
- **Курс USD** — загружать в `_MacroRefreshThread` (он уже фоновый) и кэшировать с
  TTL в БД или инвалидировать по времени.
- **`ensure_history` при открытии** — сделать фоновым `QThread` (по образцу
  `_ChartLoaderThread`), результат приходит сигналом и обновляет корреляцию.
- **`tickerChanged`** — уже есть debounce 700 мс; оставить debounce, но запрос
  цены/рынка выполнять в `QThread` или через `QNetworkAccessManager` (асинхронно).
- **Логотипы** — `logo_pixmap` уже умеет фолбэк; для интерактивности отдавать
  placeholder сразу, а сетевой результат подставлять по сигналу.

**Что даёт:** соответствие заявленному в `AGENTS.md` правилу «данные всегда в фоне»,
никаких подвисаний при недоступной сети.

### 14.7 Курс USD: убрать «вечную» мемоизацию

```python
# было (markets.py): функция запоминает курс навсегда
_fetch_usd_rate_cached.rate = ...

# стало: кэш с TTL + блокировкой
import threading, time
_rate, _rate_at, _lock = None, 0.0, threading.Lock()

def fetch_usd_rate(ttl=300):
    global _rate, _rate_at
    with _lock:
        if _rate and time.time() - _rate_at < ttl:
            return _rate
    try:
        r = requests.get(..., timeout=5); r.raise_for_status()
        with _lock:
            _rate, _rate_at = float(...), time.time()
        return _rate
    except Exception:
        return _rate   # отдаём последнее известное
```

**Что даёт:** курс не устаревает за сессию, конкурентные вызовы безопасны.

### 14.8 Логирование вместо `print`

**Проблема.** Десятки `print('TickerChanged')`, `print(deal)` замусоривают stdout
и не несут уровней/источника.

```python
import logging
log = logging.getLogger(__name__)

log.debug("TickerChanged %s", ticker)
log.warning("Yahoo failed for %s: %s", ticker, e)
```

**Что даёт:** фильтрация по уровню, `logging.basicConfig` в `main`, готовность к
записи в файл, отсутствие шума в проде.

### 14.9 Гигиена репозитория

- Удалить `deal.cpp`, `deal.h`, `data.csv` (пустой), `refac.txt` (черновик) — либо
  перенести заметки в `docs/`.
- Убрать `updatePricesClicked` с захардкоженным URL `..._2023-02-15.xml.zip` или
  переписать на актуальный ISS-эндпоинт с выбором даты.
- `GOAT_IMAGE = '/home/vitaly/Downloads/advice_goat.png'` → относительный путь в
  `assets/` с фолбэком (как в `OfficeAssistant` с `clippy.png`).
- Проверить, что `opencode.json` реально в `.gitignore` (он там) и не попал в историю;
  при необходимости `git filter-repo` для вычистки ключа из истории.

### 14.10 Тайпхинты и линтер

- Добавить `ruff` (или `flake8`) + `mypy --strict` (постепенно).
- Начать с доменного ядра (`pivots.py`, `mlrci.py`, `yield_curve.py`, `price_history.py`)
  — там типы дают максимальный эффект.
- `price_history.py` использует deprecated `datetime.utcfromtimestamp` → заменить на
  `datetime.fromtimestamp(ts, tz=datetime.UTC)` (как уже сделано в `index_dialog.py`).

### 14.11 Зависимости

- `seaborn` тянется ради одной `heatmap` в `correlation_dialog.py` (42 строки).
  Тепловую карту можно нарисовать на чистом matplotlib (`imshow` + colorbar) и
  выкинуть seaborn из зависимостей — быстрее холодный старт, меньше конфликтов.

### 14.12 Перспектива (если планируется рост)

- **ИИ-агент поверх дневника**: текущее чистое доменное ядро переносится в сервис
  (FastAPI) без переписывания; графики — Plotly/React. Стоит спланировать этот
  переход, пока модель данных не разрослась.
- **Мультипользователь/сервер**: SQLite → PostgreSQL, сервисы уже будут готовы.

---

## 15. Рекомендации (приоритизированный роадмап)

### P0 — стабилизация модели данных
1. Ввести `@dataclass Deal` с **явным полем `direction`** и типизированными полями;
   заменить `list-of-lists` на список `Deal`/dataclass-строк.
2. Убрать `__init__`-баг в `Deal`, перевести поля в instance-атрибуты.
3. Заменить `diary.xml` на SQLite (единый `diary.db`) или JSON с атомарной записью
   (`tmp` + `os.replace`). Убрать дубль `_dealDirection`.

### P1 — тесты и развязка
4. Покрыть тестами чистое ядро: `pivot_indices`, `compute_ntfs_series`,
   `compute_mlrci`, `compute_macro_score`, `analyze_death_crosses`, `_regime`.
5. Вынести из `main.py` сервисы: `RiskService`, `CorrelationService`,
   `MacroService`, `PersistenceService`; `main.py` оставить только UI-оркестрацию.

### P2 — консистентность и гигиена
6. Вынести общий базовый класс виджета-графика (zoom/pan/скролл) и убрать дубль
   между `_IndicatorTab` и `MlrcTab`.
7. Убрать всю сеть с UI-потока (дебаунс-тикер в DealDialog, `ensure_history`,
   `fetch_usd_rate`) — в фон через существующие потоки.
8. Заменить `print` на `logging`; убрать мёртвый код и абсолютные пути.
9. Добавить `ruff` + type hints + CI (compile + headless-тесты диалогов в offscreen).

### P3 — архитектурные развилки
10. Если планируется ИИ-агент поверх дневника — рассмотреть сервисный слой
    (FastAPI + Plotly/React) вместо десктопа; текущее чистое доменное ядро перенесётся
    без переписывания.

---

## 16. Итоговая оценка

| Критерий | Оценка |
|---|---|
| Разделение слоёв | Хорошо (по файлам), но `main.py` перегружен |
| Модель данных | Слабо (списки, магические индексы, `Deal` без `__init__`) |
| Работа с потоками | Отлично для PySide6 |
| Кэширование | Отлично |
| Доменная логика | Отлично (чистое ядро, документировано) |
| UI-паттерны | Хорошо (немодальность, тема), есть дубль навигации |
| Тестируемость | Слабо (нет тестов), но ядро к этому готово |
| Документация | Отлично |

**Вывод**: проект производит впечатление зрелого в части, где это сложнее всего
(потоки, кэш, доменная математика), и «студенческого» в самой скучной части —
модели данных и тестах. Это классическая картина сильного практика, который решал
интересные задачи и откладывал рутину. Потенциал для рефакторинга высокий, риски
понятны и локализованы.

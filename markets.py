# -*- coding: utf-8 -*-
import requests

RUB = 'RUB'
USD = 'USD'
CURRENCY_SIGN = {RUB: '\u20bd', USD: '$'}

MOEX = 'MOEX'
WORLD = 'WORLD'

_UA = {'User-Agent': 'Mozilla/5.0'}


def _fetch_usd_rate_cached():
    if not hasattr(_fetch_usd_rate_cached, 'rate'):
        _fetch_usd_rate_cached.rate = None
        try:
            r = requests.get(
                'https://iss.moex.com/iss/engines/currency/markets/selt/boards/CETS/securities/USD000UTSTOM.json',
                timeout=5)
            r.raise_for_status()
            data = r.json()
            rows = data.get('marketdata', {}).get('data', [])
            cols = data.get('marketdata', {}).get('columns', [])
            if rows and 'LAST' in cols:
                last_idx = cols.index('LAST')
                for row in rows:
                    if row[last_idx] is not None:
                        _fetch_usd_rate_cached.rate = float(row[last_idx])
                        break
        except Exception as e:
            print('Failed to fetch USD/RUB rate: ' + str(e))
    return _fetch_usd_rate_cached.rate


def fetch_usd_rate():
    return _fetch_usd_rate_cached()


def fetch_moex_price(ticker):
    url = 'https://iss.moex.com/iss/engines/stock/markets/shares/securities/{}.json'.format(ticker)
    try:
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        data = r.json()
        rows = data.get('marketdata', {}).get('data', [])
        cols = data.get('marketdata', {}).get('columns', [])
        if rows and 'LAST' in cols:
            last_idx = cols.index('LAST')
            for row in rows:
                if row[last_idx] is not None:
                    return float(row[last_idx])
    except Exception as e:
        print('Failed to fetch MOEX price for ' + ticker + ': ' + str(e))
    return None


def _fetch_yahoo_price(ticker):
    for host in ('query1', 'query2'):
        url = 'https://{}.finance.yahoo.com/v8/finance/chart/{}'.format(host, ticker)
        try:
            r = requests.get(url, headers=_UA, timeout=8)
            r.raise_for_status()
            data = r.json()
            result = data.get('chart', {}).get('result')
            if result:
                price = result[0].get('meta', {}).get('regularMarketPrice')
                if price is not None:
                    return float(price)
        except Exception as e:
            print('Yahoo {} failed for {}: {}'.format(host, ticker, e))
    return None


def _fetch_stooq_price(ticker):
    url = 'https://stooq.com/q/l/?s={}.us&f=cd&h&e=csv'.format(ticker.lower())
    try:
        r = requests.get(url, headers=_UA, timeout=8)
        r.raise_for_status()
        lines = r.text.strip().splitlines()
        if len(lines) > 1:
            value = lines[1].split(',')[-1]
            if value not in ('N/D', ''):
                return float(value)
    except Exception as e:
        print('Stooq failed for {}: {}'.format(ticker, e))
    return None


def fetch_world_price(ticker):
    price = _fetch_yahoo_price(ticker)
    if price is not None:
        return price
    return _fetch_stooq_price(ticker)


def market_currency(ticker):
    """Detect market (MOEX or WORLD) and currency (RUB or USD). Never raises."""
    if not ticker:
        return None, None
    if fetch_moex_price(ticker) is not None:
        return MOEX, RUB
    if fetch_world_price(ticker) is not None:
        return WORLD, USD
    return None, None


def convert_usd(value_rub, rate=None):
    if rate is None:
        rate = fetch_usd_rate()
    if rate:
        return value_rub / rate
    return None

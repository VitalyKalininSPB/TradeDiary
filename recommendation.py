# -*- coding: utf-8 -*-
"""Рекомендация по компании: компактная сводка + раскрытая механика.

Чистая математика (без Qt/matplotlib): переводит ranked-строку компании в
RU-строки и данные для 4-столбцовых графиков (сектор/компания × сейчас/форвард).

Вход — dict из company_quant.rank_companies (e):
  forward_pe, trailing_pe, eps_growth (forward YoY), trailing_eps_growth,
  peg, pct_pe, sector_median_pe, sector_median_eps_growth,
  sector_median_trailing_pe, sector_median_trailing_eps_growth.
"""

# Порог для направления ожиданий: разрыв trailing↔forward P/E в ±3%.
_REV_THRESHOLD = 0.03


def _fmt_pct(v):
    if v is None:
        return None
    return '{:+.1f}%'.format(v)


def _fmt_pe(v):
    if v is None:
        return None
    return '{:.1f}×'.format(v)


def _revision_dir(tp, fp):
    """Направление ожиданий из разрыва P/E: forward < trailing => рост EPS."""
    if tp is None or fp is None or fp <= 0:
        return None
    implied = tp / fp - 1.0
    if implied > _REV_THRESHOLD:
        return 'up'
    if implied < -_REV_THRESHOLD:
        return 'down'
    return 'flat'


def _status(above, revision):
    """Статус из матрицы: Рост выше/ниже peers × ожидания растут/падают."""
    if above is None or revision is None:
        return None
    improving = revision in ('up', 'flat')
    if above:
        return 'Рост подтверждается' if improving else 'Рост под вопросом'
    return 'Восстановление возможно' if improving else 'Замедление прибыли'


def build_recommendation(e):
    feg = e.get('eps_growth')                       # форвард, компания
    sfeg = e.get('sector_median_eps_growth')        # форвард, медиана сектора
    tepsg = e.get('trailing_eps_growth')            # сейчас, компания
    steg = e.get('sector_median_trailing_eps_growth')
    fp = e.get('forward_pe')
    sfp = e.get('sector_median_pe')
    tp = e.get('trailing_pe')
    stp = e.get('sector_median_trailing_pe')
    pct_pe = e.get('pct_pe')
    peg = e.get('peg')

    rel = (feg - sfeg) if (feg is not None and sfeg is not None) else None
    above = None if rel is None else rel >= 0

    revision = _revision_dir(tp, fp)
    status = _status(above, revision)
    rev_txt = {'up': '↑ растут', 'flat': '→ стабильны',
               'down': '↓ снижаются'}.get(revision, '-')

    # --------------------------- свёрнутая сводка
    summary = [
        'Ожидаемый рост прибыли: {}'.format(_fmt_pct(feg) or '-'),
        'Похожие компании: {}'.format(_fmt_pct(sfeg) or '-'),
        'Относительный рост: {}'.format(
            '{:+.1f} п.п.'.format(rel) if rel is not None else '-'),
        'Ожидания аналитиков: {}'.format(rev_txt),
        'Статус: {}'.format(status or '-'),
    ]

    # --------------------------- раскрытая механика
    mech = []
    implied = None
    if tp is not None and fp is not None and fp > 0:
        implied = (tp / fp - 1.0) * 100.0
        mech.append('P/E сейчас: {} → Forward P/E: {} ({:+.0f}% к текущему)'
                    .format(_fmt_pe(tp), _fmt_pe(fp), implied))
    elif tp is not None or fp is not None:
        mech.append('P/E сейчас: {} · Forward P/E: {}'.format(
            _fmt_pe(tp) or '-', _fmt_pe(fp) or '-'))
    mech.append('EPS growth (форвард, YoY): {}'.format(_fmt_pct(feg) or '-'))
    if tepsg is not None:
        mech.append('EPS growth (текущий, YoY): {}'.format(_fmt_pct(tepsg)))
    if feg is not None and sfeg is not None:
        mech.append('Относительный рост к сектору: {:+.1f} п.п.'
                    .format(rel))
    mech.append('PEG: {:.2f}'.format(peg) if peg is not None else 'PEG: -')
    if sfp is not None:
        peers_line = 'Peers: медиана Forward P/E сектора {}'.format(
            _fmt_pe(sfp))
        if pct_pe is not None:
            peers_line += ' · компания дешевле {:.0f}% компаний сектора'.format(
                100 - pct_pe)
        mech.append(peers_line)
    if revision is not None:
        rev_w = {'up': 'растут', 'flat': 'стабильны',
                 'down': 'снижаются'}[revision]
        if implied is not None:
            mech.append('Revisions (оценка): ожидания {} — рынок закладывает '
                        '{:+.0f}% к EPS'.format(rev_w, implied))
        else:
            mech.append('Revisions (оценка): ожидания {}'.format(rev_w))
    mech.append('Статус: {}'.format(status or '-'))

    pe_bars = [('Сектор сейчас', stp), ('Компания сейчас', tp),
               ('Сектор форвардный', sfp), ('Компания форвардная', fp)]
    epsg_bars = [('Сектор сейчас', steg), ('Компания сейчас', tepsg),
                 ('Сектор форвардный', sfeg), ('Компания форвардная', feg)]

    return {'rel': rel, 'above': above, 'revision': revision, 'status': status,
            'summary_lines': summary, 'expanded_lines': mech,
            'pe_bars': pe_bars, 'epsg_bars': epsg_bars}
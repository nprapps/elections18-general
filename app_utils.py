from collections import OrderedDict
from decimal import Decimal, ROUND_DOWN
from models import models


def get_results(name):
    results = models.Result.select(
        models.Result,
        models.Call.accept_ap,
        models.Call.override_winner
    ).where(
        (models.Result.level == 'state') | (models.Result.level == 'national') | (models.Result.level == 'district'),
        models.Result.officename == name
    ).order_by(
        models.Result.statepostal,
        models.Result.seatname,
        -models.Result.votecount,
        models.Result.last
    ).join(
        models.Call,
        on=(models.Call.call_id == models.Result.id)
    ).dicts()

    grouped = OrderedDict()
    for result in results:
        grouped[result['raceid']] = grouped.get(result['raceid'], []) + [result]

    return grouped


def comma_filter(value):
    """
    Format a number with commas.
    """
    return '{:,}'.format(value)


def percent_filter(value):
    """
    Format percentage
    """
    value = Decimal(value) * Decimal(100)
    if value == 0:
        return '0%'
    elif value == 100:
        return '100%'
    elif value > 0 and value < 1:
        return '<1%'
    else:
        cleaned_pct = value.quantize(Decimal('.1'), rounding=ROUND_DOWN)
        return '{:.1f}%'.format(cleaned_pct)


def never_cache_preview(response):
    """
    Ensure preview is never cached
    """
    response.cache_control.max_age = 0
    response.cache_control.no_cache = True
    response.cache_control.must_revalidate = True
    response.cache_control.no_store = True
    return response


def open_db():
    """
    Open db connection
    """
    if models.db._local.closed:
        models.db.connect()


def close_db(response):
    """
    Close db connection
    """
    models.db.close()
    return response

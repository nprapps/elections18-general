#!/usr/bin/env python
# _*_ coding:utf-8 _*_
from datetime import datetime
from models import models
from playhouse.shortcuts import model_to_dict


"""
List of Result model fields that will be serialized
"""
COMMON_SELECTIONS = [
    models.Result.first,
    models.Result.last,
    models.Result.lastupdated,
    models.Result.level,
    models.Result.officename,
    models.Result.party,
    models.Result.precinctsreporting,
    models.Result.precinctsreportingpct,
    models.Result.precinctstotal,
    models.Result.raceid,
    models.Result.statename,
    models.Result.statepostal,
    models.Result.votepct,
    models.Result.votecount
]


"""
Names of Result model fields that pertain to the race
"""
RACE_SELECTIONS = (
    'lastupdated',
    'level',
    'officename',
    'precinctsreporting',
    'nprformat_precinctsreportingpct',
    'precinctstotal',
    'statename',
    'statepostal'
)

"""
Names of Result model fields that pertain to a candidate's result
"""
CANDIDATES_SELECTIONS = (
    'first',
    'last',
    'party',
    'votepct',
    'votecount',
    'winner'
)


def serialize_results(results, selections=COMMON_SELECTIONS, key='raceid'):
    """
    Returns a collection of results that can be serialized as JSON.

    Also shapes the collection of results in a format that is easy to consume
    by front-end code.

    Args:
        results (SelectQuery): Peewee `SelectQuery` object that can be
            iterated over to get `Result` model instances to be
            serialized.
        selections (list): Only fields in this list of `Result` model
            fields will be serialized.
        key (str): Key used to look up races in the returned dictionary.
            Default is `raceid`.

    Returns:
        Collection of results as a dictionary.

    """
    serialized_results = {
        'results': {}
    }

    for result in results:
        result_dict = model_to_dict(result, backrefs=True, only=selections)
        # Add custom npr calculated data
        result_dict['winner'] = result.is_npr_winner()
        result_dict['nprformat_precinctsreportingpct'] = (
            result.nprformat_precinctsreportingpct()
        )

        dict_key = result_dict[key]
        if dict_key not in serialized_results['results']:
            serialized_results['results'][dict_key] = {
                k: result_dict[k] for k in RACE_SELECTIONS
            }
            _override_last_updated(serialized_results['results'][dict_key])
            serialized_results['results'][dict_key]['candidates'] = []

        serialized_results['results'][dict_key]['candidates'].append({
            k: result_dict[k] for k in CANDIDATES_SELECTIONS
        })

    return serialized_results


def _override_last_updated(serialized_results):
    """Use the AP lastupdated timestamp when results are available
    In other case use the execution timestamp
    """
    if serialized_results['precinctsreporting'] == 0 or serialized_results['lastupdated'] == None:
        serialized_results['lastupdated'] = datetime.utcnow()

#!/usr/bin/env python
# _*_ coding:utf-8 _*_

import app_config
import logging
import simplejson as json

from fabric.api import local, task
from models import models
from playhouse.shortcuts import model_to_dict

from . import utils

logging.basicConfig(format=app_config.LOG_FORMAT)
logger = logging.getLogger(__name__)
logger.setLevel(app_config.LOG_LEVEL)

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


def _select_senate_results():
    """Returns Peewee model instances for U.S. Senate results"""
    results = models.Result.select().where(
        models.Result.level == 'state',
        models.Result.officename == 'U.S. Senate'
    )

    return results


def _serialize_results(results, selections, key='raceid'):
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
            serialized_results['results'][dict_key]['candidates'] = []

        serialized_results['results'][dict_key]['candidates'].append({
            k: result_dict[k] for k in CANDIDATES_SELECTIONS
        })

    return serialized_results


@task
def render_senate_results():
    """Render U.S. Senate results to JSON"""
    results = _select_senate_results()

    serialized_results = _serialize_results(results, COMMON_SELECTIONS)
    _write_json_file(serialized_results, 'alabama-test-results.json')


def _write_json_file(serialized_results, filename):
    """
    Write results JSON to a file

    Args:
        serialized_results (dict): JSON-serializeable collection of results.
        filename (str): Path to file where the results JSON will be written.

    """
    json_path = '{0}/{1}'.format(app_config.DATA_OUTPUT_FOLDER, filename)
    with open(json_path, 'w') as f:
        json.dump(serialized_results, f, use_decimal=True,
                  cls=utils.APDatetimeEncoder)


@task
def render():
    """Render all results to JSON files"""
    local('rm -rf {0}'.format(app_config.DATA_OUTPUT_FOLDER))
    local('mkdir {0}'.format(app_config.DATA_OUTPUT_FOLDER))
    render_senate_results()

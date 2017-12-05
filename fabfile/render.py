#!/usr/bin/env python
# _*_ coding:utf-8 _*_

import app_config
import logging
import os
import re
import shutil
import simplejson as json

from datetime import date, datetime
from fabric.api import execute, hide, local, task, settings, shell_env
from fabric.state import env
from models import models
from playhouse.shortcuts import model_to_dict
from pytz import timezone
from time import time

from . import utils

logging.basicConfig(format=app_config.LOG_FORMAT)
logger = logging.getLogger(__name__)
logger.setLevel(app_config.LOG_LEVEL)

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

CANDIDATES_SELECTIONS = (
    'first',
    'last',
    'party',
    'votepct',
    'votecount',
    'winner'
)


def _select_senate_results():
    results = models.Result.select().where(
        models.Result.level == 'state',
        models.Result.officename == 'U.S. Senate'
    )

    return results


def _serialize_results(results, selections, key='raceid'):
    with models.db.execution_context() as ctx:
        serialized_results = {
            'results': {}
        }

        for result in results:
            result_dict = model_to_dict(result, backrefs=True, only=selections)
            # Add custom npr calculated data
            result_dict['winner'] = result.is_npr_winner()
            result_dict['nprformat_precinctsreportingpct'] = result.nprformat_precinctsreportingpct()


            dict_key = result_dict[key]
            if not serialized_results['results'].get(dict_key):
                serialized_results['results'][dict_key] = {k: result_dict[k] for k in RACE_SELECTIONS}
                serialized_results['results'][dict_key]['candidates'] = []

            serialized_results['results'][dict_key]['candidates'].append({k: result_dict[k] for k in CANDIDATES_SELECTIONS})

        return serialized_results


@task
def render_senate_results():
    results = _select_senate_results()

    serialized_results = _serialize_results(results, COMMON_SELECTIONS)
    _write_json_file(serialized_results, 'alabama-results.json')

def _write_json_file(serialized_results, filename):
    with open('{0}/{1}'.format(app_config.DATA_OUTPUT_FOLDER, filename), 'w') as f:
        json.dump(serialized_results, f, use_decimal=True, cls=utils.APDatetimeEncoder)


@task
def render():
    local('rm -rf {0}'.format(app_config.DATA_OUTPUT_FOLDER))
    local('mkdir {0}'.format(app_config.DATA_OUTPUT_FOLDER))
    render_senate_results()

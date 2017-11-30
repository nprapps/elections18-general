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
    models.Result.votecount,
    models.Result.winner
]

SENATE_SELECTIONS = COMMON_SELECTIONS + [
    models.Result.incumbent,
    models.Result.runoff
]


ACCEPTED_PARTIES = ['Dem', 'GOP']


def _select_senate_results():
    results = models.Result.select().where(
        models.Result.level == 'state',
        models.Result.officename == 'U.S. Senate'
    )

    return results


def _serialize_results(results, selections, key='statepostal'):
    with models.db.execution_context() as ctx:
        serialized_results = {
            'results': {}
        }

        for result in results:
            result_dict = model_to_dict(result, backrefs=True, only=selections)
            result_dict['npr_winner'] = result.is_npr_winner()

            dict_key = result_dict[key]
            if not serialized_results['results'].get(dict_key):
                serialized_results['results'][dict_key] = []

            serialized_results['results'][dict_key].append(result_dict)

        serialized_results['last_updated'] = _get_last_updated(serialized_results)

        return serialized_results


def _get_last_updated(serialized_results):
    last_updated = None

    for key, val in serialized_results['results'].items():
        if isinstance(val, list):
            if val[0]['precinctsreporting'] > 0:
                for result in val:
                    if not last_updated or result['lastupdated'] > last_updated:
                        last_updated = result['lastupdated']

        elif isinstance(val, dict):
            for key, val in val.items():
                if val[0]['precinctsreporting'] > 0:
                    for result in val:
                        if not last_updated or result['lastupdated'] > last_updated:
                            last_updated = result['lastupdated']

    if not last_updated:
        last_updated = datetime.utcnow()

    return last_updated


def _set_npr_winner(result, result_dict):
    result_dict['npr_winner'] = result.is_npr_winner()


@task
def render_senate_results():
    results = _select_senate_results()

    serialized_results = _serialize_results(results, SENATE_SELECTIONS)
    _write_json_file(serialized_results, 'alabama-results.json')

def _write_json_file(serialized_results, filename):
    with open('{0}/{1}'.format(app_config.DATA_OUTPUT_FOLDER, filename), 'w') as f:
        json.dump(serialized_results, f, use_decimal=True, cls=utils.APDatetimeEncoder)


@task
def render():
    local('rm -rf {0}'.format(app_config.DATA_OUTPUT_FOLDER))
    local('mkdir {0}'.format(app_config.DATA_OUTPUT_FOLDER))
    render_senate_results()

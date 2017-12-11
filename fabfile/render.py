#!/usr/bin/env python
# _*_ coding:utf-8 _*_
import app_config
import logging
import simplejson as json

from fabric.api import local, task
import utils


logging.basicConfig(format=app_config.LOG_FORMAT)
logger = logging.getLogger(__name__)
logger.setLevel(app_config.LOG_LEVEL)


@task
def render_results(config):
    """Render U.S. Senate results to JSON"""
    query = utils.import_string(config['query'])
    transform = utils.import_string(config['transform'])
    results = query()
    serialized_results = transform(results)
    _write_json_file(serialized_results, config['filename'])


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
    for config in app_config.RESULTS:
        render_results(config)

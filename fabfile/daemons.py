from time import sleep, time
from fabric.api import execute, require, settings, task
from fabric.state import env


import app_config
import logging
import sys

logging.basicConfig(format=app_config.LOG_FORMAT)
logger = logging.getLogger(__name__)
logger.setLevel(app_config.LOG_LEVEL)


@task
def deploy(run_once=False):
    """
    Harvest data and deploy cards
    """
    require('settings', provided_by=['production', 'staging'])
    try:
        with settings(warn_only=True):
            main(run_once)
    except KeyboardInterrupt:
        sys.exit(0)


def main(run_once=False):
    """
    Main loop
    """
    results_start = 0
    mode = 'fast'

    while True:
        now = time()

        if app_config.LOAD_RESULTS_INTERVAL and (now - results_start) > app_config.LOAD_RESULTS_INTERVAL:
            results_start = now
            if mode == 'fast':
                logger.info('loading all national results')
                execute('data.load_results', mode)
                execute('deploy_national_data')
            
            if mode == 'slow':
                logger.info('loading all presidential results')
                execute('data.load_results', mode)
                execute('deploy_presidential_data')

            if mode == 'fast':
                mode = 'slow'
            elif mode == 'slow':
                mode = 'fast'
        
        if run_once:
            logger.info('run once specified, exiting')
            sys.exit(0)

        sleep(1)
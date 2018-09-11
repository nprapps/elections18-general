from time import sleep, time
from fabric.api import execute, require, settings, task


import app_config
import logging
import sys

logging.basicConfig(format=app_config.LOG_FORMAT)
logger = logging.getLogger(__name__)
logger.setLevel(app_config.LOG_LEVEL)


@task
def fetch_and_publish_results(run_once=False):
    """
    Harvest data and deploy cards
    """
    require('settings', provided_by=['production', 'staging'])
    try:
        with settings(warn_only=True):
            main(run_once)
    except KeyboardInterrupt:
        sys.exit(0)


@task
def main(run_once=False):
    """
    Main loop
    """
    results_start = 0

    while True:
        now = time()

        if app_config.LOAD_RESULTS_INTERVAL and (now - results_start) > app_config.LOAD_RESULTS_INTERVAL:
            results_start = now
            logger.info('updating get-caught-up text (runs in parallel)')
            execute('text.update_in_parallel')
            logger.info('loading results')
            execute('data.load_results')
            logger.info("results loaded: %s seconds" % (time() - results_start))
            execute('publish_results')
            logger.info("results rendered and published: %s seconds" % (time() - results_start))

        if run_once:
            logger.info('run once specified, exiting')
            sys.exit(0)

        sleep(0.1)

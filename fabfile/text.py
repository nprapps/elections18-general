#!/usr/bin/env python
"""
Commands related to syncing docs and spreadsheets from Google Drive.
"""

import logging

import app_config

from fabric.api import parallel, task
from oauth import get_document


logging.basicConfig(format=app_config.LOG_FORMAT)
logger = logging.getLogger(__name__)
logger.setLevel(app_config.LOG_LEVEL)


@task(default=True)
def update():
    """
    Update all Drive content.
    """
    update_copytext()
    update_calendar()


@task
@parallel
def update_in_parallel():
    '''
    Update the tabular data in the background
    '''
    try:
        update_calendar()
    except KeyError as e:
        message = str(e)
        # Allow `500` errors, since Google sometimes fails on its end,
        # and we don't want that to cause the AP data pipeline to fail
        if '500' in message:
            logger.warning(message)
        # Other errors, such as user-caused OAuth problems, should trigger
        # normally
        else:
            raise e


def update_copytext():
    """
    Downloads a Google Doc as an Excel file.
    """
    get_document(
        app_config.COPY_GOOGLE_DOC_KEY,
        app_config.COPY_PATH
    )


def update_calendar():
    """
    Download calendar file.
    """
    get_document(
        app_config.CALENDAR_GOOGLE_DOC_KEY,
        app_config.CALENDAR_PATH
    )

#!/usr/bin/env python
"""
Commands related to syncing docs and spreadsheets from Google Drive.
"""

import app_config

from fabric.api import parallel, task
from oauth import get_document


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
    update_calendar()


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

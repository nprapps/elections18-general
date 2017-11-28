#!/usr/bin/env python
"""
Commands related to syncing docs and spreadsheets from Google Drive.
"""

import app_config
import copytext

from fabric.api import task
from fabric.state import env
from oauth import get_document


@task(default=True)
def update():
    """
    Update all Drive content.
    """
    update_copytext()
    update_calendar()

@task
def update_copytext():
    """
    Downloads a Google Doc as an Excel file.
    """
    get_document(app_config.COPY_GOOGLE_DOC_KEY,
                    app_config.COPY_PATH)


@task
def update_calendar():
    """
    Download calendar file.
    """
    get_document(app_config.CALENDAR_GOOGLE_DOC_KEY,
                    app_config.CALENDAR_PATH)
#!/usr/bin/env python

import app_config
import boto
from datetime import date, datetime
import logging
from pytz import timezone
import simplejson as json
from time import time

from boto.s3.connection import OrdinaryCallingFormat
from fabric.api import local, task

logging.basicConfig(format=app_config.LOG_FORMAT)
logger = logging.getLogger(__name__)
logger.setLevel(app_config.LOG_LEVEL)

AP_MONTHS = ['Jan.', 'Feb.', 'March', 'April', 'May', 'June', 'July', 'Aug.', 'Sept.', 'Oct.', 'Nov.', 'Dec.']

"""
Utilities used by multiple commands.
"""

from fabric.api import prompt

def confirm(message):
    """
    Verify a users intentions.
    """
    answer = prompt(message, default="Not at all")

    if answer.lower() not in ('y', 'yes', 'buzz off', 'screw you'):
        exit()


def get_bucket(bucket_name):
    """
    Established a connection and gets s3 bucket
    """

    if '.' in bucket_name:
        s3 = boto.connect_s3(calling_format=OrdinaryCallingFormat())
    else:
        s3 = boto.connect_s3()

    return s3.get_bucket(bucket_name)

@task
def install_font(force='true'):
    """
    Install font
    """
    print('Installing font')
    if force != 'true':
        try:
            with open('www/css/icon/npr-app-template.css') and open('www/css/font/npr-app-template.svg'):
                logger.info('Font installed, skipping.')
                return
        except IOError:
            pass

    local('node_modules/fontello-cli/bin/fontello-cli install --config fontello/config.json --css www/css/icon --font www/css/font/')


@task
def open_font():
    """
    Open font in Fontello GUI in your browser
    """
    local('node_modules/fontello-cli/bin/fontello-cli open --config fontello/config.json')


class APDatetimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            thedate = ap_date_filter(obj)
            thetime = ap_time_filter(obj)
            theperiod = ap_time_period_filter(obj)
            return '{0}, {1} {2}'.format(thedate, thetime, theperiod)
        elif isinstance(obj, date):
            return obj.isoformat()
        else:
            return super(APDatetimeEncoder, self).default(obj)

def ap_date_filter(value):
    """
    Converts a date string in m/d/yyyy format into AP style.
    """
    if isinstance(value, str):
        value = datetime.strptime(value, '%m/%d/%Y')
    value_tz = _set_timezone(value)
    output = AP_MONTHS[value_tz.month - 1]
    output += ' ' + str(value_tz.day)
    output += ', ' + str(value_tz.year)

    return output


def ap_time_filter(value):
    """
    Converts a datetime or string in hh:mm format into AP style.
    """
    if isinstance(value, str):
        value = datetime.strptime(value, '%I:%M')
    value_tz = _set_timezone(value)
    value_year = value_tz.replace(year=2016)
    return value_year.strftime('%-I:%M')


def ap_state_filter(usps):
    """
    Convert a USPS state abbreviation into AP style.
    """
    return USPS_TO_AP_STATE[str(usps)]


def ap_time_period_filter(value):
    """
    Converts Python's AM/PM into AP Style's a.m./p.m.
    """
    if isinstance(value, str):
        value = datetime.strptime(value, '%p')
    value_tz = _set_timezone(value)
    value_year = value_tz.replace(year=2016)
    periods = '.'.join(value_year.strftime('%p')) + '.'
    return periods.lower()

def _set_timezone(value):
    datetime_obj_utc = value.replace(tzinfo=timezone('GMT'))
    datetime_obj_est = datetime_obj_utc.astimezone(timezone('US/Eastern'))
    return datetime_obj_est
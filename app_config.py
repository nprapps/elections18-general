#!/usr/bin/env python

"""
Project-wide application configuration.

DO NOT STORE SECRETS, PASSWORDS, ETC. IN THIS FILE.
They will be exposed to users. Use environment variables instead.
See get_secrets() below for a fast way to access them.
"""

import logging
import os

from authomatic.providers import oauth2
from authomatic import Authomatic


"""
NAMES
"""
# Project name to be used in urls
# Use dashes, not underscores!
PROJECT_SLUG = 'elections17-alabama'

# Project name to be used in file paths
PROJECT_FILENAME = 'elections17_alabama'

# The name of the repository containing the source
REPOSITORY_NAME = 'elections17-alabama'
GITHUB_USERNAME = 'nprapps'
REPOSITORY_URL = 'git@github.com:%s/%s.git' % (GITHUB_USERNAME, REPOSITORY_NAME)
REPOSITORY_ALT_URL = None # 'git@bitbucket.org:nprapps/%s.git' % REPOSITORY_NAME'

# Project name used for assets rig
# Should stay the same, even if PROJECT_SLUG changes
ASSETS_SLUG = 'elections17-alabama'

"""
DEPLOYMENT
"""
PRODUCTION_S3_BUCKET = 'apps.npr.org'

STAGING_S3_BUCKET = 'stage-apps.npr.org'

ASSETS_S3_BUCKET = 'assets.apps.npr.org'

DEFAULT_MAX_AGE = 20

RELOAD_TRIGGER = False
RELOAD_CHECK_INTERVAL = 60

PRODUCTION_SERVERS = ['54.211.61.5']
STAGING_SERVERS = ['54.235.226.135']

# Should code be deployed to the web/cron servers?
DEPLOY_TO_SERVERS = True

SERVER_USER = 'ubuntu'
SERVER_PYTHON = 'python3'
SERVER_PROJECT_PATH = '/home/%s/apps/%s' % (SERVER_USER, PROJECT_FILENAME)
SERVER_REPOSITORY_PATH = '%s/repository' % SERVER_PROJECT_PATH
SERVER_VIRTUALENV_PATH = '%s/virtualenv' % SERVER_PROJECT_PATH

# Should the crontab file be installed on the servers?
# If True, DEPLOY_TO_SERVERS must also be True
DEPLOY_CRONTAB = False

# Should the service configurations be installed on the servers?
# If True, DEPLOY_TO_SERVERS must also be True
DEPLOY_SERVICES = False

UWSGI_SOCKET_PATH = '/tmp/%s.uwsgi.sock' % PROJECT_FILENAME

# Services are the server-side services we want to enable and configure.
# A three-tuple following this format:
# (service name, service deployment path, service config file extension)
SERVER_SERVICES = [
    ('app', SERVER_REPOSITORY_PATH, 'ini'),
    ('uwsgi', '/etc/init', 'conf'),
    ('nginx', '/etc/nginx/sites-enabled', 'conf'),
    ('deploy', '/etc/init', 'conf')
]

# These variables will be set at runtime. See configure_targets() below
S3_BUCKET = None
S3_BASE_URL = None
S3_DEPLOY_URL = None
SERVERS = []
SERVER_BASE_URL = None
SERVER_LOG_PATH = None
DEBUG = True

"""
COPY EDITING
"""
COPY_GOOGLE_DOC_KEY = '1eIDJz5Ay07XoX8zkSk1fINH-ovS2yaEa99kP67bZMz0'
COPY_PATH = 'data/copy.xlsx'

CALENDAR_GOOGLE_DOC_KEY = '1j5fxdiUyruSdjgNDU14lAIAw-r51oDCMdhaAnKcCWBU'
CALENDAR_PATH = 'data/meta.xlsx'

"""
SHARING
"""
SHARE_URL = 'http://%s/%s/' % (PRODUCTION_S3_BUCKET, PROJECT_SLUG)


"""
SERVICES
"""
NPR_GOOGLE_ANALYTICS = {
    'ACCOUNT_ID': 'UA-5828686-4',
    'DOMAIN': PRODUCTION_S3_BUCKET,
    'TOPICS': '' # e.g. '[1014,3,1003,1002,1001]'
}

VIZ_GOOGLE_ANALYTICS = {
    'ACCOUNT_ID': 'UA-5828686-75'
}

"""
OAUTH
"""

GOOGLE_OAUTH_CREDENTIALS_PATH = '~/.google_oauth_credentials'

authomatic_config = {
    'google': {
        'id': 1,
        'class_': oauth2.Google,
        'consumer_key': os.environ.get('GOOGLE_OAUTH_CLIENT_ID'),
        'consumer_secret': os.environ.get('GOOGLE_OAUTH_CONSUMER_SECRET'),
        'scope': ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/userinfo.email'],
        'offline': True,
    },
}

authomatic = Authomatic(authomatic_config, os.environ.get('AUTHOMATIC_SALT'))

"""
Logging
"""
LOG_FORMAT = '%(levelname)s:%(name)s:%(asctime)s: %(message)s'


"""
elex config
"""
NEXT_ELECTION_DATE = '2017-12-12'
ELEX_FLAGS = '--national-only --results-level state'
# ELEX_FLAGS = '--national-only --results-level ru'

LOAD_RESULTS_INTERVAL = 10
DATA_OUTPUT_FOLDER = '.rendered'

SELECTED_HOUSE_RACES = []

"""
Utilities
"""
def get_secrets():
    """
    A method for accessing our secrets.
    """
    secrets_dict = {}

    for k,v in os.environ.items():
        if k.startswith(PROJECT_SLUG):
            k = k[len(PROJECT_SLUG) + 1:]
            secrets_dict[k] = v

    return secrets_dict


def configure_targets(deployment_target):
    """
    Configure deployment targets. Abstracted so this can be
    overriden for rendering before deployment.
    """
    global S3_BUCKET
    global S3_BASE_URL
    global S3_DEPLOY_URL
    global SERVERS
    global SERVER_BASE_URL
    global SERVER_LOG_PATH
    global DEBUG
    global DEPLOYMENT_TARGET
    global LOG_LEVEL
    global ASSETS_MAX_AGE
    global database
    global NEXT_ELECTION_DATE
    global FAST_ELEX_FLAGS
    global SLOW_ELEX_FLAGS
    global ELEX_INIT_FLAGS
    global ELEX_DISTRICTS_FLAGS
    global LOAD_RESULTS_INTERVAL
    global ELEX_OUTPUT_FOLDER


    secrets = get_secrets()

    """
    Database
    """
    database = {
        'PGDATABASE': PROJECT_SLUG,
        'PGUSER': secrets.get('POSTGRES_USER', PROJECT_FILENAME),
        'PGPASSWORD': secrets.get('POSTGRES_PASSWORD', PROJECT_FILENAME),
        'PGHOST': secrets.get('POSTGRES_HOST', 'localhost'),
        'PGPORT': secrets.get('POSTGRES_PORT', '5432')
    }

    if deployment_target == 'production':
        S3_BUCKET = PRODUCTION_S3_BUCKET
        S3_BASE_URL = 'http://%s/%s' % (S3_BUCKET, PROJECT_SLUG)
        S3_DEPLOY_URL = 's3://%s/%s' % (S3_BUCKET, PROJECT_SLUG)
        SERVERS = PRODUCTION_SERVERS
        SERVER_BASE_URL = 'http://%s/%s' % (SERVERS[0], PROJECT_SLUG)
        SERVER_LOG_PATH = '/var/log/%s' % PROJECT_FILENAME
        LOG_LEVEL = logging.WARNING
        DEBUG = False
        ASSETS_MAX_AGE = 86400
        LOAD_RESULTS_INTERVAL = 60
        ELEX_OUTPUT_FOLDER = '.data'
    elif deployment_target == 'staging':
        S3_BUCKET = STAGING_S3_BUCKET
        S3_BASE_URL = 'http://%s/%s' % (S3_BUCKET, PROJECT_SLUG)
        S3_DEPLOY_URL = 's3://%s/%s' % (S3_BUCKET, PROJECT_SLUG)
        SERVERS = STAGING_SERVERS
        SERVER_BASE_URL = 'http://%s/%s' % (SERVERS[0], PROJECT_SLUG)
        SERVER_LOG_PATH = '/var/log/%s' % PROJECT_FILENAME
        LOG_LEVEL = logging.DEBUG
        DEBUG = True
        ASSETS_MAX_AGE = 20
        LOAD_RESULTS_INTERVAL = 10
        ELEX_OUTPUT_FOLDER = '.data'
    elif deployment_target == 'test':
        S3_BUCKET = STAGING_S3_BUCKET
        S3_BASE_URL = 'http://%s/%s' % (S3_BUCKET, PROJECT_SLUG)
        S3_DEPLOY_URL = 's3://%s/%s' % (S3_BUCKET, PROJECT_SLUG)
        SERVERS = STAGING_SERVERS
        SERVER_BASE_URL = 'http://%s/%s' % (SERVERS[0], PROJECT_SLUG)
        SERVER_LOG_PATH = '/var/log/%s' % PROJECT_FILENAME
        LOG_LEVEL = logging.DEBUG
        DEBUG = True
        ASSETS_MAX_AGE = 20
        NEXT_ELECTION_DATE = '2017-12-12'
        ELEX_FLAGS = '-d tests/data/test.json -o csv'
        LOAD_RESULTS_INTERVAL = 10
        ELEX_OUTPUT_FOLDER = '.testdata'
        database['PGDATABASE'] = '{0}_test'.format(database['PGDATABASE'])
        database['PGUSER'] = '{0}_test'.format(database['PGUSER'])
    else:
        S3_BUCKET = None
        S3_BASE_URL = 'http://127.0.0.1:8000'
        S3_DEPLOY_URL = None
        SERVERS = []
        SERVER_BASE_URL = 'http://127.0.0.1:8001/%s' % PROJECT_SLUG
        SERVER_LOG_PATH = '/tmp'
        LOG_LEVEL = logging.DEBUG
        DEBUG = True
        ASSETS_MAX_AGE = 20
        LOAD_RESULTS_INTERVAL = 10
        ELEX_OUTPUT_FOLDER = '.data'

    DEPLOYMENT_TARGET = deployment_target

"""
Run automated configuration
"""
DEPLOYMENT_TARGET = os.environ.get('DEPLOYMENT_TARGET', None)

configure_targets(DEPLOYMENT_TARGET)

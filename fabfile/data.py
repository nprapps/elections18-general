#!/usr/bin/env python

"""
Commands that update or process the application data.
"""
import app_config
import logging

from fabric.api import execute, hide, local, task, settings, shell_env
from fabric.state import env
from models import models

logging.basicConfig(format=app_config.LOG_FORMAT)
logger = logging.getLogger(__name__)
logger.setLevel(app_config.LOG_LEVEL)


@task
def bootstrap_db(testfilepath=None):
    """
    Build the database.
    """
    create_db()
    create_tables()
    if testfilepath:
        load_test_csv(testfilepath)
    else:
        load_results()
    create_calls()


@task
def create_db():
    with settings(warn_only=True), hide('output', 'running'):
        if env.get('settings'):
            execute('servers.stop_service', 'uwsgi')
            execute('servers.stop_service', 'deploy')

        with shell_env(**app_config.database):
            local('dropdb --if-exists %s' % app_config.database['PGDATABASE'])

        if not env.get('settings'):
            local('psql -c "DROP USER IF EXISTS %s;"' % app_config.database['PGUSER'])
            local('psql -c "CREATE USER %s WITH SUPERUSER PASSWORD \'%s\';"' % (app_config.database['PGUSER'], app_config.database['PGPASSWORD']))

        with shell_env(**app_config.database):
            local('createdb %s' % app_config.database['PGDATABASE'])

        if env.get('settings'):
            execute('servers.start_service', 'uwsgi')
            execute('servers.start_service', 'deploy')


@task
def create_tables():
    models.Result.create_table()
    models.Call.create_table()


@task
def delete_results():
    """
    Delete results without droppping database.
    """
    where_clause = ''

    with shell_env(**app_config.database), hide('output', 'running'):
        local('psql {0} -c "set session_replication_role = replica; DELETE FROM result {1}; set session_replication_role = default;"'.format(app_config.database['PGDATABASE'], where_clause))


@task
def load_results():
    """
    Load AP results. Defaults to next election, or specify a date as a parameter.
    """
    flags = app_config.ELEX_FLAGS

    election_date = app_config.NEXT_ELECTION_DATE
    with hide('output', 'running'):
        local('mkdir -p {0}'.format(app_config.ELEX_OUTPUT_FOLDER))

    cmd = 'elex results {0} {1} > {2}/results.csv'.format(
        election_date,
        flags,
        app_config.ELEX_OUTPUT_FOLDER)

    with shell_env(**app_config.database):
        with settings(warn_only=True), hide('output', 'running'):
            cmd_output = local(cmd, capture=True)

        if cmd_output.succeeded or cmd_output.return_code == 64:
            delete_results()
            with hide('output', 'running'):
                local('cat {0}/results.csv | psql {1} -c "COPY result FROM stdin DELIMITER \',\' CSV HEADER;"'.format(app_config.ELEX_OUTPUT_FOLDER, app_config.database['PGDATABASE']))
        else:
            print("ERROR GETTING MAIN RESULTS")
            print(cmd_output.stderr)

    logger.info('results loaded')


@task
def load_test_csv(path):
    """
    Load flat csv gathered from a previous elex run
    """
    delete_results()
    with shell_env(**app_config.database):
        with hide('output', 'running'):
            local('cat {0} | psql {1} -c "COPY result FROM stdin DELIMITER \',\' CSV HEADER;"'.format(path, app_config.database['PGDATABASE']))

    logger.info('test results loaded')


@task
def create_calls():
    """
    Create database of race calls for all races in results data.
    """
    models.Call.delete().execute()

    results = models.Result.select().where(models.Result.level == 'state')

    for result in results:
        models.Call.create(call_id=result.id)

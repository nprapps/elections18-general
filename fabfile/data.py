#!/usr/bin/env python

"""
Commands that update or process the application data.
"""
import app_config
import csv
import json
import hashlib
import logging
import math
import os
from time import sleep

import copytext
from fabric.api import execute, hide, local, task, settings, shell_env
from fabric.state import env
from models import models
import requests
import yaml

logging.basicConfig(format=app_config.LOG_FORMAT)
logger = logging.getLogger(__name__)
logger.setLevel(app_config.LOG_LEVEL)

CENSUS_REPORTER_URL = 'https://api.censusreporter.org/1.0/data/show/acs2016_5yr'
FIPS_TEMPLATE = '05000US{0}'
CENSUS_TABLES = ['B01003', 'B02001', 'B03002', 'B19013', 'B15001']


@task
def bootstrap_db():
    """
    Build the database.
    """
    create_db()
    create_tables()
    load_results(initialize=True)
    create_calls()
    create_race_meta()


@task
def create_db():
    with settings(warn_only=True), hide('output', 'running'):
        if env.get('settings'):
            execute('servers.stop_service', 'uwsgi')
            execute('servers.stop_service', 'fetch_and_publish_results')

        with shell_env(**app_config.database):
            local('dropdb --host={PGHOST} --port={PGPORT} --username={PGUSER} --if-exists {PGDATABASE}'.format(**app_config.database))
            local('createdb --host={PGHOST} --port={PGPORT} --username={PGUSER} {PGDATABASE}'.format(**app_config.database))

        if env.get('settings'):
            execute('servers.start_service', 'uwsgi')
            execute('servers.start_service', 'fetch_and_publish_results')


@task
def create_tables():
    models.Result.create_table()
    models.Call.create_table()
    models.RaceMeta.create_table()


@task
def delete_results():
    """
    Delete results without droppping database.
    """
    where_clause = ''

    with shell_env(**app_config.database), hide('output', 'running'):
        # Bypass the foreign-key constraint on deletion by using `session_replication_role`.
        # This is an opaque hack, and should be replaced with clearer,
        # more SQL-native database logic in the future
        local('psql {0} -c "set session_replication_role = replica; DELETE FROM result {1}; set session_replication_role = default;"'.format(
            app_config.database['PGURI'],
            where_clause
        ))


def make_flag_set_uid(flag_set):
    return hashlib.md5(flag_set.encode('utf-8')).hexdigest()


@task
def load_results(initialize=False):
    """
    Load AP results. Defaults to next election, or specify a date as a parameter.
    """
    if initialize is True:
        flag_sets = app_config.ELEX_INIT_FLAG_SETS
    else:
        flag_sets = app_config.ELEX_FLAG_SETS

    if not os.path.isdir(app_config.ELEX_OUTPUT_FOLDER):
        os.makedirs(app_config.ELEX_OUTPUT_FOLDER)

    RESULTS_FILENAME_PREFIX = 'results-'

    # Need separate filenames for the different possible elex flag sets,
    # so the simplest way is to use a hash of those flag-strings
    cmds = [
        'elex results {0} {1} > {2}'.format(
            flag_set,
            app_config.NEXT_ELECTION_DATE,
            os.path.join(
                app_config.ELEX_OUTPUT_FOLDER,
                RESULTS_FILENAME_PREFIX + make_flag_set_uid(flag_set) + '.csv'
            )
        )
        for flag_set in flag_sets
    ]

    with shell_env(**app_config.database):
        for cmd in cmds:
            with hide('output', 'running'):
                cmd_output = local(cmd, capture=True)

            # `elex` exit code `64` indicates that no new data was found,
            # and that the previous set of results will be re-used instead
            if not cmd_output.succeeded and cmd_output.return_code != 64:
                logger.critical("ERROR GETTING RESULTS")
                logger.critical(cmd_output.stderr)
                break
        else:
            delete_results()

            results_filenames = [
                os.path.join(
                    app_config.ELEX_OUTPUT_FOLDER,
                    RESULTS_FILENAME_PREFIX + make_flag_set_uid(flag_set) + '.csv'
                )
                for flag_set in flag_sets
            ]
            with hide('output', 'running'):
                local('csvstack {0} | psql {1} -c "COPY result FROM stdin DELIMITER \',\' CSV HEADER;"'.format(
                    ' '.join(results_filenames),
                    app_config.database['PGURI']
                ))

            logger.info('results loaded')


@task
def fetch_ftp_results():
    """
    Load flat csv gathered from a previous elex run
    """
    flags = app_config.ELEX_FTP_FLAGS
    cmd = 'python elex_ftp {0} > {1}/ftp_results.csv'.format(
        flags,
        app_config.ELEX_OUTPUT_FOLDER)
    with hide('output', 'running'):
        local(cmd)

    logger.info('ftp results fetched')


@task
def create_calls():
    """
    Create database of race calls for all races in results data.
    """
    models.Call.delete().execute()

    results = models.Result.select().where(models.Result.level == 'state')

    for result in results:
        models.Call.create(call_id=result.id)


@task
def create_race_meta():
    models.RaceMeta.delete().execute()

    calendar = copytext.Copy(app_config.CALENDAR_PATH)
    calendar_sheet = calendar['poll_times']
    senate_sheet = calendar['senate_seats']
    house_sheet = calendar['house_seats']

    results = models.Result.select()
    for result in results:
        meta_obj = {
            'result_id': result.id
        }

        if result.level == 'county' or result.level == 'township':
            continue

        if result.level == 'state' or result.level == 'district':
            calendar_row = list(filter(lambda x: x['key'] == result.statepostal, calendar_sheet))[0]

            meta_obj['poll_closing'] = calendar_row['time_est']
            meta_obj['first_results'] = calendar_row['first_results_est']
            meta_obj['full_poll_closing'] = calendar_row['time_all_est']

        if result.level == 'state' and result.officename == 'U.S. House':
            seat = '{0}-{1}'.format(result.statepostal, result.seatnum)
            house_row = list(filter(lambda x: x['seat'] == seat, house_sheet))[0]
            meta_obj['current_party'] = house_row['party']

            if 'competitive' in house_row['expected']:
                meta_obj['expected'] = 'competitive'
            else:
                meta_obj['expected'] = house_row['expected']

        if result.level == 'state' and result.officename == 'U.S. Senate':
            senate_row = list(filter(lambda x: x['state'] == result.statepostal, senate_sheet))[0]
            meta_obj['current_party'] = senate_row['party']

            if 'competitive' in senate_row['expected']:
                meta_obj['expected'] = 'competitive'
            else:
                meta_obj['expected'] = senate_row['expected']

        models.RaceMeta.create(**meta_obj)


@task
def copy_data_for_graphics():
    assert os.path.isdir(app_config.GRAPHICS_DATA_OUTPUT_FOLDER), \
            "Make sure that the local data output directory exists: `{}`".format(app_config.GRAPHICS_DATA_OUTPUT_FOLDER)
    with hide('output', 'running'):
        local('cp -r {0}/*.json {1}'.format(
            app_config.DATA_OUTPUT_FOLDER,
            app_config.GRAPHICS_DATA_OUTPUT_FOLDER
        ))


@task
def build_current_congress():
    party_dict = {
        'Democrat': 'Dem',
        'Republican': 'GOP',
        'Independent': 'Ind'
    }

    house_fieldnames = ['first', 'last', 'party', 'state', 'seat']
    senate_fieldnames = ['first', 'last', 'party', 'state']

    with open('data/house-seats.csv', 'w') as h, open('data/senate-seats.csv', 'w') as s:
        house_writer = csv.DictWriter(h, fieldnames=house_fieldnames)
        house_writer.writeheader()

        senate_writer = csv.DictWriter(s, fieldnames=senate_fieldnames)
        senate_writer.writeheader()

        with open('etc/legislators-current.yaml') as f:
            data = yaml.load(f)

        for legislator in data:
            current_term = legislator['terms'][-1]

            if current_term['end'][:4] == '2017':
                obj = {
                    'first': legislator['name']['first'],
                    'last': legislator['name']['last'],
                    'state': current_term['state'],
                    'party': party_dict[current_term['party']]
                }

                if current_term.get('district'):
                    obj['seat'] = '{0}-{1}'.format(current_term['state'], current_term['district'])

                if current_term['type'] == 'sen':
                    senate_writer.writerow(obj)
                elif current_term['type'] == 'rep':
                    house_writer.writerow(obj)


@task
def get_census_data(start_state='AA'):
    state_results = models.Result.select(models.Result.statepostal).distinct().order_by(models.Result.statepostal)

    for state_result in state_results:
        state = state_result.statepostal

        sorts = sorted([start_state, state])

        if sorts[0] == state:
            logging.info('skipping', state)
            continue

        logging.info('getting', state)
        output = {}
        fips_results = models.Result.select(models.Result.fipscode).distinct().where(models.Result.statepostal == state).order_by(models.Result.fipscode)
        for result in fips_results:
            if result.fipscode:
                if result.fipscode == '02000':
                    geo_id = '04000US02'
                elif result.fipscode == '46102':
                    geo_id = FIPS_TEMPLATE.format('46113')
                else:
                    geo_id = FIPS_TEMPLATE.format(result.fipscode)
                params = {
                    'geo_ids': geo_id,
                    'table_ids': ','.join(CENSUS_TABLES)
                }
                response = requests.get(CENSUS_REPORTER_URL, params=params)
                if response.status_code == 200:
                    print('fipscode succeeded', result.fipscode)
                    output[result.fipscode] = response.json()
                    sleep(2)
                else:
                    print('fipscode failed:', result.fipscode, response.status_code)
                    sleep(10)
                    continue

        with open('data/census/{0}.json'.format(state), 'w') as f:
            json.dump(output, f)


@task
def extract_census_data(fipscode, census_json):
    fips_census = census_json.get(fipscode)
    if fips_census:
        data = fips_census.get('data')
        for county, tables in data.items():
            population = tables['B01003']['estimate']
            race = tables['B02001']['estimate']
            hispanic = tables['B03002']['estimate']
            education = tables['B15001']['estimate']
            education_error = tables['B15001']['error']
            income = tables['B19013']['estimate']

            total_population = population['B01003001']

            race_total = race['B02001001']
            percent_black = race['B02001003'] / race_total

            hispanic_total = hispanic['B03002001']
            percent_white = hispanic['B03002003'] / hispanic_total
            percent_hispanic = hispanic['B03002012'] / hispanic_total

            median_income = income['B19013001']

            percent_bachelors, error = calculate_percent_bachelors(education, education_error)

            print(fipscode, percent_bachelors, error)
            return {
                'population': total_population,
                'percent_white': percent_white,
                'percent_black': percent_black,
                'percent_hispanic': percent_hispanic,
                'median_income': median_income,
                'percent_bachelors': percent_bachelors,
                'error': error
            }
    else:
        return None


def calculate_percent_bachelors(education, education_error):
    ed_total_population = education['B15001001']

    male_18_bachelors = education['B15001009']
    male_18_grad = education['B15001010']
    male_18 = male_18_bachelors + male_18_grad

    male_25_bachelors = education['B15001017']
    male_25_grad = education['B15001018']
    male_25 = male_25_bachelors + male_25_grad

    male_35_bachelors = education['B15001025']
    male_35_grad = education['B15001026']
    male_35 = male_35_bachelors + male_35_grad

    male_45_bachelors = education['B15001033']
    male_45_grad = education['B15001034']
    male_45 = male_45_bachelors + male_45_grad

    male_65_bachelors = education['B15001041']
    male_65_grad = education['B15001042']
    male_65 = male_65_bachelors + male_65_grad

    male_total = male_18 + male_25 + male_35 + male_45 + male_65

    female_18_bachelors = education['B15001050']
    female_18_grad = education['B15001051']
    female_18 = female_18_bachelors + female_18_grad

    female_25_bachelors = education['B15001058']
    female_25_grad = education['B15001059']
    female_25 = female_25_bachelors + female_25_grad

    female_35_bachelors = education['B15001066']
    female_35_grad = education['B15001067']
    female_35 = female_35_bachelors + female_35_grad

    female_45_bachelors = education['B15001074']
    female_45_grad = education['B15001075']
    female_45 = female_45_bachelors + female_45_grad

    female_65_bachelors = education['B15001082']
    female_65_grad = education['B15001083']
    female_65 = female_65_bachelors + female_65_grad

    female_total = female_18 + female_25 + female_35 + female_45 + female_65

    percent_bachelors = (male_total + female_total) / ed_total_population
    error = (math.sqrt(
        math.pow(education_error['B15001009'], 2) +
        math.pow(education_error['B15001010'], 2) +
        math.pow(education_error['B15001017'], 2) +
        math.pow(education_error['B15001018'], 2) +
        math.pow(education_error['B15001025'], 2) +
        math.pow(education_error['B15001026'], 2) +
        math.pow(education_error['B15001033'], 2) +
        math.pow(education_error['B15001034'], 2) +
        math.pow(education_error['B15001041'], 2) +
        math.pow(education_error['B15001042'], 2) +
        math.pow(education_error['B15001049'], 2) +
        math.pow(education_error['B15001050'], 2) +
        math.pow(education_error['B15001051'], 2) +
        math.pow(education_error['B15001058'], 2) +
        math.pow(education_error['B15001059'], 2) +
        math.pow(education_error['B15001066'], 2) +
        math.pow(education_error['B15001067'], 2) +
        math.pow(education_error['B15001074'], 2) +
        math.pow(education_error['B15001075'], 2) +
        math.pow(education_error['B15001082'], 2) +
        math.pow(education_error['B15001083'], 2)
    ) / ed_total_population)

    return percent_bachelors, error


def extract_2012_data(fipscode, filename):
    with open(filename) as f:
        reader = csv.DictReader(f)
        obama_row = [row for row in reader if row['fipscode'] == fipscode and row['last'] == 'Obama' and row['level'] != 'township']
        f.seek(0)
        romney_row = [row for row in reader if row['fipscode'] == fipscode and row['last'] == 'Romney' and row['level'] != 'township']

        if obama_row and romney_row:
            obama_result = obama_row[0]['votepct']
            romney_result = romney_row[0]['votepct']

            difference = (float(obama_result) * 100) - (float(romney_result) * 100)

            if difference > 0:
                margin = 'D +{0}'.format(round(difference))
            else:
                margin = 'R +{0}'.format(round(abs(difference)))

            return margin

        else:
            return None


def extract_unemployment_data(fipscode, filename):
    with open(filename) as f:
        reader = csv.DictReader(f)
        state_fips = fipscode[:2]
        county_fips = fipscode[-3:]
        unemployment_row = [row for row in reader if row['State FIPS Code'] == state_fips and row['County FIPS Code'] == county_fips]
        if unemployment_row:
            unemployment_rate = unemployment_row[0]['Unemployment Rate (%)']
            return float(unemployment_rate.strip())
        else:
            return None


@task
def save_old_data():
    state_results = models.Result.select(models.Result.statepostal).distinct().order_by(models.Result.statepostal)

    for state_result in state_results:
        state = state_result.statepostal
        print('getting', state)
        output = {}

        with open('data/census/{0}.json'.format(state)) as c:
            census_json = json.load(c)

        fips_results = models.Result.select(models.Result.fipscode).distinct().where(models.Result.statepostal == state, models.Result.fipscode is not None).order_by(models.Result.fipscode)
        for result in fips_results:
            print('extracting', result.fipscode)

            unemployment = extract_unemployment_data(result.fipscode, 'data/unemployment.csv')
            past_margin = extract_2012_data(result.fipscode, 'data/twentyTwelve.csv')
            census = extract_census_data(result.fipscode, census_json)

            this_row = {
                'unemployment': unemployment,
                'past_margin': past_margin,
                'census': census
            }

            output[result.fipscode] = this_row

        with open('data/extra_data/{0}-extra.json'.format(state.lower()), 'w') as datafile:
            json.dump(output, datafile)

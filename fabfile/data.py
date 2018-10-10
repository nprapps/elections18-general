#!/usr/bin/env python

"""
Commands that update or process the application data.
"""
import app_config
import csv
import json
import logging
import math
import os
import re
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


def get_valid_filename(s):
    """
    Return the given string converted to a string that can be used for a clean
    filename. Remove leading and trailing spaces; convert other spaces to
    underscores; and remove anything that is not an alphanumeric, dash,
    underscore, or dot.
    >>> get_valid_filename("john's portrait in 2004.jpg")
    'johns_portrait_in_2004.jpg'

    Function sourced from Django 2.1
    https://github.com/django/django/blob/master/django/utils/text.py
    """
    s = str(s).strip().replace(' ', '_')
    return re.sub(r'(?u)[^-\w.]', '', s)


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
                RESULTS_FILENAME_PREFIX + get_valid_filename(flag_set) + '.csv'
            )
        )
        for flag_set in flag_sets
    ]

    with shell_env(**app_config.database):
        for cmd in cmds:
            # The `warn_only` option turns errors into warning messages
            # This allows us to handle errors on our own terms,
            # like the `64` code below
            with settings(warn_only=True), hide('output', 'running'):
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
                    RESULTS_FILENAME_PREFIX + get_valid_filename(flag_set) + '.csv'
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
    governor_sheet = calendar['governorships']
    ballot_measure_sheet = calendar['ballot_measures']

    results = models.Result.select()
    for result in results:
        meta_obj = {
            'result_id': result.id
        }

        if result.level == 'county' or result.level == 'township':
            continue

        if (result.level == 'state' or result.level == 'district') \
                and result.statepostal != 'US':
            calendar_row = list(filter(lambda x: x['key'] == result.statepostal, calendar_sheet))[0]

            meta_obj['poll_closing'] = calendar_row['time_est']
            meta_obj['first_results'] = calendar_row['first_results_est']
            meta_obj['full_poll_closing'] = calendar_row['time_all_est']

        # Ignore special House elections, to avoid mis-assigning metadata
        # These races should still get the poll metadata from above
        if result.level == 'state' and \
                result.officename == 'U.S. House' and \
                not result.is_special_election:
            seat = '{0}-{1}'.format(result.statepostal, result.seatnum)
            house_rows = list(filter(
                lambda x: x['seat'] == seat,
                house_sheet
            ))
            assert len(house_rows) == 1, "Could not properly match Result to House spreadsheet"
            house_row = house_rows[0]

            meta_obj['current_party'] = house_row['party']
            # Handle non-voting members that are tracked in our visuals,
            # such as DC's House representative
            meta_obj['voting_member'] = (house_row['voting_member'] == 'True')
            meta_obj['key_race'] = (house_row['key_race'] == 'True')

        if result.level == 'state' and result.officename == 'U.S. Senate':
            senate_rows = list(filter(
                # Make sure to assign special election metadata accurately
                # This doesn't need to happen for any other office type,
                # since no other office has special elections that matter
                # _and_ has multiple seats per state
                lambda x: x['state'] == result.statepostal and result.is_special_election == (x['special'] == 'True'),
                senate_sheet
            ))
            assert len(senate_rows) == 1, "Could not properly match Result to Senate spreadsheet"
            senate_row = senate_rows[0]
            meta_obj['current_party'] = senate_row['party']

        if result.level == 'state' and result.officename == 'Governor':
            governor_rows = list(filter(
                lambda x: x['state'] == result.statepostal,
                governor_sheet
            ))
            assert len(governor_rows) == 1, "Could not properly match Result to governor spreadsheet"
            governor_row = governor_rows[0]
            meta_obj['current_party'] = governor_row['party']

        if result.level == 'state' and result.is_ballot_measure:
            measure_rows = list(filter(
                lambda x: x['state'] == result.statepostal and x['raceid'] == result.raceid,
                ballot_measure_sheet
            ))
            assert len(measure_rows) == 1, "Could not properly match Result to ballot-measure spreadsheet"
            measure_row = measure_rows[0]
            meta_obj['ballot_measure_theme'] = measure_row['big_board_theme']

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
def write_unemployment_csv(start_state='AA'):
    """
    Write county-level unemployment data to data/unemployment.csv.
    Will overwrite anything that was there.

    Assumes you have a document in data/unemployment.tsv
    that is similar to https://www.bls.gov/lau/laucnty17.txt
    which was found at https://www.bls.gov/lau/#cntyaa
    """
    pass
    # LAUS Code,State FIPS Code,County FIPS Code,County Name/State Abbreviation,Year,Labor Force,Employed,Unemployed,Unemployment Rate (%)
    # CN0100100000000,01,001,"Autauga County, AL",2015,"25,308     ","23,981     ","1,327     ",5.2
    # CN0100300000000,01,003,"Baldwin County, AL",2015,"87,316     ","82,525     ","4,791     ",5.5

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
        count = 0
        total = len(fips_results)
        for result in fips_results:
            if result.fipscode:
                count += 1
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
                    print('fipscode succeeded', result.fipscode, count, 'counties done, out of', total, 'in', state)
                    output[result.fipscode] = response.json()
                    sleep(1)
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


def extract_margin_data(fipscode, filename):
    """
    Called by save_old_data()
    Relies on a spreadsheet that looks something like this https://raw.githubusercontent.com/nprapps/elections16-general/master/data/twentyTwelve.csv
    This is the postgres query used in 2016 to get 2012 results
    \copy (SELECT * FROM result WHERE level = 'national' AND officename = 'President') to './prior.csv' with csv

    This is the elex command that also works, assuming you have `AP_API_KEY` set in your env and csvkit installed on your machine:
    $ elex results 2016-11-08 --results-level fipscode --officeids P | csvcut -c fipscode,level,precinctsreportingpct,last,votepct
    """
    # Candidate one must be the democratic nominee
    candidate_one = 'Clinton'
    candidate_two = 'Trump'
    with open(filename) as f:
        reader = csv.DictReader(f)
        candidate_one_row = [row for row in reader if row['fipscode'] == fipscode and row['last'] == candidate_one and row['level'] != 'township']
        f.seek(0)
        candidate_two_row = [row for row in reader if row['fipscode'] == fipscode and row['last'] == candidate_two and row['level'] != 'township']

        if candidate_one_row and candidate_two_row:
            one_result = candidate_one_row[0]['votepct']
            two_result = candidate_two_row[0]['votepct']

            difference = (float(one_result) * 100) - (float(two_result) * 100)

            if difference > 0:
                margin = 'D +{0}'.format(round(difference))
            else:
                margin = 'R +{0}'.format(round(abs(difference)))

            return margin

        else:
            return None


def extract_unemployment_data(fipscode, filename):
    """
    Called by save_old_data()
    The unemployment.csv data is pulled from https://www.bls.gov/lau/#tables, which is a long page full of links.
    Look for COUNTY DATA --> TABLES --> Labor force data by county 
    Take the latest txt file (this is the one we used in 2018: https://www.bls.gov/lau/laucnty17.txt)
    and turn it into a CSV that looks like data/unemployment.csv in this repo.
    """
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
    """
    Must run get_census_data() before running this.
    """
    state_results = models.Result.select(models.Result.statepostal).distinct().order_by(models.Result.statepostal)

    for state_result in state_results:
        state = state_result.statepostal
        print('getting', state)
        output = {}

        with open('data/census/{0}.json'.format(state)) as c:
            census_json = json.load(c)

        fips_results = models.Result.select(models.Result.fipscode).distinct().where(models.Result.statepostal == state, models.Result.fipscode is not None).order_by(models.Result.fipscode)

        for result in fips_results:
            if not result.fipscode:
                print('No FIPSCODE')
                continue
            print('extracting', result.fipscode)

            unemployment = extract_unemployment_data(result.fipscode, 'data/unemployment.csv')
            past_margin = extract_margin_data(result.fipscode, 'data/2016-presidential.csv')
            census = extract_census_data(result.fipscode, census_json)

            this_row = {
                'unemployment': unemployment,
                'past_margin': past_margin,
                'census': census
            }

            output[result.fipscode] = this_row

        with open('data/extra_data/{0}-extra.json'.format(state.lower()), 'w') as datafile:
            json.dump(output, datafile)

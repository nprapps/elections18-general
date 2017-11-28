#!/usr/bin/env python

"""
Commands that update or process the application data.
"""
import app_config
import copytext
import csv
import logging
import math
import simplejson as json
import yaml
import requests

from oauth import get_document
from fabric.api import execute, hide, local, task, settings, shell_env
from fabric.state import env
from models import models
from time import sleep

CENSUS_REPORTER_URL = 'http://api.censusreporter.org/1.0/data/show/acs2014_5yr'
FIPS_TEMPLATE = '05000US{0}'
CENSUS_TABLES = ['B01003', 'B02001', 'B03002', 'B19013', 'B15001']

logging.basicConfig(format=app_config.LOG_FORMAT)
logger = logging.getLogger(__name__)
logger.setLevel(app_config.LOG_LEVEL)

@task
def bootstrap_db():
    """
    Build the database.
    """
    create_db()
    create_tables()
    load_results('init')
    create_calls()
    create_race_meta()

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
    models.RaceMeta.create_table()

@task
def delete_results(mode):
    """
    Delete results without droppping database.
    """
    if mode == 'fast':
        where_clause = "WHERE level = 'state' OR level = 'national' OR level = 'district'"
    elif mode == 'slow':
        where_clause = "WHERE officename = 'President'"
    else:
        where_clause = ''

    with shell_env(**app_config.database), hide('output', 'running'):
        local('psql {0} -c "set session_replication_role = replica; DELETE FROM result {1}; set session_replication_role = default;"'.format(app_config.database['PGDATABASE'], where_clause))

@task
def load_results(mode):
    """
    Load AP results. Defaults to next election, or specify a date as a parameter.
    """

    if mode == 'fast':
        flags = app_config.FAST_ELEX_FLAGS
    elif mode == 'slow':
        flags = app_config.SLOW_ELEX_FLAGS
    else:
        flags = app_config.ELEX_INIT_FLAGS

    election_date = app_config.NEXT_ELECTION_DATE
    with hide('output', 'running'):
        local('mkdir -p {0}'.format(app_config.ELEX_OUTPUT_FOLDER))

    cmd = 'elex results {0} {1} > {2}/first_query.csv'.format(election_date, flags, app_config.ELEX_OUTPUT_FOLDER)
    districts_cmd = 'elex results {0} {1} | csvgrep -c level -m district > {2}/districts.csv'.format(election_date, app_config.ELEX_DISTRICTS_FLAGS, app_config.ELEX_OUTPUT_FOLDER)

    with shell_env(**app_config.database):
        with settings(warn_only=True), hide('output', 'running'):
            first_cmd_output = local(cmd, capture=True)

        if first_cmd_output.succeeded or first_cmd_output.return_code == 64:
            with hide('output', 'running'):
                district_cmd_output = local(districts_cmd, capture=True)

            if district_cmd_output.succeeded or district_cmd_output.return_code == 64:
                delete_results(mode)
                with hide('output', 'running'):
                    local('csvstack {0}/first_query.csv {1}/districts.csv | psql {2} -c "COPY result FROM stdin DELIMITER \',\' CSV HEADER;"'.format(app_config.ELEX_OUTPUT_FOLDER, app_config.ELEX_OUTPUT_FOLDER, app_config.database['PGDATABASE']))

            else:
                print("ERROR GETTING DISTRICT RESULTS")
                print(district_cmd_output.stderr)

        else:
            print("ERROR GETTING MAIN RESULTS")
            print(first_cmd_output.stderr)

    logger.info('results loaded')

@task
def create_calls():
    """
    Create database of race calls for all races in results data.
    """
    models.Call.delete().execute()

    results = models.Result.select().where(
        (models.Result.level == 'state') | (models.Result.level == 'national') | (models.Result.level == 'district')
    )

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
    execute('render.render_all')

    if app_config.NEXT_ELECTION_DATE[:4] == '2012':
        graphics_folder = '../elections16graphics/www/2012/data/'
    else:
        graphics_folder = '../elections16graphics/www/data/'

    local('cp -r {0}/* {1}'.format(app_config.DATA_OUTPUT_FOLDER, graphics_folder))

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
            print('skipping', state)
            continue

        print('getting', state)
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

        fips_results = models.Result.select(models.Result.fipscode).distinct().where(models.Result.statepostal == state, models.Result.fipscode != None).order_by(models.Result.fipscode)
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

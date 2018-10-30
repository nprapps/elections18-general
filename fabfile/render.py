import app_config
import logging
import multiprocessing
import os
import re
import shutil
import simplejson as json
import copytext

from datetime import datetime
from fabric.api import task
from joblib import Parallel, delayed
from models import models
from playhouse.shortcuts import model_to_dict
from tidylib import tidy_fragment

from . import utils

logging.basicConfig(format=app_config.LOG_FORMAT)
logger = logging.getLogger(__name__)
logger.setLevel(app_config.LOG_LEVEL)

NUM_CORES = multiprocessing.cpu_count() * 4

COMMON_SELECTIONS = [
    models.Result.first,
    models.Result.last,
    models.Result.candidateid,
    models.Result.lastupdated,
    models.Result.level,
    models.Result.officename,
    models.Result.party,
    models.Result.precinctsreporting,
    models.Result.precinctsreportingpct,
    models.Result.precinctstotal,
    models.Result.raceid,
    models.Result.statename,
    models.Result.statepostal,
    models.Result.votepct,
    models.Result.votecount,
    models.Result.winner
]

HOUSE_SELECTIONS = COMMON_SELECTIONS + [
    models.Result.incumbent,
    models.Result.runoff,
    models.Result.seatname,
    models.Result.seatnum,
    models.Result.meta
]

SENATE_SELECTIONS = COMMON_SELECTIONS + [
    models.Result.incumbent,
    models.Result.runoff,
    models.Result.meta,
    # `peewee` chokes when using `model_to_dict` with hybrid expressions,
    # so address this selection as a string instead
    'is_special_election'
]

GOVERNOR_SELECTIONS = COMMON_SELECTIONS + [
    models.Result.incumbent,
    models.Result.meta
]

BALLOT_MEASURE_SELECTIONS = COMMON_SELECTIONS + [
    models.Result.officename,
    models.Result.seatname,
    models.Result.is_ballot_measure,
    models.Result
]

COUNTY_SELECTIONS = COMMON_SELECTIONS + [
    models.Result.reportingunitname,
    models.Result.fipscode
]

CALLS_SELECTIONS = [
    models.Call.accept_ap,
    models.Call.override_winner
]

RACE_META_SELECTIONS = [
    models.RaceMeta.poll_closing,
    models.RaceMeta.full_poll_closing,
    models.RaceMeta.current_party,
    models.RaceMeta.key_race,
    models.RaceMeta.ballot_measure_theme
]

MAJOR_CANDIDATE_PARTIES = ['Dem', 'GOP']

# Number of candidates ideally in each statewide and county table
# This can be overridden by specifying exactly which candidates are
# desired, in `app_config`
TARGET_CANDIDATE_LIST_LENGTH = 2

SELECTIONS_LOOKUP = {
    'governor': GOVERNOR_SELECTIONS,
    'senate': SENATE_SELECTIONS,
    'house': HOUSE_SELECTIONS,
    'ballot_measures': BALLOT_MEASURE_SELECTIONS
}

OFFICENAME_LOOKUP = {
    'senate': 'U.S. Senate',
    'governor': 'Governor'
}


def _select_county_results(statepostal, office):
    results = models.Result.select().where(
        (models.Result.level == 'county') | (models.Result.level == 'state'),
        models.Result.officename == OFFICENAME_LOOKUP[office],
        models.Result.statepostal == statepostal
    )

    return results


def _select_governor_results():
    results = models.Result.select().where(
        models.Result.level == 'state',
        models.Result.officename == 'Governor'
    )

    return results


def _select_selected_house_results():
    results = models.Result.select().join(models.RaceMeta).where(
        models.Result.level == 'state',
        models.Result.officename == 'U.S. House',
        models.RaceMeta.key_race
    )

    return results


def _select_all_house_results():
    results = models.Result.select().join(models.RaceMeta).where(
        models.Result.level == 'state',
        models.Result.officename == 'U.S. House',
        ~(models.Result.is_special_election),
        models.RaceMeta.voting_member
    )

    return results


def _select_senate_results():
    # These results are only used for BoP calculation and big board,
    # so they don't need to take `is_special_election` into account
    results = models.Result.select().where(
        models.Result.level == 'state',
        models.Result.officename == 'U.S. Senate'
    )

    return results


def _select_ballot_measure_results():
    results = models.Result.select().join(models.RaceMeta).where(
        models.Result.level == 'state',
        models.Result.is_ballot_measure,
        models.RaceMeta.ballot_measure_theme != ''
    )

    return results


@task
def render_top_level_numbers():
    # init with parties that already have seats

    # Set which party controls the vice presidency, who determines
    # ties in Senate votes
    SENATE_TIE_GOES_TO = 'GOP'
    # For determining chamber control, dictate which party the
    # independents/others caucus with
    SENATE_THIRD_PARTIES_COUNT_TOWARDS = 'Dem'
    senate_bop = {
        'total_seats': 100,
        'uncalled_races': 35,
        'last_updated': None,
        'npr_winner': None,
        'Dem': {
            'seats': 23,
            'pickups': 0
        },
        'GOP': {
            'seats': 42,
            'pickups': 0
        },
        'Other': {
            'seats': 0,
            'pickups': 0
        }
    }

    house_bop = {
        'total_seats': 435,
        'uncalled_races': 435,
        'last_updated': None,
        'npr_winner': None,
        'Dem': {
            'seats': 0,
            'pickups': 0
        },
        'GOP': {
            'seats': 0,
            'pickups': 0
        },
        'Other': {
            'seats': 0,
            'pickups': 0
        }
    }

    senate_results = _select_senate_results()
    house_results = _select_all_house_results()

    for result in senate_results:
        _calculate_bop(result, senate_bop)
    _calculate_chamber_control(
        senate_bop,
        tie_goes_to=SENATE_TIE_GOES_TO,
        third_parties_count_towards=SENATE_THIRD_PARTIES_COUNT_TOWARDS,
        override=senate_results.first().meta.first().chamber_call_override
    )

    for result in house_results:
        _calculate_bop(result, house_bop)
    _calculate_chamber_control(
        house_bop,
        override=house_results.first().meta.first().chamber_call_override
    )

    last_updated = None
    if senate_bop['last_updated'] and house_bop['last_updated']:
        last_updated = max(
            senate_bop['last_updated'],
            house_bop['last_updated']
        )
    else:
        last_updated = senate_bop['last_updated'] or \
            house_bop['last_updated'] or \
            datetime.utcnow()

    data = {
        'senate_bop': senate_bop,
        'house_bop': house_bop,
        'last_updated': last_updated
    }

    _write_json_file(data, 'top-level-results.json')


@task
def render_get_caught_up():
    '''
    Render the prose for the get-caught-up info box
    The Google Sheet that powers this will be regularly re-downloaded
    '''
    copy = copytext.Copy(app_config.CALENDAR_PATH)
    sheet = copy['get_caught_up']
    serialized_data = json.loads(sheet.json())

    is_valid = True
    markup_fields = ['intro_1', 'intro_2', 'bullet_1', 'bullet_2', 'bullet_3', 'bullet_4', 'bullet_5']
    markup_errors_found = None
    # Note that despite its name, tidy_fragment() requires a valid html document or else
    # it will throw markup validation errors. The documentation at http://countergram.github.io/pytidylib/
    # did not address this seeming discrepancy.
    for field in markup_fields:
        document, errors = tidy_fragment('<!DOCTYPE html><html><head><title>test</title></head><body>%s</body></html>' % serialized_data[field])
        if errors:
            is_valid = False
            markup_errors_found = errors
            break

    # Don't publish if that option is off, or if a syntax error is found
    if serialized_data.get('published', '').lower() == 'yes' and is_valid:
        meta = {
            'is_valid_markup': is_valid,
            'published': serialized_data['published'],
            'last_updated': datetime.utcnow()
        }
        content = {k: v.strip() for k, v in serialized_data.items() if k in markup_fields}

        _write_json_file(
            {'meta': meta, 'content': content},
            'get-caught-up.json'
        )

    # Publish a debug version to help editors gauge length of content
    # If there are no markup errors and `published` is `True`, the contents
    # of this file will be identical to that of the main GCU file
    meta = {
        'is_valid_markup': is_valid,
        'published': serialized_data['published'],
        'last_updated': datetime.utcnow()
    }
    content = {
        k: v.strip()
        for k, v in serialized_data.items()
        if k in markup_fields
    } if is_valid else "The HTML markup is invalid. Errors:\n{}".format(markup_errors_found)

    _write_json_file(
        {'meta': meta, 'content': content},
        'get-caught-up-debug.json'
    )


@task
def render_county_results(office, special=False):
    states = models.Result.select(models.Result.statepostal).distinct()

    # `joblib.Parallel` was choking on the `special` argument, for
    # some reason. Could not expediently debug, so switching back to
    # serial processing for the counties.
    for state in states:
        _render_county(state.statepostal, office, special=special)


def _render_county(statepostal, office, special=False):
    # `peewee` is having trouble using hybrid properties in its
    # result filtering with a passed parameter (`special`), so
    # for now we'll perform a Pythonic filtering to apply the
    # `special` argument
    unfiltered_results = _select_county_results(statepostal, office)
    results = [result for result in unfiltered_results if result.is_special_election == special]
    serialized_results = _serialize_by_key(results, COUNTY_SELECTIONS, 'fipscode', collate_other=True)

    # No need to render if the state doesn't have that type of race
    if serialized_results['results']:
        filename = '{0}-counties-{1}{2}.json'.format(
            statepostal.lower(),
            office,
            '-special' if special else ''
        )
        _write_json_file(serialized_results, filename)


@task
def render_governor_results():
    results = _select_governor_results()

    serialized_results = _serialize_for_big_board(results, GOVERNOR_SELECTIONS)
    _write_json_file(serialized_results, 'governor-national.json')


@task
def render_house_results():
    results = _select_selected_house_results()

    serialized_results = _serialize_for_big_board(results, HOUSE_SELECTIONS)
    _write_json_file(serialized_results, 'house-national.json')


@task
def render_senate_results():
    results = _select_senate_results()

    serialized_results = _serialize_for_big_board(results, SENATE_SELECTIONS)
    _write_json_file(serialized_results, 'senate-national.json')


@task
def render_ballot_measure_results():
    results = _select_ballot_measure_results()

    serialized_results = _serialize_for_big_board(results, BALLOT_MEASURE_SELECTIONS, bucket_key='ballot_measure_theme')
    _write_json_file(serialized_results, 'ballot-measures-national.json')


@task
def render_state_results():
    states = models.Result.select(models.Result.statepostal).distinct()

    Parallel(n_jobs=NUM_CORES)(delayed(_render_state)(state.statepostal) for state in states)


def _render_state(statepostal):
    with models.db.execution_context() as ctx:
        # This will include both regular and special Senate elections
        senate = models.Result.select().where(
            models.Result.level == 'state',
            models.Result.officename == 'U.S. Senate',
            models.Result.statepostal == statepostal
        )
        house = models.Result.select().where(
            models.Result.level == 'state',
            models.Result.officename == 'U.S. House',
            models.Result.statepostal == statepostal,
            ~(models.Result.is_special_election)
        )
        governor = models.Result.select().where(
            models.Result.level == 'state',
            models.Result.officename == 'Governor',
            models.Result.statepostal == statepostal
        )
        ballot_measures = models.Result.select().join(models.RaceMeta).where(
            models.Result.level == 'state',
            models.Result.is_ballot_measure,
            models.Result.statepostal == statepostal,
            # Only include key ballot initiatives, even on state pages
            models.RaceMeta.ballot_measure_theme != ''
        )

        state_results = {
            'results': {},
            'last_updated': None
        }
        queries = [senate, house, governor, ballot_measures]
        for query in queries:
            results_key = [k for k, v in locals().items() if v is query and k != 'query'][0]
            selectors = SELECTIONS_LOOKUP[results_key]
            state_results['results'][results_key] = _serialize_by_key(query, selectors, 'raceid', collate_other=True)
            if not state_results['last_updated'] or state_results['results'][results_key]['last_updated'] > state_results['last_updated']:
                state_results['last_updated'] = state_results['results'][results_key]['last_updated']

        filename = '{0}.json'.format(statepostal.lower())
        _write_json_file(state_results, filename)


uncallable_levels = ['county', 'township']
pickup_offices = ['U.S. House', 'U.S. Senate']


def categorize_selections(selections):
    # `peewee` chokes when using `model_to_dict` with hybrid expressions,
    # so these selections should be passed as a string instead
    regular_selections = []
    hybrid_selections = []
    for selection in selections:
        if type(selection) == str:
            hybrid_selections.append(selection)
        else:
            regular_selections.append(selection)
    return regular_selections, hybrid_selections


def _serialize_for_big_board(results, selections, key='raceid', bucket_key='poll_closing'):
    serialized_results = {
        'results': {}
    }

    regular_selections, hybrid_selections = categorize_selections(selections)

    for result in results:
        result_dict = model_to_dict(result, backrefs=True, only=regular_selections, extra_attrs=hybrid_selections)

        if result.level not in uncallable_levels:
            _set_meta(result, result_dict)
            if result.officename in pickup_offices:
                _set_pickup(result, result_dict)

        if key == 'statepostal' and result.reportingunitname:
            m = re.search(r'\d$', result.reportingunitname)
            if m is not None:
                dict_key = '{0}-{1}'.format(result.statepostal, m.group())
            else:
                dict_key = result.statepostal
        else:
            dict_key = result_dict[key]

        bucket_value = getattr(result.meta.first(), bucket_key)
        if not serialized_results['results'].get(bucket_value):
            serialized_results['results'][bucket_value] = {}

        bucketed = serialized_results['results'][bucket_value]
        if not bucketed.get(dict_key):
            bucketed[dict_key] = []
        bucketed[dict_key].append(result_dict)

    serialized_results['last_updated'] = get_last_updated(serialized_results)
    # Run through other-collation mostly to allow candidate overrides,
    # via `app_config.CANDIDATE_SET_OVERRIDES`, when a race has no votes yet
    for bucket_value in serialized_results['results'].keys():
        for race_key, results_for_a_race in serialized_results['results'][bucket_value].items():
            serialized_results['results'][bucket_value][race_key] = collate_other_candidates(
                results_for_a_race,
                for_big_boards=True
            )
    return serialized_results


def _serialize_by_key(results, selections, key, collate_other=False):
    with models.db.execution_context():
        serialized_results = {
            'results': {}
        }

        regular_selections, hybrid_selections = categorize_selections(selections)

        for result in results:
            result_dict = model_to_dict(result, backrefs=True, only=regular_selections, extra_attrs=hybrid_selections)

            if result.level not in uncallable_levels:
                _set_meta(result, result_dict)
                if result.officename in pickup_offices:
                    _set_pickup(result, result_dict)

            # handle state results in the county files
            if key == 'fipscode' and result.level == 'state':
                dict_key = 'state'
            else:
                dict_key = result_dict[key]

            if not serialized_results['results'].get(dict_key):
                serialized_results['results'][dict_key] = []

            serialized_results['results'][dict_key].append(result_dict)

        serialized_results['last_updated'] = get_last_updated(serialized_results)

        if collate_other:
            # Make sure that all county-table rows have the same set of
            # candidates, as determined by the top candidates in the state
            state_level_candidateids = None
            if key == 'fipscode' and serialized_results['results']:
                state_results = serialized_results['results']['state']
                state_level_candidateids = [
                    c['candidateid'] for c in
                    collate_other_candidates(state_results)
                    if c['last'] != 'Other'
                ]
            for race_key, results_for_a_race in serialized_results['results'].items():
                serialized_results['results'][race_key] = collate_other_candidates(
                    results_for_a_race,
                    candidates_override=state_level_candidateids
                )

        return serialized_results


def _set_meta(result, result_dict):
    meta = models.RaceMeta.get(models.RaceMeta.result_id == result.id)
    result_dict['meta'] = model_to_dict(meta, only=RACE_META_SELECTIONS)
    result_dict['npr_winner'] = result.is_npr_winner()


def _set_pickup(result, result_dict):
    result_dict['pickup'] = result.is_pickup()


def _calculate_bop(result, bop):
    party = result.party if result.party in MAJOR_CANDIDATE_PARTIES else 'Other'
    if result.is_npr_winner():
        bop[party]['seats'] += 1
        bop['uncalled_races'] -= 1

    if result.is_pickup():
        picked_up_from = result.meta.first().current_party
        picked_up_from = picked_up_from if picked_up_from in MAJOR_CANDIDATE_PARTIES else 'Other'
        bop[party]['pickups'] += 1
        bop[picked_up_from]['pickups'] -= 1

    if not bop['last_updated'] or result.lastupdated > bop['last_updated']:
        bop['last_updated'] = result.lastupdated


def _calculate_chamber_control(bop, tie_goes_to=None, third_parties_count_towards=None, override=None):
    '''
    Determine which party is in control of the chamber
    '''
    dem_count = bop['Dem']['seats'] + (bop['Other']['seats'] if third_parties_count_towards == 'Dem' else 0)
    gop_count = bop['GOP']['seats'] + (bop['Other']['seats'] if third_parties_count_towards == 'GOP' else 0)

    leading_party = None
    if dem_count == gop_count:
        leading_party = tie_goes_to
    elif dem_count > gop_count:
        leading_party = 'Dem'
    else:
        leading_party = 'GOP'

    half_of_seats = bop['total_seats'] / 2.
    if leading_party and bop[leading_party]['seats'] >= half_of_seats:
        bop['npr_winner'] = leading_party

    # Only use the override if no party is yet in control normally
    if not bop['npr_winner'] and override:
        bop['npr_winner'] = override


def _sort_when_no_votes_and_duplicated_parties(results):
    # Ensure that at least one major-party candidate is included
    # in the top results, if possible
    sorted_results = []

    one_candidate_per_party = {party: None for party in MAJOR_CANDIDATE_PARTIES}
    for candidate in results:
        if candidate['party'] in MAJOR_CANDIDATE_PARTIES:
            one_candidate_per_party[candidate['party']] = candidate
    sorted_results.extend(one_candidate_per_party.values())

    # Add back in any candidates that weren't included already
    for candidate in results:
        if candidate not in sorted_results:
            sorted_results.append(candidate)

    return results


def collate_other_candidates(results_for_a_race, for_big_boards=False, candidates_override=None):
    # Create an "Other" candidate, to simplify front-end visuals,
    # and minimize filesize of JSON dumps. This may be overridden
    # by `app_config.CANDIDATE_SET_OVERRIDES` if we want to explicitly
    # include a third-party candidate or similar.

    # Here's a list of which candidates should and should not be turned
    # into "Other"s, based on the parties that are coming in:

    # Standard competitive races:
    # - D,R,I,I,... -> D,R,Oth
    # - D,R -> D,R
    # - D,I -> D,I
    # - R,I -> R,I

    # Less likely, relatively uncontested races:
    # - D,I,I -> D,I,Oth
    # - R,I,I -> R,I,Oth

    # Top-two general election (eg, California or Louisiana):
    # - D,D -> D,D
    # - R,R -> R,R

    # Uncontested races:
    # - D -> D
    # - R -> R
    # - I -> I

    # "Jungle primary" races, such as in Louisiana or California, if votes present:
    # - D,R,R,D,I -> D,R,Oth
    # - D,I,R,D,I -> D,I,Oth
    # - R,R,R,R,D -> R,R,Oth

    # This won't happen for a top-of-ticket seat, but it's handled:
    # - I,I,I -> I,I,Oth
    # - I,I -> I,I

    BIG_BOARD_CANDIDATE_LIST_LENGTH = 2

    # Must check this, since `key` isn't always the `raceid`
    raceid = results_for_a_race[0]['raceid']
    candidates_override = app_config.CANDIDATE_SET_OVERRIDES.get(raceid, candidates_override)

    # Make sure that more prominent third-party candidates come first
    # But only order by votes if there are any votes in so far
    any_votes_yet = sum([r['votecount'] for r in results_for_a_race]) > 0
    if any_votes_yet:
        results_for_a_race.sort(key=lambda c: c['votecount'], reverse=True)
    else:
        # If there are no results yet, ensure that the main-party candidates
        # are ordered first; this ensures that they show up on the big board
        results_for_a_race.sort(key=lambda c: c['party'] in MAJOR_CANDIDATE_PARTIES, reverse=True)

        # Also, if there are multiple members of a particular party, make
        # sure that the first candidates are of different major parties,
        # so that the race doesn't appear to be single-party on the big boards
        if for_big_boards:
            parties = [r['party'] for r in results_for_a_race]
            major_parties = [p for p in parties if p in MAJOR_CANDIDATE_PARTIES]
            is_repeated_major_parties = len(major_parties) > len(set(major_parties))

            if is_repeated_major_parties and \
                    len(results_for_a_race) > BIG_BOARD_CANDIDATE_LIST_LENGTH:
                results_for_a_race = _sort_when_no_votes_and_duplicated_parties(results_for_a_race)

    other_votecount = 0
    other_votepct = 0
    other_winner = False
    filtered = []

    if candidates_override:
        for result in results_for_a_race:
            if result['candidateid'] in candidates_override:
                filtered.append(result)
            else:
                other_votecount += result['votecount']
                other_votepct += result['votepct']
                if result.get('npr_winner') is True:
                    other_winner = True
        # If no votes are present, reorder based on the sort-order
        # of the override setting
        if not any_votes_yet:
            resorted_filtered = []
            for candidateid in candidates_override:
                for result in filtered:
                    if result['candidateid'] == candidateid:
                        resorted_filtered.append(result)
                        break
            filtered = resorted_filtered
    else:
        for result in results_for_a_race:
            # This logic properly handles "jungle primaries" that have
            # many main-party candidates, as well as when there is only
            # one major-party candidate in the race
            if len(filtered) < TARGET_CANDIDATE_LIST_LENGTH:
                filtered.append(result)
            else:
                other_votecount += result['votecount']
                other_votepct += result['votepct']
                if result.get('npr_winner') is True:
                    other_winner = True

    # Don't create an "Other" if no candidates were amalgomated into it
    if len(results_for_a_race) > len(filtered) and not for_big_boards:
        filtered.append({
            'first': '',
            'last': 'Other',
            'votecount': other_votecount,
            'votepct': other_votepct,
            'npr_winner': other_winner
        })

    # Big boards should never show "Other"s, and have no need for
    # candidates that won't be shown
    if for_big_boards:
        filtered = filtered[:BIG_BOARD_CANDIDATE_LIST_LENGTH]

    return filtered


def get_last_updated(serialized_results):
    last_updated = None

    for key, val in serialized_results['results'].items():
        if isinstance(val, list):
            if val[0]['precinctsreporting'] > 0:
                for result in val:
                    if not last_updated or result['lastupdated'] > last_updated:
                        last_updated = result['lastupdated']

        elif isinstance(val, dict):
            for key, val in val.items():
                if val[0]['precinctsreporting'] > 0:
                    for result in val:
                        if not last_updated or result['lastupdated'] > last_updated:
                            last_updated = result['lastupdated']

    if not last_updated:
        last_updated = datetime.utcnow()

    return last_updated


def _write_json_file(serialized_results, filename):
    with open('{0}/{1}'.format(app_config.DATA_OUTPUT_FOLDER, filename), 'w') as f:
        json.dump(serialized_results, f, use_decimal=True, cls=utils.APDatetimeEncoder)


@task
def render_all():
    if os.path.isdir(app_config.DATA_OUTPUT_FOLDER):
        shutil.rmtree(app_config.DATA_OUTPUT_FOLDER)
    os.makedirs(app_config.DATA_OUTPUT_FOLDER)

    render_top_level_numbers()
    render_get_caught_up()

    render_senate_results()
    render_governor_results()
    render_ballot_measure_results()
    render_house_results()

    render_state_results()
    render_county_results('senate')
    render_county_results('senate', special=True)
    render_county_results('governor')

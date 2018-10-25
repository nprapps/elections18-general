import app_config
import app_utils
import datetime
import logging
import static

from app_utils import comma_filter, percent_filter, open_db, close_db, never_cache_preview
from flask import Flask, make_response, render_template
from flask_admin import Admin
from flask_admin.contrib.peewee import ModelView
from models import models
from render_utils import make_context, smarty_filter, urlencode_filter
from werkzeug.contrib.profiler import ProfilerMiddleware
from werkzeug.debug import DebuggedApplication

app = Flask(__name__)
app.debug = app_config.DEBUG
secrets = app_config.get_secrets()
app.secret_key = secrets.get('FLASK_SECRET_KEY')

app.add_template_filter(comma_filter, name='comma')
app.add_template_filter(percent_filter, name='percent')


try:
    file_handler = logging.FileHandler('%s/admin_app.log' % app_config.SERVER_LOG_PATH)
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
except IOError:
    print('Could not open %s/admin_app.log, skipping file-based logging' % app_config.SERVER_LOG_PATH)

app.logger.setLevel(logging.INFO)

app.register_blueprint(static.static, url_prefix='/%s' % app_config.PROJECT_SLUG)

app.add_template_filter(smarty_filter, name='smarty')
app.add_template_filter(urlencode_filter, name='urlencode')

admin = Admin(app, url='/%s/admin' % app_config.PROJECT_SLUG)
admin.add_view(ModelView(models.Result))
admin.add_view(ModelView(models.Call))
admin.add_view(ModelView(models.RaceMeta))

SLUG_TO_OFFICENAME = {
    'senate': 'U.S. Senate',
    'house': 'U.S. House',
    'governor': 'Governor'
}


@app.route('/%s/calls/<office>/' % app_config.PROJECT_SLUG, methods=['GET'])
def calls_admin(office):
    officename = SLUG_TO_OFFICENAME[office]

    # This value will be the same for all seats in a chamber, so pick
    # an arbitrary one
    chamber_call_override = models.RaceMeta.select(
        models.RaceMeta.chamber_call_override
    ).join(
        models.Result
    ).where(
        models.Result.officename == SLUG_TO_OFFICENAME[office]
    ).scalar()

    results = app_utils.get_results(officename)

    if not results:
        # Occasionally, the database will erroneously return zero races
        # Handle this by signaling a server error
        # See https://github.com/nprapps/elections18-general/issues/24
        return 'Server error; failed to fetch results from database', 500

    context = make_context(asset_depth=1)
    context.update({
        'officename': officename,
        'chamber_call_override': chamber_call_override,
        'offices': SLUG_TO_OFFICENAME,
        'races': results
    })

    return make_response(render_template('calls.html', **context))


@app.route('/%s/calls/<office>/call-chamber' % app_config.PROJECT_SLUG, methods=['POST'])
def call_chamber(office):
    '''
    Set an override for control of a legislative chamber, separate
    from calling any individual seat
    '''
    from flask import request

    # Passing `null` in the `POST`ed data does not register as `None`
    # in Flask, so cast it as such
    call = request.form.get('call') or None

    result_ids_for_chamber = models.Result.select(models.Result.id).where(models.Result.officename == SLUG_TO_OFFICENAME[office])
    update = models.RaceMeta.update(chamber_call_override=call).where(models.RaceMeta.result_id_id << result_ids_for_chamber)
    update.execute()

    return 'Success', 200


@app.route('/%s/calls/<office>/call-npr' % app_config.PROJECT_SLUG, methods=['POST'])
def call_npr(office):
    from flask import request

    result_id = request.form.get('result_id')

    result = models.Result.get(models.Result.id == result_id)
    call = result.call[0]
    if call.override_winner:
        call.override_winner = False
    else:
        call.override_winner = True

    call.save()

    race_id = result.raceid
    statepostal = result.statepostal
    officename = result.officename
    level = result.level
    reportingunitname = result.reportingunitname

    race_results = models.Result.select().where(
        models.Result.level == level,
        models.Result.raceid == race_id,
        models.Result.officename == officename,
        models.Result.statepostal == statepostal,
        models.Result.reportingunitname == reportingunitname
    )

    for race_result in race_results:
        race_call = race_result.call[0]
        if call.override_winner:
            race_call.accept_ap = False

        if race_call.call_id != call.call_id:
            race_call.override_winner = False

        race_call.save()

    return 'Success', 200


@app.route('/%s/calls/<office>/accept-ap' % app_config.PROJECT_SLUG, methods=['POST'])
def accept_ap(office):
    from flask import request

    officename = SLUG_TO_OFFICENAME[office]

    race_id = request.form.get('race_id')
    statepostal = request.form.get('statepostal')
    reportingunit = request.form.get('reportingunit')
    level = request.form.get('level')

    if level == 'district':
        results = models.Result.select().where(
            models.Result.level == 'district',
            models.Result.raceid == race_id,
            models.Result.officename == officename,
            models.Result.statepostal == statepostal,
            models.Result.reportingunitname == reportingunit
        )
    else:
        results = models.Result.select().where(
            (models.Result.level == 'state') | (models.Result.level == 'national'),
            models.Result.raceid == race_id,
            models.Result.officename == officename,
            models.Result.statepostal == statepostal,
        )

    for result in results:
        call = result.call[0]
        if call.accept_ap:
            call.accept_ap = False
        else:
            call.accept_ap = True
        call.save()

    return 'Success', 200


@app.route('/%s/test/' % app_config.PROJECT_SLUG, methods=['GET'])
def _test_app():
    """
    Test route for verifying the application is running.
    """
    app.logger.info('Test URL requested.')

    return make_response(datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))


app.before_request(open_db)
app.after_request(close_db)
app.after_request(never_cache_preview)

# Enable Werkzeug debug pages, and add a performance profiler
if app_config.DEBUG:
    app.config['PROFILE'] = True
    app.wsgi_app = ProfilerMiddleware(app.wsgi_app, restrictions=[10])
    wsgi_app = DebuggedApplication(app, evalex=False)
else:
    wsgi_app = app

elections18-general
===================

* [What is this?](#what-is-this)
* [Assumptions and Requirements](#assumptions-and-requirements)
* [What's in here?](#whats-in-here)
* [Data flow](#data-flow)
* [Output JSON](#output-json)
* [Configuration](#configuration)
* [Hide project secrets](#hide-project-secrets)
* [Save media assets](#save-media-assets)
* [Add a page to the site](#add-a-page-to-the-site)
* [Provisioning servers](#provisioning-servers)
* [Deployment](#deployment)
* [Run the project](#run-the-project)
* [Admin interface](#admin-interface)
* [COPY configuration](#copy-configuration)
* [COPY editing](#copy-editing)
* [Open Linked Google Spreadsheet](#open-linked-google-spreadsheet)
* [Generating custom font](#generating-custom-font)
* [Arbitrary Google Docs](#arbitrary-google-docs)
* [Run Python tests](#run-python-tests)
* [Run Javascript tests](#run-javascript-tests)
* [Compile static assets](#compile-static-assets)
* [Test the rendered app](#test-the-rendered-app)
* [Install web services](#install-web-services)
* [Run a remote fab command](#run-a-remote-fab-command)

What is this?
-------------

The backend for NPR's 2018 miderm general-election coverage. It includes an Associated Press data ETL, database, admin panel, and produces JSON output for use on the front-end. It is an iteration upon the 2016 GE and the 2017 Alabama special-election work.


Assumptions and Requirements
-----------

### Platform and software

* macOS
* Python 3
* Node.js 8
* [`virtualenv`](https://pypi.python.org/pypi/virtualenv) and [`virtualenvwrapper`](https://pypi.python.org/pypi/virtualenvwrapper)
* `awscli`

### Environment variables

* NPR's AWS credentials, as `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` (`AWS_PROFILE` not supported)
* [AP Elections Results API key](http://elex.readthedocs.io/en/stable/install.html#automatically-set-your-api-key), as `AP_API_KEY`

Additional optional environment variables are described later.

What's in here?
---------------

The project contains the following folders and important files:

* [``confs``](confs) -- Server configuration files for nginx and uwsgi. Edit the templates then ``fab <ENV> servers.render_confs``, don't edit anything in ``confs/rendered`` directly.
* [``data``](data) -- Data files, such as those used to generate HTML.
* [``fabfile``](fabfile) -- [Fabric](http://docs.fabfile.org/en/latest/) commands for automating setup, deployment, data processing, etc.
* [``etc``](etc) -- Miscellaneous scripts and metadata for project bootstrapping.
* [``less``](less) -- [LESS](http://lesscss.org/) files, will be compiled to CSS and concatenated for deployment.
* [``templates``](templates) -- HTML ([Jinja2](http://jinja.pocoo.org/docs/)) templates, to be compiled locally.
* [``tests``](tests) -- Python unit tests.
* [``www``](www) -- Static and compiled assets to be deployed. (a.k.a. "the output")
* [``www/assets``](www/assets) -- A symlink to an S3 bucket containing binary assets (images, audio).
* [``www/live-data``](www/live-data)  -- "Live" data deployed to S3 via cron jobs or other mechanisms. (Not deployed with the rest of the project.)
* [``www/test``](www/test) -- Javascript tests and supporting files.
* [``app.py``](app.py) -- A [Flask](http://flask.pocoo.org/) app for rendering the project locally.
* [``app_config.py``](app_config.py) -- Global project configuration for scripts, deployment, etc.
* [``render_utils.py``](render_utils.py) -- Code supporting template rendering.
* [``requirements.txt``](requirements.txt) -- Python requirements.

Data flow
---------

The core functionality of this app is to fetch results from the AP elections API, bake them to JSON and publish that JSON to S3 for consumption by the front-end graphics code.  This is how the various pieces of software in this app work together to fetch and publish the results.

### Upstart starts a service that runs Fabric tasks

When the project is deployed, a service is created named `fetch_and_publish_results` by copying `confs/fetch_and_publish_results.conf` to `/etc/init/fetch_and_publish_results`.  Once deployed, this service can be started and stopped using Fabric tasks.

The `fetch_and_publish_results` service calls `run_on_server.sh` to initialize the Python and shell environment and then runs the `daemons.fetch_and_publish_results` Fabric task.  This task just runs the `daemons.main` Fabric task.

### Fabric tasks use `elex` to fetch results into a Postgres database

The `daemons.main` Fabric task executes the `data.load_results` Fabric task. This task uses the [elex](https://github.com/newsdev/elex) CLI to download the results as CSV.  It then uses `psql` to load the CSV into a PostgreSQL database using a `COPY` query.

_note: you can pass zeroes to the load_results task (`data.load_results:zeroes`) to override results with zeros; omits the winner indicator. Sets the vote, delegate, and reporting precinct counts to zero._

### Fabric tasks render results from the database to JSON

After fetching the results and loading them into the database, the `daemons.main` Fabric task executes the `publish_results` Fabric task. This task calls the `render.render` Fabric task which calls other Python code that uses the [Peewee](https://github.com/coleifer/peewee) ORM to retrieve results from the database through the `models.models.Result` model.  The `_serialize_results` function takes the Peewee model instances, converts them to plain Python dictionaries and adds a few calculated fields. It also shapes the collection of results into the format that will eventually be dumped to a JSON string by `_write_json_file`.

### Fabric tasks upload the rendered JSON to S3

After calling the `render.render` Fabric task, the `publish_results` task calls the `move_s3` task which simply uses the `aws` CLI to upload the results JSON file to S3.

Hide project secrets
--------------------

Project secrets should **never** be stored in ``app_config.py`` or anywhere else in the repository. They will be leaked to the client if you do. Instead, always store passwords, keys, etc. in environment variables and document that they are needed here in the README.

Any environment variable that starts with ``$PROJECT_SLUG_`` will be automatically loaded when ``app_config.get_secrets()`` is called.

Output JSON
-----------

The result loading and baking daemon outputs a JSON file to S3.

### Example

```
{
    "results": {
        "1683": {
            "candidates": [
                {
                    "first": "Doug",
                    "last": "Jones",
                    "party": "Dem",
                    "votecount": 0,
                    "votepct": 0.0,
                    "winner": false
                },
                {
                    "first": "Roy",
                    "last": "Moore",
                    "party": "GOP",
                    "votecount": 0,
                    "votepct": 0.0,
                    "winner": false
                },
                {
                    "first": null,
                    "last": "Total Write-Ins",
                    "party": "NPD",
                    "votecount": 0,
                    "votepct": 0.0,
                    "winner": false
                }
            ],
            "lastupdated": "Nov. 29, 2017, 2:30 p.m.",
            "level": "state",
            "nprformat_precinctsreportingpct": "0%",
            "officename": "U.S. Senate",
            "precinctsreporting": 0,
            "precinctstotal": 2220,
            "statename": "Alabama",
            "statepostal": "AL"
        }
    }
}
```

### Philosophy

We've tried to make the output JSON compact to minimize the amount of data that a user needs to download to retrieve the results.

When possible, we also try to pre-format data, such as dates or percentages, in the JSON to limit the size and complexity of front-end code.

### Race IDs

The properties nested under the `results` property, `1683` in the example above, are the AP race IDs. Using a unique identifier as a key for each race allows the front end code to quicky retrieve results for a given race without iteration. Be aware that it is possible for the AP race IDs to change prior to election night. The final IDs will be sent over with the zeroed results on election day. If they differ from the IDs used during testing, front-end configuration or code that references the ID will need to be updated.

### Race Fields

#### `candidates`

An array of candidate results.

#### `lastupdated`

Formatted timestamp reflecting:

* If there are no precincts reporting, the time of the last pull from the AP API
* If there is at least one precinct reporting, the time the data was last updated as reported by the AP.

**Example:** `Nov. 29, 2017, 2:30 p.m.`.

#### `level`

The reporting level of the results.

TODO: Document other possible levels. I think this is documented in the elex docs.

**Example:** `state`

#### `nprformat\_precinctsreportingpct`

String containing formatted percentage of precincts reporting:.

* If the percentage of precincts reporting is less than 1%, `<1%`.
* If the percentage is less than 99%, the percentage value will be displayed, e.g. `15.1%`.
* If the percentage is greater than 99% but less than 100%, `>99%`.

#### `officename`

Name of the office for this election.

**Example:** `U.S. Senate`

#### `precinctsreporting`

Integer representing number of precincts reporting results.

**Example:** `1`

#### `precinctstotal`

Integer representing total number of precincts that can report results for this election.

**Example:** `2220`

#### `statename`

Name of state for these election results.

**Example:** `Alabama`

#### `statepostal`

Abbreviation for Alabama.

**Example:** `AL`

### Candidate Fields

These fields represent results for individual candidates and are collected under the `candidates` property of a race record.

#### `first`

String containing first name of candidate or `null` for pseudo-candidates.

**Example:** "Doug"

#### `last`

String containing last name of candidate or identifier of pseudo-candidates.

**Examples:**

* `Jones`
* `Total Write-Ins`

#### `votecount`

Integer representing total number of votes received by the candidate.

**Example:** `0`

#### `votepct`

Float representing percentage of total votes won by the candidate.

**Example:** `0.0`

#### `winner`

Boolean representing whether this candidate has been called as the winner. Defaults to the AP call but will be overridden by the NPR call if specified in the admin.

**Example:** `false`

Configuration
-------------

This app shares many of the configuration variables common to apps based on [NPR's App Template](https://github.com/nprapps/app-template). This section documents application-specific configuration variables.

In most cases, configuration is through variables defined in the `app\_config` module in `app\_config.py`. However, some configuration may be defined through environment variables.

### AP\_API\_KEY

API key used by [`elex`](http://elex.readthedocs.io/) to authenticate to the Associated Press' results API.

Type: Environment variable

### ELEX\_FLAG\_SETS

Command line flags for the `elex` command. See the [elex cli documentation](http://elex.readthedocs.io/en/stable/cli.html) for available flags.

This supports multiple different `elex` calls; for example, one may want to make a `reportingunit`-level call for presidential results, but a `state`-level call for the result of all other race types.

Type: `app\_config` variable

Example: `'--national-only'`

### ELEX\_FTP\_FLAGS

Command line flags for the `elex\_ftp` command, which is a vendorized version of [elex-ftp-loader](https://github.com/newsdev/elex-ftp-loader). This is available as a fallback if there are issues retrieving results through AP's API. However, the API is the preferred method of retrieving results.

Type: `app\_config` variable

Example: `'--states AL'`

### ELEX\_INIT\_FLAG\_SETS

Command line flags for the `elex` command used to force zeroed-out results with `fab data.load\_results:mode=zeroes` . See the [elex cli documentation](http://elex.readthedocs.io/en/stable/cli.html) for more information.

Type: `app\_config` variable

Example: `'--national-only --set-zero-counts'`

### LOAD\_RESULTS\_INTERVAL

Time, in seconds, between requests to the AP API. The AP API is throttled, so you can't set this to be too small.

Type: `app\_config` variable

Example: `10`

### CANDIDATE\_SET\_OVERRIDES

Our system typically only includes the Democrat and Republican (or just the top/main two candidates) in the JSON files that get rendered.

Sometimes, we'll want to explicitly include a third-party candidate, or include three or more candidates. Use this option to do so. If no votes are in yet, we'll maintain the candidate order provided. If any votes are in, allow this set of candidates to be reordered by the system.

We're using AP `candidateid` to identify, which is unique at the race level. Structure is `{ 'AP RACE ID 1': [ 'AP CANDIDATEID 1', 'AP CANDIDATEID 2', ... ], ... }`

Type: `app\_config` variable

Example:

```python
{
    # New York's 22nd House seat: Tenney, Myers, and Babinec
    '36602': ['79331', '79334', '79335'],
    # Alaska Senate seat: Murkowski, Miller, and Stock
    '2933': ['6021', '6650', '6647']
}
```

### DATA\_OUTPUT\_FOLDER

Path to folder where results JSON is rendered before being uploaded to S3.

Type: `app\_config` variable

Example: `'.rendered'`

Save media assets
-----------------

Large media assets (images, videos, audio) are synced with an Amazon S3 bucket specified in ``app_config.ASSETS_S3_BUCKET`` in a folder with the name of the project. (This bucket should not be the same as any of your ``app_config.PRODUCTION_S3_BUCKETS`` or ``app_config.STAGING_S3_BUCKETS``.) This allows everyone who works on the project to access these assets without storing them in the repo, giving us faster clone times and the ability to open source our work.

Syncing these assets requires running a couple different commands at the right times. When you create new assets or make changes to current assets that need to get uploaded to the server, run ```fab assets.sync```. This will do a few things:

* If there is an asset on S3 that does not exist on your local filesystem it will be downloaded.
* If there is an asset on that exists on your local filesystem but not on S3, you will be prompted to either upload (type "u") OR delete (type "d") your local copy.
* You can also upload all local files (type "la") or delete all local files (type "da"). Type "c" to cancel if you aren't sure what to do.
* If both you and the server have an asset and they are the same, it will be skipped.
* If both you and the server have an asset and they are different, you will be prompted to take either the remote version (type "r") or the local version (type "l").
* You can also take all remote versions (type "ra") or all local versions (type "la"). Type "c" to cancel if you aren't sure what to do.

Unfortunantely, there is no automatic way to know when a file has been intentionally deleted from the server or your local directory. When you want to simultaneously remove a file from the server and your local environment (i.e. it is not needed in the project any longer), run ```fab assets.rm:"www/assets/file_name_here.jpg"```

Adding a page to the site
-------------------------

A site can have any number of rendered pages, each with a corresponding template and view. To create a new one:

* Add a template to the ``templates`` directory. Ensure it extends ``_base.html``.
* Add a corresponding view function to ``app.py``. Decorate it with a route to the page name, i.e. ``@app.route('/filename.html')``
* By convention only views that end with ``.html`` and do not start with ``_``  will automatically be rendered when you call ``fab render``.

Provisioning servers
--------------------

We need to create instances for both our staging and our production environments. For each environment we need to setup an EC2 instance to run the Python daemon and admin web app and a RDS instance for our database that we use to store the results coming from the AP API through elex.

This project did not have strong requirements in terms of performance nor data loads so we chose medium sized virtual machines. For other elections a new assessment will need to be made on data throughput and storage capacity.

### EC2 instance configuration

We use Ubuntu 16.04 LTS images for Python 3 projects.

* Instance type: `t2.medium`
* Storage: 10GB

### Additional needed software

* Python 3
* `virtualenv`
* Node.js 8
* Upstart, to use our configuration files
* Nginx
* `uwsgi`

_Note: NPR users can use our AMI that already contains this configuration, `python3 webserver`_


### RDS instance configuration

* Instance type: `db.t2.medium`
* Database engine: PostgreSQL 9.6.3

_Note: At NPR we normally do not create the actual dabatase through the AWS Console, in order to test our database bootstrapping scripts in the staging and production environments._

Deployment
----------

This app can be deployed to EC2 using Fabric in a manner to other NPR apps that run on servers.

### First time

* In ``app_config.py`` set ``DEPLOY_TO_SERVERS`` to ``True``.
* Run ``fab staging master servers.setup`` to configure the server.
* Initialize the RDS DB ``fab staging master servers.fabcast:data.bootstrap_db``

Once we have setup our servers we will need to install the webservices to support the admin that will allow us to override winner calls from AP, follow the instructions in [Install web services](#install-web-services). More details on the Admin can be found [here](#admin-interface)

### Update server after code changes

* Verify that ``DEPLOY_TO_SERVERS`` is set to ``True`` in ``app_config.py``.
* Run ``fab staging master servers.checkout_latest`` to update codebase on the server

### Update DB after change in ORM models

* Verify that ``DEPLOY_TO_SERVERS`` is set to ``True`` in ``app_config.py``.
* Run ``fab staging master servers.checkout_latest`` to update codebase on the server
* Reset the RDS DB ``fab staging master servers.fabcast:data.bootstrap_db``

Run the project
---------------

### Local development server, with Docker Compose

Since there are multiple components and processes, it's easiest to coordinate and containerize all of them using Docker Compose. Make sure that you have [Docker](https://docs.docker.com/install/) installed on your computer.

Select environment variables (dictated in `docker-compose.yml`) will be shared with the Docker containers. Updates to the code on your local machine will be reflected in the containers (since their file systems share the repo directory from your local machine). Similar to how you'd need to stop and start most processes on your local machine, you may need to stop (`docker-compose stop ${SERVICE_NAME}`) and restart (`docker-compose up ${SERVICE_NAME}`) to get the updated code to run. If you change the `Dockerfile`s, `requirements.txt`, or `package.json` files containing the operating systems, libraries, and binaries installed on the Docker containers, you will need to run `docker-compose build ${SERVICE_NAME}` in order to update that Docker container.

- To bring up the database server, run `docker-compose up database`
  - Leaving this terminal shell up will let you view database logs as they happen
  - We use port `5433` instead of the Postgres-default `5432` so that the Docker container's open port doesn't conflict with any local Postgres instances you have on your machine
  - You should be able to use a local Postgres client to connect to this container, using `psql postgres://elections18:elections18@localhost:5433/elections18`
- To initialize your database's schema and insert some test data, run `docker-compose up bootstrap_db"
  - This will pull the most recent data from the AP API
- To run the daemon, to continuously poll the AP API and publish the most recent JSON files, run `docker-compose up daemon`
  - JSON files will be published to the `GRAPHICS_DATA_OUTPUT_FOLDER`, set in `app_config.py`
- To bring up the admin interface, run `docker-compose up app`
  - You can connect to this service at `localhost:8001`; eg, `http://localhost:8001/elections18/calls/senate/`
- Separately, and not required, there is also a `fakeapserver` Docker Compose service that can mock constantly-updating AP data using [AP Deja-Vu](https://github.com/newsdev/ap-deja-vu). Per the comments in `docker-compose.yml`, you can run this service (`docker-compose up fakeapserver`), connect to its admin panel on `http://localhost:8002/elections/${YEAR_OF_ELECTION}/ap-deja-vu/`, and then point the `daemon` service at this fake AP API endpoint.

(Again, all of the above could be executed on your local machine, but it's much simpler to handle the varied OS+binary+library environments within containers, and also makes for quicker local setup.)


### Results loader daemon

To start the daemon that loads results into the database, bakes them to JSON and publishes the JSON to S3, run this Fabric task:

```
fab production servers.start_service:fetch_and_publish_results
```

To stop the daemon, run this Fabric task:

```
fab production servers.stop_service:fetch_and_publish_results
```

Admin interface
---------------

There is a web-based admin interface that can be used to call winners in races. The winners called through the admin will override the winner in the AP results and will be reflected in the published results JSON.

In the admin we can decide whether or not we accept AP calls for winners in a given race.

For example if you are running the local webserver you can check the admin for senate races by visiting `http://localhost:8000/elections18-general/calls/senate/`

![screenshot Admin][screenshot]

If we decide to not accept AP calls for winners in a given race we can then make a manual call ourselves for a given candidate in the race and that will be reflected in the published results JSON.

For example a manual call for `Doug Jones` would look like this:

![screenshot manual call][manual]

[screenshot]: readme-assets/admin1.png
[manual]: readme-assets/admin2.png


COPY configuration
------------------

_Note: This project was first created using NPR [app-template](https://github.com/nprapps/app-template) and even though we have stripped out the unused boilerplate that came along from it, we have left the COPY functionality because for subsequent elections we can foresee the use of the COPY worklow to add meta information for an election like the expected winner, or any other information given to us by the politics team that will add value to the pure results provided by AP_

This app uses a Google Spreadsheet for a simple key/value store that provides an editing workflow.

To access the Google doc, you'll need to create a Google API project via the [Google developer console](http://console.developers.google.com).

Enable the Drive API for your project and create a "web application" client ID.

For the redirect URIs use:

* `http://localhost:8000/authenticate/`
* `http://127.0.0.1:8000/authenticate`
* `http://localhost:8888/authenticate/`
* `http://127.0.0.1:8888/authenticate`

For the Javascript origins use:

* `http://localhost:8000`
* `http://127.0.0.1:8000`
* `http://localhost:8888`
* `http://127.0.0.1:8888`

You'll also need to set some environment variables:

```
export GOOGLE_OAUTH_CLIENT_ID="something-something.apps.googleusercontent.com"
export GOOGLE_OAUTH_CONSUMER_SECRET="bIgLonGStringOfCharacT3rs"
export AUTHOMATIC_SALT="jAmOnYourKeyBoaRd"
```

Note that `AUTHOMATIC_SALT` can be set to any random string. It's just cryptographic salt for the authentication library we use.

Once set up, run `fab app` and visit `http://localhost:8000` in your browser. If authentication is not configured, you'll be asked to allow the application for read-only access to Google drive, the account profile, and offline access on behalf of one of your Google accounts. This should be a one-time operation across all app-template projects.

It is possible to grant access to other accounts on a per-project basis by changing `GOOGLE_OAUTH_CREDENTIALS_PATH` in `app_config.py`.


COPY editing
------------

View the [sample copy spreadsheet](https://docs.google.com/spreadsheet/pub?key=1pja8aNw24ZGZTrfO8TSQCfN76gQrj6OhEcs07uz0_C0#gid=0).

This document is specified in ``app_config`` with the variable ``COPY_GOOGLE_DOC_KEY``. To use your own spreadsheet, change this value to reflect your document's key. (The long string of random looking characters is in your Google Docs URL. For example: ``1DiE0j6vcCm55Dyj_sV5OJYoNXRRhn_Pjsndba7dVljo``)

A few things to note:

* If there is a column called ``key``, there is expected to be a column called ``value`` and rows will be accessed in templates as key/value pairs
* Rows may also be accessed in templates by row index using iterators (see below)
* You may have any number of worksheets
* This document must be "published to the web" using Google Docs' interface

The app template is outfitted with a few ``fab`` utility functions that make pulling changes and updating your local data easy.

To update the latest document, run:

```
fab text.update
```

Note: ``text.update`` runs automatically whenever ``fab render`` is called.

At the template level, Jinja maintains a ``COPY`` object that you can use to access your values in the templates. Using our example sheet, to use the ``byline`` key in ``templates/index.html``:

```
{{ COPY.attribution.byline }}
```

More generally, you can access anything defined in your Google Doc like so:

```
{{ COPY.sheet_name.key_name }}
```

You may also access rows using iterators. In this case, the column headers of the spreadsheet become keys and the row cells values. For example:

```
{% for row in COPY.sheet_name %}
{{ row.column_one_header }}
{{ row.column_two_header }}
{% endfor %}
```

When naming keys in the COPY document, please attempt to group them by common prefixes and order them by appearance on the page. For instance:

```
title
byline
about_header
about_body
about_url
download_label
download_url
```

### How to create a new sheet and hook it up

Example: This is how the Get Caught Up chunk was created on the backend and hooked up to the front-end.

1. Create the new tab in the COPY spreadsheet. You'll probably want to do this on your own copy of the COPY spreadsheet, that means you'll have to point to the new spreadsheet in app_config.py, `COPY_GOOGLE_DOC_KEY`
1. In [fabfile/render.py](fabfile/render.py#L258), create a new method with a `@task` decorator that will load the data and save it to a json file. Make sure to call that method in the `render_all()` method.
1. Download the latest COPY spreadsheet with `fab text.update`
1. Run the command you created in step two, in this example it was `fab render.render_get_caught_up`
1. Run the local docker daemon to copy the new json file to graphics: `docker-compose up daemon`. If that doesn't work you could try `docker-compose up bootstrap_db`

That's the backend portion of hooking up a new tab in the COPY spreadsheet.

Open Linked Google Spreadsheet
------------------------------
Want to edit/view the app's linked google spreadsheet, we got you covered.

We have created a simple Fabric task ```spreadsheet```. It will try to find and open the app's linked google spreadsheet on your default browser.

```
fab spreadsheet
```

If you are working with other arbitraty google docs that are not involved with the COPY rig you can pass a key as a parameter to have that spreadsheet opened instead on your browser

```
fab spreadsheet:$GOOGLE_DOC_KEY
```

For example:

```
fab spreadsheet:12_F0yhsXEPN1w3GOlQB4_NKGadXiRLOa9l-HQu5jSL8
// Will open 270 project number-crunching spreadsheet
```


Generating custom font
----------------------

This project uses a custom font build powered by [Fontello](http://fontello.com)
If the font does not exist, it will be created when running `fab update`.
To force generation of the custom font, run:

```
fab utils.install_font:true
```

Editing the font is a little tricky -- you have to use the Fontello web gui.
To open the gui with your font configuration, run:

```
fab utils.open_font
```

Now edit the font, download the font pack, copy the new config.json into this
project's `fontello` directory, and run `fab utils.install_font:true` again.

Arbitrary Google Docs
----------------------

Sometimes, our projects need to read data from a Google Doc that's not involved with the COPY rig. In this case, we've got a helper function for you to download an arbitrary Google spreadsheet.

This solution will download the uncached version of the document, unlike those methods which use the "publish to the Web" functionality baked into Google Docs. Published versions can take up to 15 minutes up update!

Make sure you're authenticated, then call `oauth.get_document(key, file_path)`.

Here's an example of what you might do:

```
from copytext import Copy
from oauth import get_document

def read_my_google_doc():
    file_path = 'data/extra_data.xlsx'
    get_document('1pja8aNw24ZGZTrfO8TSQCfN76gQrj6OhEcs07uz0_C0', file_path)
    data = Copy(file_path)

    for row in data['example_list']:
        print '%s: %s' % (row['term'], row['definition'])

read_my_google_doc()
```

Run Python tests
----------------

Python unit tests are stored in the ``tests`` directory. Run them with ``fab tests``.

Compile static assets
---------------------

Compile LESS to CSS, compile javascript templates to Javascript and minify all assets:

```
fab render
```

(This is done automatically whenever you deploy to S3.)

Test the rendered app
---------------------

If you want to test the app once you've rendered it out, just use the Python webserver:

```
cd www
python -m SimpleHTTPServer
```

Install web services
---------------------

Web services are configured in the `confs/` folder.

Running ``fab servers.setup`` will deploy your confs if you have set ``DEPLOY_TO_SERVERS`` and ``DEPLOY_WEB_SERVICES`` both to ``True`` at the top of ``app_config.py``.

To check that these files are being properly rendered, you can render them locally and see the results in the `confs/rendered/` directory.

```
fab servers.render_confs
```

You can also deploy only configuration files by running (normally this is invoked by `deploy`):

```
fab servers.deploy_confs
```

Run a remote fab command
-------------------------

Sometimes it makes sense to run a fabric command on the server, for instance, when you need to render using a production database. You can do this with the `fabcast` fabric command. For example:

```
fab staging master servers.fabcast:deploy
```

If any of the commands you run themselves require executing on the server, the server will SSH into itself to run them.

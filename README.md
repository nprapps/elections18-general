Copyright 2015 NPR.  All rights reserved.  No part of these materials may be reproduced, modified, stored in a retrieval system, or retransmitted, in any form or by any means, electronic, mechanical or otherwise, without prior written permission from NPR.

(Want to use this code? Send an email to nprapps@npr.org!)


elections17-alabama
===================

* [What is this?](#what-is-this)
* [Assumptions](#assumptions)
* [What's in here?](#whats-in-here)
* [Bootstrap the project](#bootstrap-the-project)
* [Data flow](#data-flow)
* [Hide project secrets](#hide-project-secrets)
* [Save media assets](#save-media-assets)
* [Add a page to the site](#add-a-page-to-the-site)
* [Run the project](#run-the-project)
* [COPY configuration](#copy-configuration)
* [COPY editing](#copy-editing)
* [Open Linked Google Spreadsheet](#open-linked-google-spreadsheet)
* [Generating custom font](#generating-custom-font)
* [Arbitrary Google Docs](#arbitrary-google-docs)
* [Run Python tests](#run-python-tests)
* [Run Javascript tests](#run-javascript-tests)
* [Compile static assets](#compile-static-assets)
* [Test the rendered app](#test-the-rendered-app)
* [Deploy to S3](#deploy-to-s3)
* [Deploy to EC2](#deploy-to-ec2)
* [Install cron jobs](#install-cron-jobs)
* [Install web services](#install-web-services)
* [Run a remote fab command](#run-a-remote-fab-command)
* [Report analytics](#report-analytics)

What is this?
-------------

The backend for NPR's 2017 alabama special election coverage.

Assumptions
-----------

The following things are assumed to be true in this documentation.

* You are running OSX.
* You are using **Python 3**.
* You have [virtualenv](https://pypi.python.org/pypi/virtualenv) and [virtualenvwrapper](https://pypi.python.org/pypi/virtualenvwrapper) installed and working.
* You have NPR's AWS credentials stored as environment variables locally.
* You have an AP Elections results API key (see the [elex documentation](http://elex.readthedocs.io/en/stable/install.html#automatically-set-your-api-key) for more on this)

For more details on the technology stack used with the app-template, see our [development environment blog post](http://blog.apps.npr.org/2013/06/06/how-to-setup-a-developers-environment.html).

What's in here?
---------------

The project contains the following folders and important files:

* ``confs`` -- Server configuration files for nginx and uwsgi. Edit the templates then ``fab <ENV> servers.render_confs``, don't edit anything in ``confs/rendered`` directly.
* ``data`` -- Data files, such as those used to generate HTML.
* ``fabfile`` -- [Fabric](http://docs.fabfile.org/en/latest/) commands for automating setup, deployment, data processing, etc.
* ``etc`` -- Miscellaneous scripts and metadata for project bootstrapping.
* ``jst`` -- Javascript ([Underscore.js](http://documentcloud.github.com/underscore/#template)) templates.
* ``less`` -- [LESS](http://lesscss.org/) files, will be compiled to CSS and concatenated for deployment.
* ``templates`` -- HTML ([Jinja2](http://jinja.pocoo.org/docs/)) templates, to be compiled locally.
* ``tests`` -- Python unit tests.
* ``www`` -- Static and compiled assets to be deployed. (a.k.a. "the output")
* ``www/assets`` -- A symlink to an S3 bucket containing binary assets (images, audio).
* ``www/live-data`` -- "Live" data deployed to S3 via cron jobs or other mechanisms. (Not deployed with the rest of the project.)
* ``www/test`` -- Javascript tests and supporting files.
* ``app.py`` -- A [Flask](http://flask.pocoo.org/) app for rendering the project locally.
* ``app_config.py`` -- Global project configuration for scripts, deployment, etc.
* ``copytext.py`` -- Code supporting the [Editing workflow](#editing-workflow)
* ``crontab`` -- Cron jobs to be installed as part of the project.
* ``public_app.py`` -- A [Flask](http://flask.pocoo.org/) app for running server-side code.
* ``render_utils.py`` -- Code supporting template rendering.
* ``requirements.txt`` -- Python requirements.
* ``static.py`` -- Static Flask views used in both ``app.py`` and ``public_app.py``.

Bootstrap the project
---------------------

Node.js is required for the static asset pipeline. If you don't already have it, get it like this:

```
brew install node
```

You will also need Python 3:

```
brew install python3
```

Then bootstrap the project:

```
git clone git@github.com:nprapps/elections17-alabama.git
cd elections17-alabama
mkvirtualenv -p `which python3` elections17-alabama
pip install -r requirements.txt
npm install
```

Note that deployment depends on `awscli`, which is broken on pip at the moment. Use your operating system's package manager to install it instead. (On Macs, use `brew install awscli`).

**Problems installing requirements?** You may need to run the pip command as ``ARCHFLAGS=-Wno-error=unused-command-line-argument-hard-error-in-future pip install -r requirements.txt`` to work around an issue with OSX.

Data flow
---------

The core functionality of this app is to fetch results from the AP elections API, bake them to JSON and publish that JSON to S3 for consumption by the front-end graphics code.  This is how the various pieces of software in this app work together to fetch and publish the results.

### Upstart starts a service that runs Fabric tasks

When the project is deployed, a service is created named `deploy` by copying `confs/fetch_and_publish_results.conf` to `/etc/init/fetch_and_publish_results`.  Once deployed, this service can be started with `fab production servers.start_service:fetch_and_publish_results` or `fab production servers.stop_service:fetch_and_publish_results`.

The `fetch_and_publish_results` service calls `run_on_server.sh` to initialize the Python and shell environment and then runs the `daemons.fetch_and_publish_results` Fabric task.  This task just runs the `daemons.main` Fabric task.

### Fabric tasks use elex to fetch results into a Postgres database

The `daemons.main` Fabric task executes the `data.load_results` Fabric task. This task uses the [elex](https://github.com/newsdev/elex) CLI to download the results as CSV.  It then uses `psql` to load the CSV into a PostgreSQL database using a `COPY` query.

### Fabric tasks render results from the database to JSON

After fetching the results and loading them into the database, the `daemons.main` Fabric task executes the `publish_results` Fabric task. This task calls the `render.render` Fabric task which calls other Python code that uses the [Peewee](https://github.com/coleifer/peewee) ORM to retrieve results from the database through the `models.models.Result` model.  The `_serialize_results` function takes the Peewee model instances, converts them to plain Python dictionaries and adds a few calculated fields. It also shapes the collection of results into the format that will eventually be dumped to a JSON string by `_write_json_file`.

### Fabric tasks upload the rendered JSON to S3

After calling the `render.render` Fabric task, the `publish_results` task calls the `move_s3` task which simply uses the `aws` CLI to upload the results JSON file to S3.

Hide project secrets
--------------------

Project secrets should **never** be stored in ``app_config.py`` or anywhere else in the repository. They will be leaked to the client if you do. Instead, always store passwords, keys, etc. in environment variables and document that they are needed here in the README.

Any environment variable that starts with ``$PROJECT_SLUG_`` will be automatically loaded when ``app_config.get_secrets()`` is called.

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

Run the project
---------------

A flask app is used to run the project locally. It will automatically recompile templates and assets on demand.

```
workon elections17-alabama
fab app
```

Visit [localhost:8000](http://localhost:8000) in your browser.

COPY configuration
------------------

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

This document is specified in ``app_config`` with the variable ``COPY_GOOGLE_DOC_KEY``. To use your own spreadsheet, change this value to reflect your document's key. (The long string of random looking characters in your Google Docs URL. For example: ``1DiE0j6vcCm55Dyj_sV5OJYoNXRRhn_Pjsndba7dVljo``)

A few things to note:

* If there is a column called ``key``, there is expected to be a column called ``value`` and rows will be accessed in templates as key/value pairs
* Rows may also be accessed in templates by row index using iterators (see below)
* You may have any number of worksheets
* This document must be "published to the web" using Google Docs' interface

The app template is outfitted with a few ``fab`` utility functions that make pulling changes and updating your local data easy.

To update the latest document, simply run:

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
workon elections17-alabama
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

Deploy to S3
------------

```
fab staging master deploy
```

Deploy to EC2
-------------

You can deploy to EC2 for a variety of reasons. We cover two cases: Running a dynamic web application (`public_app.py`) and executing cron jobs (`crontab`).

Servers capable of running the app can be setup using our [servers](https://github.com/nprapps/servers) project.

For running a Web application:

* In ``app_config.py`` set ``DEPLOY_TO_SERVERS`` to ``True``.
* Also in ``app_config.py`` set ``DEPLOY_WEB_SERVICES`` to ``True``.
* Run ``fab staging master servers.setup`` to configure the server.
* Run ``fab staging master deploy`` to deploy the app.

For running cron jobs:

* In ``app_config.py`` set ``DEPLOY_TO_SERVERS`` to ``True``.
* Also in ``app_config.py``, set ``INSTALL_CRONTAB`` to ``True``
* Run ``fab staging master servers.setup`` to configure the server.
* Run ``fab staging master deploy`` to deploy the app.

You can configure your EC2 instance to both run Web services and execute cron jobs; just set both environment variables in the fabfile.

Install cron jobs
-----------------

Cron jobs are defined in the file `crontab`. Each task should use the `cron.sh` shim to ensure the project's virtualenv is properly activated prior to execution. For example:

```
* * * * * ubuntu bash /home/ubuntu/apps/elections16_general/repository/cron.sh fab $DEPLOYMENT_TARGET cron_jobs.test
```

To install your crontab set `INSTALL_CRONTAB` to `True` in `app_config.py`. Cron jobs will be automatically installed each time you deploy to EC2.

The cron jobs themselves should be defined in `fabfile/cron_jobs.py` whenever possible.

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

Run a  remote fab command
-------------------------

Sometimes it makes sense to run a fabric command on the server, for instance, when you need to render using a production database. You can do this with the `fabcast` fabric command. For example:

```
fab staging master servers.fabcast:deploy
```

If any of the commands you run themselves require executing on the server, the server will SSH into itself to run them.

Analytics
---------

The Google Analytics events tracked in this application are:

|Category|Action|Label|Value|
|--------|------|-----|-----|
|elections17-alabama|tweet|`location`||
|elections17-alabama|facebook|`location`||
|elections17-alabama|email|`location`||
|elections17-alabama|new-comment||
|elections17-alabama|open-share-discuss||
|elections17-alabama|close-share-discuss||
|elections17-alabama|summary-copied||
|elections17-alabama|featured-tweet-action|`action`|
|elections17-alabama|featured-facebook-action|`action`|

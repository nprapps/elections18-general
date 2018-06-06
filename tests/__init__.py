import app_config
from fabfile import data

app_config.configure_targets('test')
data.bootstrap_db()

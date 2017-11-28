import app_config

from peewee import Model, PostgresqlDatabase
from peewee import BooleanField, CharField, DateField, DateTimeField, DecimalField, ForeignKeyField, IntegerField
from slugify import slugify
from playhouse.postgres_ext import JSONField

import logging
logger = logging.getLogger('peewee')
logger.setLevel(logging.WARNING)
logger.addHandler(logging.StreamHandler())

# app_config.configure_targets('test')

db = PostgresqlDatabase(
    app_config.database['PGDATABASE'],
    user=app_config.database['PGUSER'],
    password=app_config.database['PGPASSWORD'],
    host=app_config.database['PGHOST'],
    port=app_config.database['PGPORT']
)

class BaseModel(Model):
    """
    Base class for Peewee models. Ensures they all live in the same database.
    """
    class Meta:
        database = db


class Result(BaseModel):
    id = CharField(primary_key=True)
    raceid = CharField(null=True)
    racetype = CharField(null=True)
    racetypeid = CharField(null=True)
    ballotorder = IntegerField(null=True)
    candidateid = CharField(null=True)
    description = CharField(null=True)
    delegatecount = IntegerField(null=True)
    electiondate = DateField(null=True)
    electtotal = IntegerField(null=True)
    electwon = IntegerField(null=True)
    fipscode = CharField(max_length=5, null=True)
    first = CharField(null=True)
    incumbent = BooleanField(null=True)
    initialization_data = BooleanField(null=True)
    is_ballot_measure = BooleanField(null=True)
    last = CharField(null=True)
    lastupdated = DateTimeField(null=True)
    level = CharField(null=True)
    national = BooleanField(null=True)
    officeid = CharField(null=True)
    officename = CharField(null=True)
    party = CharField(null=True)
    polid = CharField(null=True)
    polnum = CharField(null=True)
    precinctsreporting = IntegerField(null=True)
    precinctsreportingpct = DecimalField(null=True)
    precinctstotal = IntegerField(null=True)
    reportingunitid = CharField(null=True)
    reportingunitname = CharField(null=True)
    runoff = BooleanField(null=True)
    seatname = CharField(null=True)
    seatnum = CharField(null=True)
    statename = CharField(null=True)
    statepostal = CharField(max_length=2)
    test = BooleanField(null=True)
    uncontested = BooleanField(null=True)
    votecount = IntegerField(null=True)
    votepct = DecimalField(null=True)
    winner = BooleanField(null=True)

    def is_npr_winner(self):
        if self.level == 'district':
            if (self.electwon > 0 and self.call[0].accept_ap) or self.call[0].override_winner:
                return True
            else:
                return False

        if (self.winner and self.call[0].accept_ap) or self.call[0].override_winner:
            return True
        else:
            return False

    def is_pickup(self):
        if self.is_npr_winner() and self.party != self.meta[0].current_party:
            return True
        else:
            return False

    def is_expected(self):
        if self.is_npr_winner() and self.party == self.meta[0].expected:
            return True
        else:
            return False

    def is_not_expected(self):
        if self.is_npr_winner():
            if self.meta[0].expected == 'Dem' and self.party != 'Dem':
                return True
            if self.meta[0].expected == 'GOP' and self.party != 'GOP':
                return True
            else:
                return False
        else:
            return False        


class Call(BaseModel):
    call_id = ForeignKeyField(Result, related_name='call')
    accept_ap = BooleanField(default=True)
    override_winner = BooleanField(default=False)


class RaceMeta(BaseModel):
    result_id = ForeignKeyField(Result, related_name='meta')
    poll_closing = CharField(null=True)
    full_poll_closing = CharField(null=True)
    first_results = CharField(null=True)
    current_party = CharField(null=True)
    expected = CharField(null=True)

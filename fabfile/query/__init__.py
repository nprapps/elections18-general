#!/usr/bin/env python
# _*_ coding:utf-8 _*_
from models import models

def select_senate_results():
    """Returns Peewee model instances for U.S. Senate results"""
    results = models.Result.select().where(
        models.Result.level == 'state',
        models.Result.officename == 'U.S. Senate'
    )

    return results

from __future__ import unicode_literals
from helium import DataPoint
from operator import attrgetter


def display_map(cls, client):
    dict = super(DataPoint, cls).display_map(client)
    dict.update([
        ('timestamp', attrgetter('timestamp')),
        ('port', attrgetter('port')),
        ('value', attrgetter('value')),
    ])
    return dict

DataPoint.display_map = classmethod(display_map)

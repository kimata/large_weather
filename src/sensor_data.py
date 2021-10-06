#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from influxdb import InfluxDBClient
import datetime
import dateutil.parser

INFLUXDB_ADDR = '192.168.0.10'
INFLUXDB_PORT = 8086
INFLUXDB_DB = 'sensor'

INFLUXDB_QUERY = """
SELECT mean("{param}") FROM "sensor.{sensor_type}" WHERE ("hostname" = \'{hostname}\') AND time >= now() - 60h GROUP BY time(3m) fill(previous) ORDER by time asc
"""


def fetch_data(sensor_type, hostname, param):
    client = InfluxDBClient(
        host=INFLUXDB_ADDR, port=INFLUXDB_PORT, database=INFLUXDB_DB
    )
    result = client.query(INFLUXDB_QUERY.format(
        sensor_type=sensor_type, hostname=hostname, param=param)
    )

    data = list(map(lambda x: x['mean'], result.get_points()))

    localtime_offset = datetime.timedelta(hours=9)
    time = list(map(lambda x: dateutil.parser.parse(x['time'])+localtime_offset, result.get_points()))

    return {
        'value': data,
        'time': time,
        'valid': len(time) != 0
    }

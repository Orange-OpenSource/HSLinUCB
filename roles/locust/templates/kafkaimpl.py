# Software Name : HSLinUCB
# SPDX-FileCopyrightText: Copyright (c) 2021 Orange
# SPDX-License-Identifier: GPL-2.0
#
# This software is distributed under the GNU General Public License v2.0 license
#
# Author: David DELANDE <david.delande@orange.com> et al.

from kafka import KafkaProducer
from backend_base import BackendAdapter, AdapterError
from json import dumps


class KafkaAdapter(BackendAdapter):

    def __init__(self, kafka_hosts=["localhost:9092"]):
        self.es = KafkaProducer(bootstrap_servers=kafka_hosts,value_serializer=lambda x: dumps(x).encode('utf-8'))

    def send(self, data, topic_name='locust'):
        # convert data to proper format
        pass

        # store the data in Kafka
        #self.es.send(topic_name,bytes(str(data).encode('utf-8')))
        self.es.send(topic_name,value=data)

    def finalize(self):
        print("flushing the messages")
        self.es.flush(timeout=5)
        print("flushing finished")

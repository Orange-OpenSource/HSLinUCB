# Software Name : HSLinUCB
# SPDX-FileCopyrightText: Copyright (c) 2021 Orange
# SPDX-License-Identifier: GPL-2.0
#
# This software is distributed under the GNU General Public License v2.0 license
#
# Author: David DELANDE <david.delande@orange.com> et al.

import json
import os
import time
import math
import requests
from random import randint

import gevent
import locust
from locust import TaskSet, task, HttpUser, events, between
from locust import LoadTestShape
from locust.runners import MasterRunner, WorkerRunner, LocalRunner

from backend_base import DBForwarder
from backend_base import KafkaLocustLoadAdapter
from kafkaimpl import KafkaAdapter

##################
# Reading environment variables and setting up constants
#
KAFKA_CONNECTIONS = os.getenv("KAFKA_CONNECTIONS", "{{hostvars[groups['master'][0]].ansible_default_ipv4.address}}:{{kafka_component.spec.ports[0].port}}").split(sep=",")
#QUIET_MODE = True if os.getenv("QUIET_MODE", "true").lower() in ['1', 'true', 'yes'] else False
TASK_DELAY = int(os.getenv("TASK_DELAY", "1000"))


#def log(message):
#    if not QUIET_MODE:
#        print(message)

send_stats = True
send_details = False
Environment = None
forwarder = None

@events.test_stop.add_listener
def on_test_stop(**kw):
    print("test is stopping wait 10 seconds for pending requests")
    time.sleep(10)

@events.quitting.add_listener
def on_locust_quitting(environment, **kwargs):
    global forwarder
    print("quitting forwarder from locustfile")
    forwarder.quitting()

@events.init.add_listener
def on_locust_init(environment, **kwargs):
    global Environment
    global forwarder
    if isinstance(environment.runner, MasterRunner):
        print("I'm on master node")
        print("environment on master:", environment)
        Environment = environment
        print("starting external db forwarder on master")
        forwarder = DBForwarder(send_stats=send_stats,send_details=send_details)
        ea = KafkaAdapter(KAFKA_CONNECTIONS)
        forwarder.add_backend(ea)
        gevent.spawn(forwarder.run)
        LocustLoadAdapter = KafkaLocustLoadAdapter(Environment, KAFKA_CONNECTIONS)
        gevent.spawn(LocustLoadAdapter.run)

        @events.worker_report.add_listener
        def request_stats(client_id, data):
            global forwarder
            stat = {"type": "total", "source": client_id, "payload": data}
            forwarder.add(Environment,stat)
    else:
        print("I'm on a worker or standalone node")
        print("environment on worker:", environment)
        Environment = environment
        print("starting external db forwarder on worker or standalone")
        forwarder = DBForwarder(send_stats=send_stats,send_details=send_details)
        ea = KafkaAdapter(KAFKA_CONNECTIONS)
        forwarder.add_backend(ea)
        gevent.spawn(forwarder.run)
        gevent.spawn(forwarder.run_details)
        if isinstance(Environment.runner, LocalRunner):
            LocustLoadAdapter = KafkaLocustLoadAdapter(Environment, KAFKA_CONNECTIONS)
            gevent.spawn(LocustLoadAdapter.run)

        @events.request_success.add_listener
        def additional_success_handler(request_type, name, response_time, response_length, **kwargs):
            OK_TEMPLATE = '{"request_type":"%s", "name":"%s", "result":"%s", "response_time":%s, "response_length":%s, "other":%s}'
            json_string = OK_TEMPLATE % (request_type, name, "OK", response_time, response_length, json.dumps(kwargs))
            message = {"type": "success", "payload": json.loads(json_string)}
            forwarder.add(Environment,message)
        @events.request_failure.add_listener
        def additional_failure_handler(request_type, name, response_time, exception, **kwargs):
            ERR_TEMPLATE = '{"request_type":"%s", "name":"%s", "result":"%s","response_time":%s, "exception":"%s", "other":%s}'
            json_string = ERR_TEMPLATE % (request_type, name, "ERR", response_time, exception, json.dumps(kwargs))
            message = {"type": "error", "payload": json.loads(json_string)}
            forwarder.add(Environment,message)

class QuickstartUser(HttpUser):

    wait_time = between(0, 2)

    @task
    def index_page(self):
        #self.client.get("/ResponseTime?time=5000")
        self.client.get("/ConsumeFixedCpu?cpu=200")
        #self.client.get("/ResponseTime?time=300")
        #self.client.get("/Proxy?path=ResponseTime?time=300")

class StepLoadShape(LoadTestShape):
    """
    A step load shape
    Keyword arguments:
        step_time -- Time between steps
        step_load -- User increase amount at each step
        spawn_rate -- Users to stop/start per second at every step
        time_limit -- Time limit in seconds
    """

    step_time = 30
    step_load = 1
    spawn_rate = 1
    user_max = 10
    time_limit = 60000

    def tick(self):
        run_time = self.get_run_time()

        if run_time > self.time_limit:
            return None

        current_step = math.floor(run_time / self.step_time) + 1
        if current_step >= self.user_max / self.step_load:
            current_step = math.floor(self.user_max / self.step_load)
        return (current_step * self.step_load, self.spawn_rate)

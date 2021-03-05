# Software Name : HSLinUCB
# SPDX-FileCopyrightText: Copyright (c) 2021 Orange
# SPDX-License-Identifier: GPL-2.0
#
# This software is distributed under the GNU General Public License v2.0 license
#
# Author: David DELANDE <david.delande@orange.com> et al.

from queue import Queue
from locust import runners
from locust.runners import MasterRunner, WorkerRunner, LocalRunner
import time
from itertools import chain
from locust.stats import sort_stats
from kafka import KafkaConsumer
from json import loads


debug = True

###########
# Exceptions
#
class AdapterError(Exception):
    pass

###########
# Base for concrete adapters
#
class BackendAdapter:

    def id(self):
        return f"{type(self)}"

    def send(self, data):
        pass

    def finalize(self):
        pass

    def __hash__(self):
        return hash(self.id())

###########
# Generic forwarder
#
class DBForwarder:
    def __init__(self,send_stats=True,send_details=False):
        self.backends = set()
        self.quit = False
        self.forwarder_queue = Queue()
        self.forwarder_queue_details = Queue()
        self.agregated_result = []
        self.send_stats = send_stats
        self.send_details = send_details
        self.send_timestamp = time.time()

    def add_backend(self, backend_adapter):
        self.backends.add(backend_adapter)
        if debug:
            print(f"backend after addition: {self.backends}")

    def remove_backend(self, backend_adapter):
        self.backends.remove(backend_adapter)
        if debug:
            print(f"backend after removal: {self.backends}")

    def add(self, Environment, data):
        is_master = isinstance(Environment.runner, MasterRunner)
        is_worker = isinstance(Environment.runner, WorkerRunner)
        is_standalone = isinstance(Environment.runner, LocalRunner)
        if (Environment.runner.state == 'running' or Environment.runner.state == 'spawning' or Environment.runner.state == 'stopping') and (self.send_stats or self.send_details): 
            workers = []
            if is_master and self.send_stats:
                for worker in Environment.runner.clients.values():
                    workers.append(
                        {
                            "id": worker.id,
                            "state": worker.state,
                            "user_count": worker.user_count,
                            "cpu_usage": worker.cpu_usage,
                        }
                    )
                entry_already_here = False
                for index,entry in enumerate(self.agregated_result):
                    if data['source'] == entry['source']:
                        entry_already_here = True
                        if debug:
                            print("update entry in buffer")
                        self.agregated_result[index] = data
                if not entry_already_here:    
                    self.agregated_result.append(data)
                if len(self.agregated_result) >= len(Environment.runner.clients.values()):
                    message = {'state': Environment.runner.state, 'toto':'titi','target_user_count': Environment.runner.target_user_count, 'global_user_count': Environment.runner.user_count, 'workers_count': len(Environment.runner.clients.values()), 'worker_details': workers, 'worker_jobs': self.agregated_result}
                    self.forwarder_queue.put(message)
                    self.agregated_result = []

            if is_standalone and self.send_stats:
                if time.time() > self.send_timestamp + 3:
                    self.send_timestamp = time.time()
                    state = Environment.runner.state
                    user_count = Environment.runner.user_count
                    cpu_usage = Environment.runner.current_cpu_usage
                    stats = Environment.runner.stats
                    workers.append(
                        {
                            "id": 1,
                            "state": state,
                            "user_count": user_count,
                            "cpu_usage": cpu_usage,
                        }
                    )
                    message = {'state': state, 'target_user_count': Environment.runner.target_user_count, 'global_user_count': user_count, 'workers_count': 1, 'worker_details': workers, 'worker_jobs': [{'type': 'total', 'source': '1', 'payload': {'stats': stats.serialize_stats(),'stats_total': stats.total.get_stripped_report(),'errors': stats.serialize_errors(),'user_count': user_count}}]}
                    self.forwarder_queue.put(message)

            if is_standalone and self.send_details:
                    self.forwarder_queue_details.put(data)

            if is_worker and self.send_details:
                self.forwarder_queue_details.put(data)

    def quitting(self):
        print("quitting from base adapter")
        self.quit = True
        for backend in self.backends:
            backend.finalize()

    def run(self):
        print("Started forwarder run loop for stats...")
        # forwarder pops a value and uses a list of adapters to forward it to different sinks
        while not self.quit:
            data = self.forwarder_queue.get()
            for backend in self.backends:
                backend.send(data,topic_name='locust')

    def run_details(self):
        print("Started forwarder run loop for details...")
        # forwarder pops a value and uses a list of adapters to forward it to different sinks
        while not self.quit:
            data = self.forwarder_queue_details.get()
            for backend in self.backends:
                backend.send(data,topic_name='locust_details')
class KafkaLocustLoadAdapter():
    def __init__(self, Environment, kafka_hosts=["localhost:9092"]):
        self.quit = False
        self.Environment = Environment
        self.consumer = KafkaConsumer('locust_order',bootstrap_servers=kafka_hosts,value_deserializer=lambda x: loads(x.decode('utf-8')))

    def run(self):
        for message in self.consumer:
            newuser = 0
            message = message.value
            if debug:
                print("message:", message)
            if 'order' in message and (('spawn_rate' in message and 'level' in message and message['order'] != 'stop' and message['order'] != 'reset') or (message['order'] == 'reset') or (message['order'] == 'stop')):
                self.Environment.reset_stats = False
                if message['order'] == 'set_user_level':
                    if self.Environment.runner.target_user_count == None or self.Environment.runner.state == 'stopped':
                        if debug:
                            print("injection was not started")
                            print("injection will start with specified user number:", message['level'])
                            print("Start injection with spawn_rate:", message['spawn_rate'])
                    else:
                        if debug:
                            print("changing user number to:", message['level'])
                            print("changing user number at spawn rate:", message['spawn_rate'])
                    if (self.Environment.runner.target_user_count != message['level'] and self.Environment.runner.state != 'stopped') or self.Environment.runner.state == 'stopped':
                        self.Environment.runner.start(message['level'], message['spawn_rate'])
                    else:
                        if debug:
                            print("current user level is the same as asked user level. Do nothing")
                if message['order'] == 'stop':
                    if debug:
                        print("stopping injection")
                    self.Environment.runner.stop()
                if message['order'] == 'step_user_level':
                    if debug:
                        print("changing user number with level:", message['level'])
                        print("changing at spawn rate:", message['spawn_rate'])
                    if self.Environment.runner.target_user_count == None:
                        if debug:
                            print("injection was not started")
                            print("injection will start with specified level only if level is upper than 0")
                        if message['level'] > 0:
                            newuser = message['level']
                            if debug:
                                print("new user number:", newuser)
                        else:
                            if debug:
                                print("level is negative so injection will not use this setting to start")
                    else:
                        newuser = self.Environment.runner.target_user_count + message['level']
                        if debug:
                            print("current user number:", self.Environment.runner.target_user_count)
                            print("new user number:", newuser)
                    if newuser != 0:
                        self.Environment.runner.start(newuser,message['spawn_rate'])
                if message['order'] == 'reset':
                    if debug:
                        print("resetting stats")
                    if self.Environment.runner.target_user_count == None or self.Environment.runner.state == 'stopped':
                        self.Environment.reset_stats = True
                        self.Environment.runner.start(0,1)
                        self.Environment.reset_stats = False
                        self.Environment.runner.stop()
                    else:
                        if debug:
                            print("current user number:", self.Environment.runner.target_user_count)
                            print("current spawn_rate:", self.Environment.runner.spawn_rate)
                        self.Environment.reset_stats = True
                        self.Environment.runner.start(self.Environment.runner.target_user_count,self.Environment.runner.spawn_rate)
                if self.quit:
                    break
            else:
                if 'order' not in message:
                    print("order field missing in message")
                if 'order' in message and message['order'] != 'stop' and 'spawn_rate' not in message:
                    print("spawn_rate field missing in message")
                if 'order' in message and message['order'] != 'stop' and 'level' not in message:
                    print("level field missing in message")

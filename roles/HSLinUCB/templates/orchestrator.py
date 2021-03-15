# Software Name : HSLinUCB
# SPDX-FileCopyrightText: Copyright (c) 2021 Orange
# SPDX-License-Identifier: GPL-2.0
#
# This software is distributed under the GNU General Public License v2.0 license
#
# Author: David DELANDE <david.delande@orange.com> et al.

from pathlib import Path
import time
from datetime import datetime
import sys
import os
import re
import sdnotify
from threading import Thread
from kafka import TopicPartition
from kafka import KafkaProducer
from kafka import KafkaConsumer
from json import loads
from json import dumps
import pandas as pd
import numpy as np
import json
import urllib3
from collections import OrderedDict
http = urllib3.PoolManager()

from kubernetes import client, config
from kubernetes.client.models.v1_scale import V1Scale

pd.set_option("display.max_rows", None, "display.max_columns", None)


#Locust
locust_debug = False

#Zipkin
zipkin_dataframe_trace_number = 30 #Number of unique traceid to keep in the dataframe (a unique traceid can be shared across multiple service endpoints)
zipkin_debug = False

#Metric server
metricserver_dataframe_trace_number = 3 #30
metricserver_WaitBetweenCall = 5 #In seconds
metricserver_debug = False

#Prometheus
prometheus_dataframe_trace_number = 30
prometheus_WaitBetweenCall = 5 #In seconds
prometheus_debug = False

#Orchestrator
orchestrator_debug = True

class Orchestrator(Thread):

    def __init__(self, consumer_locust=None, consumer_zipkin=None, consumer_prometheus=None,consumer_metricserver=None,debug=orchestrator_debug):
        Thread.__init__(self)
        self.last_component_count = {}
        self.debug=orchestrator_debug
        self.debug_level = 1
        self.consumer_locust = consumer_locust
        self.consumer_zipkin = consumer_zipkin
        self.consumer_metricserver = consumer_metricserver
        self.consumer_prometheus = consumer_prometheus
        self.orchestrator_consumer = KafkaConsumer('action',bootstrap_servers=['{{hostvars[groups['master'][0]].ansible_default_ipv4.address}}:{{kafka_component.spec.ports[0].port}}'],value_deserializer=lambda x: loads(x.decode('utf-8')))
        self.kafka_producer = KafkaProducer(bootstrap_servers = ['{{hostvars[groups['master'][0]].ansible_default_ipv4.address}}:{{kafka_component.spec.ports[0].port}}'],acks='all',max_request_size=104858800,compression_type='gzip',value_serializer=lambda x: dumps(x).encode('utf-8'))
        self.RestartOnLastMessage = False #When unpaused if True continue reading from kafka from last message. If False continue reading from position at stop time.
        self.lookback = 12
        self.pause = False
        self.deployment_limit = {"front-dynamic-component": {"min": 1, "max":30},"back-dynamic-component": {"min": 1, "max": 30}, "back2-dynamic-component": {"min": 1, "max": 30}} 
        if os.path.exists('/var/run/secrets/kubernetes.io/serviceaccount/token'):
            config.load_incluster_config()
            print("connection inside kubernetes")
        else:
            try:
                config.load_kube_config()
                print("connection outside kubernetes")
            except:
                print('Unable to find cluster configuration')
                exit(1)

    def setZipkinLookback(self,message):
        transactionId = 0
        if message != None:
           if 'transactionId' in message:
                transactionId = message['transactionId']
           if 'lookback' in message:
               self.lookback = message['lookback']
               self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'result': 'OK'})
           else:
               if self.debug:
                   print("lookback field missing in message")
               self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'result': 'ERROR', 'reason': 'lookback field missing in message'})
        self.kafka_producer.flush()

    def setZipkinService(self,message):
        transactionId = 0
        if message != None:
           if 'transactionId' in message:
                transactionId = message['transactionId']
           if 'services' in message:
               services=[]
               for service in message['services']:
                   services.append(service)
               self.consumer_zipkin.service = services 
               self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'result': 'OK'})
        self.kafka_producer.flush()

    def setPrometheusService(self,message):
        transactionId = 0
        if message != None:
           if 'transactionId' in message:
                transactionId = message['transactionId']
           if 'services' in message:
               services=[]
               for service in message['services']:
                   services.append(service)
               self.consumer_prometheus.services = services
               self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'result': 'OK'})
        self.kafka_producer.flush()

    def getDeploymentState(self,message):
        transactionId = 0
        if message != None:
           if 'transactionId' in message:
                transactionId = message['transactionId']
           if 'deployment' in message:
               try:
                   appsv1 = client.AppsV1Api()
                   default_deploy = appsv1.list_namespaced_deployment(namespace='default',label_selector="app=" + message['deployment'])
                   if self.debug:
                       print("desired replicas from deployment:", default_deploy.items[0].status.replicas)
                       print("available front replicas from deployment:", default_deploy.items[0].status.ready_replicas)
                       print("unavailable front replicas from deployment:", default_deploy.items[0].status.unavailable_replicas)
                   replica={}
                   replica[message['deployment']] = {'desired': default_deploy.items[0].status.replicas, 'available': default_deploy.items[0].status.ready_replicas, 'unavailable': default_deploy.items[0].status.unavailable_replicas }
                   self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'reason': replica , 'result': 'OK'})
               except:
                   print("exception raised in check deployment state on Kubernetes:", sys.exc_info()[0])
                   self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'result': 'ERROR', 'reason': 'exception raised in check deployment state on Kubernetes'})
        self.kafka_producer.flush()
               

    def getConfig(self,message):
        transactionId = 0
        if message != None:
           if 'transactionId' in message:
                transactionId = message['transactionId']
           config = {}
           config['orchestrator'] = {'debug': self.debug, 'debug_level': self.debug_level, 'deployment_limit': self.deployment_limit, 'lookback': self.lookback}
           config['zipkin'] = {'debug': self.consumer_zipkin.debug, 'debug_level': self.consumer_zipkin.debug_level, 'dataframe_trace_number': self.consumer_zipkin.dataframe_trace_number,'RestartOnLastMessage': self.consumer_zipkin.RestartOnLastMessage, 'pause': self.consumer_zipkin.pause, 'zipkin_service': self.consumer_zipkin.service}
           config['prometheus'] = {'debug': self.consumer_prometheus.debug, 'debug_level': self.consumer_prometheus.debug_level, 'dataframe_trace_number': self.consumer_prometheus.dataframe_trace_number, 'waitBetweenCall': self.consumer_prometheus.waitBetweenCall, 'pause': self.consumer_prometheus.pause, 'last_component_number': self.consumer_prometheus.last_component_number, 'sample_number_before_accepting_scaling': self.consumer_prometheus.sample_number_before_accepting_scaling}
           if self.debug:
               print("configuration:", config)
           self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'reason': config , 'result': 'OK'})
        self.kafka_producer.flush()

    def setSampleNumberBeforeAcceptScaling(self,message):
        transactionId = 0
        if message != None:
           if 'transactionId' in message:
                transactionId = message['transactionId']
        if 'number' in message:
            self.consumer_prometheus.sample_number_before_accepting_scaling = message['number']
            self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'number': message['number'] , 'result': 'OK'})
        else:
            if self.debug:
                print("number field missing in message")
            self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'result': 'ERROR', 'reason': 'number field missing in setSampleNumberBeforeAcceptScaling order'})
        self.kafka_producer.flush()

    def setDeploymentLimit(self,message):
        transactionId = 0
        if message != None:
           if 'transactionId' in message:
                transactionId = message['transactionId']
           if 'deployment' in message:
               if 'min' in message:
                   if 'max' in message:
                       self.deployment_limit[message['deployment']] = {"min": message['min'], "max": message['max']}
                       self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'result': 'OK'})
                   else:
                       if self.debug:
                           print("max field missing in setDeploymentLimit order")
                       self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'result': 'ERROR', 'reason': 'max field missing in setDeploymentLimit order'})
               else:
                   if self.debug:
                       print("min field is missing in message")
                   self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'result': 'ERROR', 'reason': 'min field missing in setDeploymentLimit order'})
           else:
               if self.debug:
                   print("deployment filed missing in message")
               self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'result': 'ERROR', 'reason': 'deployment field missing in setDeploymentLimit order'})
        self.kafka_producer.flush()

    def activateDebug(self, message):
        transactionId = 0
        if message != None:
           if 'transactionId' in message:
                transactionId = message['transactionId']
        if message['order'] == 'activateDebug':
            if 'component' not in message:
                print("component field missing in activateDebug order")
                self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'result': 'ERROR', 'reason': 'component field missing in activateDebug order'})
            else:
                if message['component'] == 'orchestrator':
                    if 'level' in message:
                        print("Set orchestrator debug level to: ", message['level'])
                        self.debug_level = message['level']
                    print("activate debugging for orchestrator component")
                    self.debug = True
                    self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'component': 'orchestrator', 'result': 'OK'})
                if message['component'] == 'zipkin':
                    if 'level' in message:
                        print("Set zipkin debug level to: ", message['level'])
                        self.consumer_zipkin.debug_level = message['level']
                    print("activate debugging for zipkin thread")
                    self.consumer_zipkin.debug = True
                    self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'component': 'zipkin' , 'result': 'OK'})
                if message['component'] == 'prometheus':
                    if 'level' in message:
                        print("Set prometheus debug level to :", message['level'])
                        self.consumer_prometheus.debug_level = message['level']
                    print("activate debugging for prometheus thread")
                    self.consumer_prometheus.debug = True
                    self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'component': 'prometheus' , 'result': 'OK'})
                if message['component'] != 'orchestrator' and message['component'] != 'zipkin' and message['component'] != 'prometheus':
                    print("unknown component specified")
                    self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] ,'result': 'ERROR', 'reason': 'unknown component specified'})
        self.kafka_producer.flush()

    def deactivateDebug(self, message):
        transactionId = 0
        if message != None:
           if 'transactionId' in message:
                transactionId = message['transactionId']
        if message['order'] == 'deactivateDebug':
            if 'component' not in message:
                print("component field missing in activateDebug order")
                self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'result': 'ERROR', 'reason': 'component field missing in activateDebug order'})
            else:
                if message['component'] == 'orchestrator':
                    print("deactivate debugging for orchestrator component")
                    self.debug = False
                    self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'component': 'orchestrator' , 'result': 'OK'})
                if message['component'] == 'zipkin':
                    print("deactivate debugging for zipkin thread")
                    self.consumer_zipkin.debug = False
                    self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'component': 'zipkin' , 'result': 'OK'})
                if message['component'] == 'prometheus':
                    print("deactivate debugging for prometheus thread")
                    self.consumer_prometheus.debug = False
                    self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'component': 'prometheus' , 'result': 'OK'})
                if message['component'] != 'orchestrator' and message['component'] != 'zipkin' and message['component'] != 'prometheus':
                    print("unknown component specified")
                    self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'result': 'ERROR', 'reason': 'unknown component specified'})
        self.kafka_producer.flush()

    def ResetZipkinStats(self, message):
        transactionId = 0
        if message != None:
           if 'transactionId' in message:
                transactionId = message['transactionId']
           if message['order'] == 'resetZipkinStats':
               print("reseting zipkin stats")
               self.consumer_zipkin.reset()
               self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'result': 'OK'})
        self.kafka_producer.flush()

    def ResetPrometheusStats(self, message):
        transactionId = 0
        if message != None:
           if 'transactionId' in message:
                transactionId = message['transactionId']
           if message['order'] == 'resetPrometheusStats':
               print("reseting prometheus stats")
               self.consumer_prometheus.reset()
               self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'result': 'OK'})
        self.kafka_producer.flush()
   
    def ResetZipkinPrometheusStats(self, message):
        transactionId = 0
        if message != None:
           if 'transactionId' in message:
                transactionId = message['transactionId']
           if message['order'] == 'resetZipkinPrometheusStats':
               print("reseting zipkin and prometheus stats")
               self.consumer_zipkin.reset()
               self.consumer_prometheus.reset()
               self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'], 'result': 'OK'})
        self.kafka_producer.flush()

    def StopZipkinThread(self, message):
        transactionId = 0
        if message != None:
           if 'transactionId' in message:
                transactionId = message['transactionId']
           if message['order'] == 'stopZipkin':
               print("stopping zipkin thread") 
               self.consumer_zipkin.stop() 
               self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'result': 'OK'})
        self.kafka_producer.flush()

    def StartZipkinThread(self, message):
        transactionId = 0
        if message != None:
           if 'transactionId' in message:
                transactionId = message['transactionId']
           if message['order'] == 'startZipkin':
               print("starting zipkin thread") 
               self.consumer_zipkin.unstop()
               self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'result': 'OK'})
        self.kafka_producer.flush()

    def StopPrometheusThread(self, message):
        transactionId = 0
        if message != None:
           if 'transactionId' in message:
                transactionId = message['transactionId']
           if message['order'] == 'stopPrometheus':
               print("stopping prometheus thread")
               self.consumer_prometheus.stop() 
               self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'result': 'OK'})
        self.kafka_producer.flush()

    def StartPrometheusThread(self, message):
        transactionId = 0
        if message != None:
           if 'transactionId' in message:
                transactionId = message['transactionId']
           if message['order'] == 'startPrometheus':
               print("starting prometheus thread")
               self.consumer_prometheus.unstop()
               self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'result': 'OK'})
        self.kafka_producer.flush()

    def StopZipkinPrometheusThread(self, message):
        transactionId = 0
        if message != None:
           if 'transactionId' in message:
                transactionId = message['transactionId']
           if message['order'] == 'stopZipkinPrometheus':
               print("stopping zipkin and prometheus thread")
               self.consumer_zipkin.stop() 
               self.consumer_prometheus.stop()
               self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'result': 'OK'})
        self.kafka_producer.flush()

    def StartZipkinPrometheusThread(self, message):
        transactionId = 0
        if message != None:
           if 'transactionId' in message:
                transactionId = message['transactionId']
           if message['order'] == 'startZipkinPrometheus':
               print("starting zipkin and prometheus thread")
               self.consumer_zipkin.unstop()
               self.consumer_prometheus.unstop()
               self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'result': 'OK'})
        self.kafka_producer.flush()

    def ChangeScaling(self,message=None,waitKubernetes = True,waitPrometheus = True): 
        if self.debug: 
            print("In scaling function")
        mode = None
        level = None
        deployment = None
        transactionId = 0
        if message != None:
            if 'transactionId' in message:
                transactionId = message['transactionId']
            if 'useMetricServer' in message and message['useMetricServer'] == True:
                useMetricServer = True
            else:
                useMetricServer = False
            if 'waitPrometheus' in message and message['waitPrometheus'] == True and useMetricServer == False:
                waitPrometheus = True
            else:
                waitPrometheus = False
            if 'waitKubernetes' in message and message['waitKubernetes'] == True:
                waitKubernetes = True
            else:
                waitKubernetes = False 
            if 'deployment' in message:
                if self.debug:
                    print("change deployment:", message['deployment'])
                deployment = message['deployment']
                if 'mode' in message and message['mode'] == 'incremental':
                    if self.debug:
                        print("change with incremental mode")
                    mode = 'incremental'
                if 'mode' in message and message['mode'] == 'fixed':
                    if self.debug:
                        print("change with fixed mode")
                    mode = 'fixed'
                if 'mode' in message and message['mode'] != 'incremental' and message['mode'] != 'fixed':
                    print("not understood mode in scaling function. Message:", message)
                if 'level' not in message:
                    print("level field missing in scaling function. Message:", message)
                else:
                    #if message['level'] <= 0 and message['mode'] == 'fixed':
                    if message['level'] < self.deployment_limit[deployment]['min'] and message['mode'] == 'fixed':
                        print("Requested component number is less than min limit for the specified deployment. Set requested component deployment to lower limit number")
                        #level = 1
                        level = self.deployment_limit[deployment]['min']
                    elif message['level'] > self.deployment_limit[deployment]['max'] and message['mode'] == 'fixed':
                        print("Requested component number is upper than max limit for the specified deployment. Set requested component deployment to upper limit number")
                        level = self.deployment_limit[deployment]['max']
                    else:
                        if self.debug:
                            print("requested component number:", message['level'])
                        level = message['level']
                if mode == 'fixed' and level != None:
                    if self.debug:
                        print("In fixed scaling")
                    try:
                        appsv1 = client.AppsV1Api()
                        default_deploy = appsv1.list_namespaced_deployment(namespace='default',label_selector="app=" + deployment)
                        if self.debug:
                            print("current desired replicas from deployment:", default_deploy.items[0].status.replicas)
                        current_component_number = default_deploy.items[0].status.replicas
                        if current_component_number != level:
                            if self.debug:
                                print("scaling to requested component number:", level)
                            body = V1Scale()
                            body.spec = {'replicas': level}
                            appsv1.patch_namespaced_deployment_scale(name=deployment,namespace='default', body=body)
                        else:
                            if self.debug:
                                print("requested component number is already asked in kubernetes")
                    except:
                        print("exception raised in scaling:", sys.exc_info()[0])
                        self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'deployment': message['deployment'] , 'level': message['level'] , 'mode': message['mode'] , 'result': 'ERROR', 'reason': 'Error in calling kubernetes API for scaling'})
                        self.kafka_producer.flush()
                        return
                    if waitKubernetes:
                            try:
                                self.WaitForKubernetesScalingDone(deployment,level)
                            except:
                                self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'deployment': message['deployment'] , 'level': message['level'] , 'mode': message['mode'] , 'result': 'ERROR', 'reason': 'Error in calling kubernetes API for scaling check'})
                                self.kafka_producer.flush()
                                return
                    if waitPrometheus:
                            try:  
                                self.WaitForPrometheusScalingDone(deployment,level,useMetricServer = False)
                            except:
                                self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'deployment': message['deployment'] , 'level': message['level'] , 'mode': message['mode'] , 'result': 'ERROR', 'reason': 'Error in calling Prometheus for scaling check'})
                                self.kafka_producer.flush()
                                return
                    if useMetricServer:
                            try:
                                self.WaitForPrometheusScalingDone(deployment,level,useMetricServer = True)
                            except:
                                self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'deployment': message['deployment'] , 'level': message['level'] , 'mode': message['mode'] , 'result': 'ERROR', 'reason': 'Error in calling MetricServer for scaling check'})
                                self.kafka_producer.flush()
                                return

                if mode == 'incremental' and level != None:
                    if self.debug:
                        print("In incremental scaling")
                    current_component_number = -1
                    try:
                        appsv1 = client.AppsV1Api()
                        default_deploy = appsv1.list_namespaced_deployment(namespace='default',label_selector="app=" + deployment)
                        if self.debug:
                            print("current desired replicas from deployment:", default_deploy.items[0].status.replicas)
                        current_component_number = default_deploy.items[0].status.replicas
                        if current_component_number != None:
                            new_component_number = current_component_number + level
                        else:
                            new_component_number = level
                        if new_component_number < self.deployment_limit[deployment]['min']:
                        #if new_component_number <= 0:
                            #print("No component left after applying requested component number. Set component number to 1")
                            print("New component number is less than lower limit for requested deployment. Set component number to deployment lower limit")
                            new_component_number = self.deployment_limit[deployment]['min']
                            #new_component_number = 1
                        elif new_component_number > self.deployment_limit[deployment]['max']:
                            print("New component number is upper than upper limit for requested deployment. Set component number to deployment upper limit")
                            new_component_number = self.deployment_limit[deployment]['max']
                        if self.debug:
                            print("scaling to new requested component number:", new_component_number)
                        body = V1Scale()
                        body.spec = {'replicas': new_component_number}
                        appsv1.patch_namespaced_deployment_scale(name=deployment,namespace='default', body=body)
                    except:
                        print("exception raised in scaling:", sys.exc_info()[0])
                        self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'deployment': message['deployment'] , 'level': message['level'] , 'mode': message['mode'] , 'result': 'ERROR', 'reason': 'Error in calling Kubernetes API for scaling'})
                        self.kafka_producer.flush()
                    if waitKubernetes:
                        try:
                            self.WaitForKubernetesScalingDone(deployment,new_component_number)
                        except:
                            self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'deployment': message['deployment'] , 'level': message['level'] , 'mode': message['mode'] , 'result': 'ERROR', 'reason': 'Error in calling Kubernetes API for scaling check'})
                            self.kafka_producer.flush()
                            return
                    if waitPrometheus:
                        try:
                            self.WaitForPrometheusScalingDone(deployment,new_component_number, useMetricServer = False)
                        except:
                            self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'deployment': message['deployment'] , 'level': message['level'] , 'mode': message['mode'] , 'result': 'ERROR', 'reason': 'Error in calling Prometheus for scaling check'})
                            self.kafka_producer.flush()
                            return
                    if useMetricServer:
                        try:
                            self.WaitForPrometheusScalingDone(deployment,new_component_number, useMetricServer = True)
                        except:
                            self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'deployment': message['deployment'] , 'level': message['level'] , 'mode': message['mode'] , 'result': 'ERROR', 'reason': 'Error in calling MetricServer for scaling check'})
                            self.kafka_producer.flush()
                            return
                self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'deployment': message['deployment'] , 'level': message['level'] , 'mode': message['mode'] , 'result': 'OK'})
            else:
                print('deployment field missing in scaling.message:', message)
                self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'level': message['level'] , 'mode': message['mode'] , 'result': 'ERROR', 'reason': 'deployment field missing'})
                self.kafka_producer.flush()

    def WaitForKubernetesScalingDone(self,deployment,component_number):
        if self.debug:
            print("In wait for kubernetes scaling")
        if component_number == 0:
            component_number = None
        current_component_number = -1
        while(current_component_number != component_number):
            try:
                appsv1 = client.AppsV1Api()
                default_deploy = appsv1.list_namespaced_deployment(namespace='default',label_selector="app=" + deployment)
                current_component_number = default_deploy.items[0].status.ready_replicas
                if current_component_number == component_number:
                    break
            except:
                print("exception raised in check scaling on Kubernetes:", sys.exc_info()[0])
            if self.debug:
                print("Scaling is not ready on kubernetes side, wait 1 second for next call on kubernetes...")
            time.sleep(1)
        if self.debug:
            print("Scaling ready on kubernetes side")
    
    def WaitForPrometheusScalingDone(self,deployment,component_number,useMetricServer = False):
        if useMetricServer:
            if self.debug:
                print("In wait for MetricServer scaling")
            if component_number == 0:
                component_number = None
            current_component_number = -1
            while(current_component_number != component_number):
                try:
                    if self.debug:
                        print("Component number seen by MetricServer thread:", self.consumer_metricserver.last_component_number[deployment])
                    current_component_number = self.consumer_metricserver.last_component_number[deployment]
                    if int(current_component_number) == int(component_number):
                        break
                except:
                    print('Orchestrator thread: MetricServer call error')
                if self.debug:
                    print("Scaling is not ready on MetricServer side, wait 1 second for next call on MetricServer...")
                time.sleep(1)
            self.consumer_metricserver.count_sample = 0
            if self.debug:
                print("Scaling ready on MetricServer side")
                print("Waiting for: ", self.consumer_metricserver.sample_number_before_accepting_scaling ," measure from MetricServer thread before accepting scaling")
            while self.consumer_metricserver.count_sample < self.consumer_metricserver.sample_number_before_accepting_scaling:
                if self.debug:
                    print("Wait for measure...", self.consumer_metricserver.count_sample , " on ", self.consumer_metricserver.sample_number_before_accepting_scaling)
                time.sleep(1)
        else:
            if self.debug:
                print("In wait for prometheus scaling")
            if component_number == 0:
                component_number = None
            current_component_number = -1
            while(current_component_number != component_number):
                try:
                    if self.debug:
                        print("Component number seen by prometheus thread:", self.consumer_prometheus.last_component_number[deployment])
                    current_component_number = self.consumer_prometheus.last_component_number[deployment]
                    if int(current_component_number) == int(component_number):
                        break
                except:
                    print('Orchestrator thread: Prometheus call error')
                if self.debug:
                    print("Scaling is not ready on prometheus side, wait 1 second for next call on prometheus...")
                time.sleep(1)
            self.consumer_prometheus.count_sample = 0
            if self.debug:
                print("Scaling ready on prometheus side")
                print("Waiting for: ", self.consumer_prometheus.sample_number_before_accepting_scaling ," measure from prometheus thread before accepting scaling")
            while self.consumer_prometheus.count_sample < self.consumer_prometheus.sample_number_before_accepting_scaling:
                if self.debug:
                    print("Wait for measure...", self.consumer_prometheus.count_sample , " on ", self.consumer_prometheus.sample_number_before_accepting_scaling)
                time.sleep(1)

    def GetLocustState(self):
        self.consumer_locust.generate_view = True
        while not self.consumer_locust.view_ready:
            print("Wait for locust view")
            time.sleep(1)
        print("locust view ready")
        locust_state = self.consumer_locust.retrieveView()
        print("locust state:", locust_state)
        return locust_state

    def GetState(self,message = None):
        transactionId = 0
        if 'transactionId' in message:
            transactionId = message['transactionId']
        dataframe_header = ['traceId','parentId','id','kind','name','timestamp','duration','serviceName','ipv4','component','downstream_cluster','http_method','http_protocol','http_status','http_url','node_id','peer_address','request_size','response_flags','response_size','upstream_cluster','user_agent']
        latency_dataframe = pd.DataFrame(data=[],columns=dataframe_header)
        getZipkin = True
        getPrometheus = True
        externalScaling = False
        if 'externalScaling' in message and message['externalScaling'] == True:
            externalScaling = True
        self.consumer_locust.generate_view = True
        if 'prometheusOnly' in message and message['prometheusOnly'] == True:
            getZipkin = False
        if 'zipkinOnly' in message and message['zipkinOnly'] == True:
            getPrometheus = False
        if externalScaling:
            if self.debug:
                print("Check scaling with external scaler")
            for service in self.consumer_prometheus.services:
                print("monitorized service in prometheus:", service)
                if service not in self.last_component_count:
                    self.last_component_count[service] = {'desired': 0, 'available': 0, 'unavailable': 0} 
                print("last desired component:", self.last_component_count[service]['desired'])
                try:
                    appsv1 = client.AppsV1Api()
                    default_deploy = appsv1.list_namespaced_deployment(namespace='default',label_selector="app=" + service)
                except:
                    print("exception raised in scaling:", sys.exc_info()[0])
                if self.debug:
                    print("current desired replicas from deployment:", default_deploy.items[0].status.replicas)
                    print("current available replicas from deployment:", default_deploy.items[0].status.ready_replicas)
                    print("unavailable replicas from deployment:", default_deploy.items[0].status.unavailable_replicas)
                desired_component_number = default_deploy.items[0].status.replicas
                available_component_number = default_deploy.items[0].status.ready_replicas
                if self.last_component_count[service]['desired'] == 0:
                    print("initialize desired component count as first round")
                    self.last_component_count[service]['desired'] = desired_component_number
                if self.last_component_count[service]['available'] == 0:
                    print("initialize available component count as first round")
                    self.last_component_count[service]['available'] = available_component_number
                if desired_component_number != self.last_component_count[service]['desired']:
                    self.last_component_count[service]['desired'] = desired_component_number
                    print("desired component number is differente from previous desired component number")
                    self.WaitForKubernetesScalingDone(service,desired_component_number)
                    self.WaitForPrometheusScalingDone(service,desired_component_number, useMetricServer = False)
                    self.last_component_count[service]['available'] = desired_component_number
                else:
                    print("desired component number and current component number are equals")

        if getPrometheus:
            self.consumer_prometheus.generate_view = True
        if getZipkin:
            self.consumer_zipkin.generate_view = True
        if getPrometheus:
            while not self.consumer_prometheus.view_ready:
                print("Wait for prometheus view")
                print("prometheus count sample:", self.consumer_prometheus.count_sample)
                time.sleep(1)
            print("prometheus view ready")
            prometheus_view = self.consumer_prometheus.retrieveView()
        else:
            prometheus_view = self.consumer_prometheus.retrieveView(empty = True)
        if getZipkin:
            while not self.consumer_zipkin.view_ready:
                print("Wait for zipkin view")
                time.sleep(1)
            print("zipkin views ready")
            zipkin_view = self.consumer_zipkin.retrieveView()
        else:
            zipkin_view = self.consumer_zipkin.retrieveView(empty = True)
        locust_view = self.consumer_locust.retrieveView()
        latency_dataframe = pd.DataFrame(zipkin_view, columns=dataframe_header)
        for trace in latency_dataframe.loc[latency_dataframe['response_flags'] == 'DC']['traceId']:
            latency_dataframe = latency_dataframe[latency_dataframe['traceId'] != trace]
        if self.debug and self.debug_level == 2:
            print("latency dataframe before applying timestamp filter:", latency_dataframe)
        print("lookback: ", self.lookback, " seconds")
        timestamp = int(str(time.time())[:10])
        print("current time:", datetime.fromtimestamp(timestamp))
        timestamp = timestamp - self.lookback
        print("back in time for retrieving record:", datetime.fromtimestamp(timestamp))
        print("complete latency dataframe entry number:", len(latency_dataframe))
        latency_dataframe = latency_dataframe[(latency_dataframe['timestamp'] >= datetime.fromtimestamp(timestamp))]
        print("latency dataframe entry number returned to lib:", len(latency_dataframe)) 
        if self.debug and self.debug_level == 2:
            print("latency dataframe after applying timestamp filter:", latency_dataframe)
        zipkin_json = latency_dataframe.to_json(orient="split")
        prometheus_json = prometheus_view.to_json(orient="split")
        state_message = {'transactionId': transactionId, "zipkin": zipkin_json, "prometheus": prometheus_json, "locust": locust_view}
        returnKafka = self.kafka_producer.send('state', value=state_message)
        print("return kafka:", vars(returnKafka))
        self.kafka_producer.flush()
        self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'result': 'OK'})
        self.kafka_producer.flush()

    def GetStateMetricServer(self,message = None):
        transactionId = 0
        if 'transactionId' in message:
            transactionId = message['transactionId']
        dataframe_header = ['traceId','parentId','id','kind','name','timestamp','duration','serviceName','ipv4','component','downstream_cluster','http_method','http_protocol','http_status','http_url','node_id','peer_address','request_size','response_flags','response_size','upstream_cluster','user_agent']
        latency_dataframe = pd.DataFrame(data=[],columns=dataframe_header)
        getZipkin = True
        getMetricServer = True
        self.consumer_locust.generate_view = True
        if 'prometheusOnly' in message and message['prometheusOnly'] == True:
            getZipkin = False
        if 'zipkinOnly' in message and message['zipkinOnly'] == True:
            getPrometheus = False
        if getMetricServer:
            self.consumer_metricserver.generate_view = True
        if getZipkin:
            self.consumer_zipkin.generate_view = True
        if getMetricServer:
            while not self.consumer_metricserver.view_ready:
                print("Wait for MetricServer view")
                time.sleep(1)
            print("MetricServer view ready")
            metricserver_view = self.consumer_metricserver.retrieveView()
        else:
            metricserver_view = self.consumer_metricserver.retrieveView(empty = True)
        if getZipkin:
            while not self.consumer_zipkin.view_ready:
                print("Wait for zipkin view")
                time.sleep(1)
            print("zipkin views ready")
            zipkin_view = self.consumer_zipkin.retrieveView()
        else:
            zipkin_view = self.consumer_zipkin.retrieveView(empty = True)
        locust_view = self.consumer_locust.retrieveView()
        latency_dataframe = pd.DataFrame(zipkin_view, columns=dataframe_header)
        for trace in latency_dataframe.loc[latency_dataframe['response_flags'] == 'DC']['traceId']:
            latency_dataframe = latency_dataframe[latency_dataframe['traceId'] != trace]
        if self.debug and self.debug_level == 2:
            print("latency dataframe before applying timestamp filter:", latency_dataframe)
        print("lookback: ", self.lookback, " seconds")
        timestamp = int(str(time.time())[:10])
        print("current time:", datetime.fromtimestamp(timestamp))
        timestamp = timestamp - self.lookback
        print("back in time for retrieving record:", datetime.fromtimestamp(timestamp))
        print("complete latency dataframe entry number:", len(latency_dataframe))
        latency_dataframe = latency_dataframe[(latency_dataframe['timestamp'] >= datetime.fromtimestamp(timestamp))]
        print("latency dataframe entry number returned to lib:", len(latency_dataframe))
        if self.debug and self.debug_level == 2:
            print("latency dataframe after applying timestamp filter:", latency_dataframe)
        zipkin_json = latency_dataframe.to_json(orient="split")
        metricserver_json = metricserver_view.to_json(orient="split")
        state_message = {'transactionId': transactionId, "zipkin": zipkin_json, "prometheus": metricserver_json, "locust": locust_view}
        returnKafka = self.kafka_producer.send('state', value=state_message)
        print("return kafka:", vars(returnKafka))
        self.kafka_producer.flush()
        self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'result': 'OK'})
        self.kafka_producer.flush()

    def ChangeZipkinTraceNumber(self, message = None):
        if message != None:
            transactionId = 0
            if 'transactionId' in message:
                transactionId = message['transactionId']
            if 'trace_number' in message:
                if self.debug:
                    print("Change zipkin tracenumber to:", message['trace_number'])
                self.consumer_zipkin.dataframe_trace_number = message['trace_number']
                self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'component': message['component'] , 'trace_number': message['trace_number'] ,'result': 'OK'})
            else:
                print("Change Zipkin trace number [ERROR]: trace_number field missing") 
                self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'component': message['component'] ,'result': 'ERROR', 'reason': 'trace_number field missing'})
            self.kafka_producer.flush()

    def ChangePrometheusTraceNumber(self, message = None):
        if message != None:
            transactionId = 0
            if 'transactionId' in message:
                transactionId = message['transactionId']
            if 'trace_number' in message:
                if self.debug:
                    print("Change prometheus tracenumber to:", message['trace_number'])
                self.consumer_prometheus.dataframe_trace_number = message['trace_number']
                self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'component': message['component'] , 'trace_number': message['trace_number'] ,'result': 'OK'})
            else:
                print("Change Prometheus trace number [ERROR]: trace_number field missing") 
                self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'component': message['component'] ,'result': 'ERROR', 'reason': 'trace_number field missing'})
            self.kafka_producer.flush()

    def LocustOrder(self,message=None):
        if message != None:
            transactionId = 0
            if 'transactionId' in message:
                transactionId = message['transactionId']
            if self.debug:
                print("message to send to locust:", message['payload'])
            self.kafka_producer.send('locust_order' ,value=message['payload'])
            self.kafka_producer.send('action_result', value={'transactionId': transactionId , 'order': message['order'] , 'payload': message['payload'] ,'result': 'OK'})
            self.kafka_producer.flush()

    def unstop(self):
        self.pause = False

    def stop(self):
        self.pause = True

    def run(self):
        print("Orchestrator thread : started")
        for message in self.orchestrator_consumer:
            while self.pause:
                print("Orchestrator thread paused")
                if self.RestartOnLastMessage:
                    self.orchestrator_consumer.seek_to_end()
                time.sleep(1)
            message = message.value
            if self.debug:
                print(message)
            #Order: scaleSUT, RetreiveState, ChangeConfig, LocustMgmt
            if 'order' in message:
                if message['order'] == 'setZipkinLookback':
                    if self.debug:
                        print("Zipkin lookback configuration requested")
                    self.setZipkinLookback(message)
                if message['order'] == 'setZipkinService':
                    if self.debug:
                        print("Zipkin service configuration requested")
                    self.setZipkinService(message)
                if message['order'] == 'setPrometheusService':
                    if self.debug:
                        print("Prometheus service configuration requested")
                    self.setPrometheusService(message)
                if message['order'] == 'getDeploymentState':
                    if self.debug:
                        print("deployment state dump requested")
                    self.getDeploymentState(message)
                if message['order'] == 'getConfig':
                    if self.debug:
                        print("Configuration dump asked")
                    self.getConfig(message)
                if message['order'] == 'setSampleNumberBeforeAcceptScaling':
                    if self.debug:
                        print("Changing sample number before accept scaling")
                    self.setSampleNumberBeforeAcceptScaling(message)
                if message['order'] == 'scaleSUT':
                    if self.debug:
                        print("Scaling SUT ask")
                    self.ChangeScaling(message)
                if message['order'] == 'setDeploymentLimit':
                    if self.debug:
                        print("Set deployment limit")
                    self.setDeploymentLimit(message)
                if message['order'] == 'activateDebug':
                    if self.debug:
                        print("Component debug activation requested")
                    self.activateDebug(message)
                if message['order'] == 'deactivateDebug': 
                    if self.debug:
                        print("Component debug deactivation requested")
                    self.deactivateDebug(message)
                if message['order'] == 'resetZipkinStats':
                    if self.debug:
                        print("zipkin stats reset requested")
                    self.ResetZipkinStats(message)
                if message['order'] == 'resetPrometheusStats':
                    if self.debug:
                        print("prometheus stats reset requested")
                    self.ResetPrometheusStats(message)
                if message['order'] == 'resetZipkinPrometheusStats':
                    if self.debug:
                        print("zipkin and prometheus stats reset requested")
                    self.ResetZipkinPrometheusStats(message)
                if message['order'] == 'stopZipkin':
                    if self.debug:
                        print("zipkin stop requested")
                    self.StopZipkinThread(message)
                if message['order'] == 'startZipkin':
                    if self.debug:
                        print("zipkin start requested")
                    self.StartZipkinThread(message)
                if message['order'] == 'stopPrometheus':
                    if self.debug:
                        print("prometheus stop requested")
                    self.StopPrometheusThread(message)
                if message['order'] == 'startPrometheus':
                    if self.debug:
                        print("prometheus start requested")
                    self.StartPrometheusThread(message)
                if message['order'] == 'stopZipkinPrometheus':
                    if self.debug:
                        print("prometheus and zipkin stop requested")
                    self.StopZipkinPrometheusThread(message)
                if message['order'] == 'startZipkinPrometheus':
                    if self.debug:
                        print("prometheus and zipkin start requested")
                    self.StartZipkinPrometheusThread(message)
                if message['order'] == 'getZipkinState':
                    if self.debug:
                        print("Zipkin state requested")
                    self.GetZipkinState(message)
                if message['order'] == 'getPrometheusState':
                    if self.debug:
                        print("Prometheus state requested")
                    self.GetPrometheusState(message)
                if message['order'] == 'getState' and ('useMetricServer' not in message or ('useMetricServer' in message and message['useMetricServer'] == False)):
                    if self.debug:
                        print("State requested")
                    self.GetState(message)
                if message['order'] == 'getState' and 'useMetricServer' in message and message['useMetricServer'] == True:
                    if self.debug:
                        print("State with metricserver requested")
                    self.GetStateMetricServer(message)
                if message['order'] == 'ChangeConfig':
                    if self.debug:
                        print("Configuration change asked")
                    if 'component' in message and message['component'] == 'zipkin':
                        self.ChangeZipkinTraceNumber(message)
                    if 'component' in message and message['component'] == 'prometheus':
                        self.ChangePrometheusTraceNumber(message)
                if message['order'] == 'LocustMgmt':
                    if self.debug:
                        print("Locust Mgmt message")
                    self.LocustOrder(message)
            else:
                if 'order' not in message:
                    print("order field missing in message")
                #if 'order' in message and message['order'] != 'stop' and 'spawn_rate' not in message:
                #    print("spawn_rate field missing in message")
                #if 'order' in message and message['order'] != 'stop' and 'level' not in message:
                #    print("level field missing in message")

class ConsumerLocust(Thread):
    def __init__(self, debug=locust_debug):
        Thread.__init__(self)
        self.debug=debug
        self.debug_level = 1
        self.Locust_consumer = KafkaConsumer(bootstrap_servers=['{{hostvars[groups['master'][0]].ansible_default_ipv4.address}}:{{kafka_component.spec.ports[0].port}}'],value_deserializer=lambda x: loads(x.decode('utf-8')))
        self.tp = TopicPartition('locust', 0)
        self.Locust_consumer.assign([self.tp])
        self.RestartOnLastMessage = False #When unpaused if True continue reading from kafka from last message. If False continue reading from position at stop time.
        self.pause = False
        self.locust_dataframe_view = {}
        self.generate_view = False
        self.view_ready = False
        self.locust_table = {}
        self.locust_state = ''
        self.locust_target_user_count = 0
        self.locust_global_user_count = 0
        self.locust_worker_count = 0
        self.locust_last_request_timestamp = 0
        self.locust_start_time = 0
        self.locust_num_requests = 0
        self.locust_num_none_requests = 0
        self.locust_num_failure = 0
        self.locust_total_response_time = 0
        self.locust_max_response_time = 0
        self.locust_min_response_time = 0
        self.locust_total_content_length = 0
        self.locust_response_times = {}
        self.locust_num_reqs_per_sec = {}
        self.locust_num_fail_per_sec = {}

    def reset(self):
        self.locust_table = []
        self.locust_dataframe_view = None
        self.view_ready = False

    def generateView(self):
        self.generate_view = False
        self.locust_dataframe_view = {'state': self.locust_state, 'target_user_count': self.locust_target_user_count, 'global_user_count': self.locust_global_user_count, 'worker_count':self.locust_worker_count, 'last_request_timestamp':self.locust_last_request_timestamp, 'start_time':self.locust_start_time, 'num_requests':self.locust_num_requests, 'num_none_requests':self.locust_num_none_requests, 'num_failure':self.locust_num_failure, 'total_response_time': self.locust_total_response_time, 'max_response_time':self.locust_max_response_time, 'min_response_time':self.locust_min_response_time,'total_content_length':self.locust_total_content_length, 'response_times':self.locust_response_times, 'num_reqs_per_sec':self.locust_num_reqs_per_sec, 'num_fail_per_sec':self.locust_num_fail_per_sec }
        self.view_ready = True
        #self.Locust_consumer.seek_to_end()

    def retrieveView(self,empty=False):
        self.view_ready = False
        return self.locust_dataframe_view

    def unstop(self):
        self.pause = False

    def stop(self):
        self.pause = True

    def run(self):
        print("Locust thread : started")
        for message in self.Locust_consumer:
            if self.debug:
                print("locust.dataframe_trace_number:", self.dataframe_trace_number)
            while self.pause:
                if self.debug:
                    print("Locust thread paused")
                if self.RestartOnLastMessage:
                    self.Locust_consumer.seek_to_end()
                time.sleep(1)
            message = message.value
            #print("message:", message)
            if self.debug:
                print("offset:", str(self.Locust_consumer.position(self.tp)))
                print("last offset:", str(self.Locust_consumer.end_offsets([self.tp])[self.tp]))
            self.locust_state = message['state']
            self.locust_target_user_count = message['target_user_count']
            self.locust_global_user_count = message['global_user_count']
            self.locust_worker_count = message['workers_count']
            self.locust_last_request_timestamp = message['worker_jobs'][0]['payload']['stats_total']['last_request_timestamp']
            self.locust_start_time = message['worker_jobs'][0]['payload']['stats_total']['start_time']
            self.locust_num_requests = message['worker_jobs'][0]['payload']['stats_total']['num_requests']
            self.locust_num_none_requests = message['worker_jobs'][0]['payload']['stats_total']['num_none_requests']
            self.locust_num_failure = message['worker_jobs'][0]['payload']['stats_total']['num_failures']
            self.locust_total_response_time = message['worker_jobs'][0]['payload']['stats_total']['total_response_time']
            self.locust_max_response_time = message['worker_jobs'][0]['payload']['stats_total']['max_response_time']
            self.locust_min_response_time = message['worker_jobs'][0]['payload']['stats_total']['min_response_time']
            self.locust_total_content_length = message['worker_jobs'][0]['payload']['stats_total']['total_content_length']
            self.locust_response_times = message['worker_jobs'][0]['payload']['stats_total']['response_times']
            self.locust_num_reqs_per_sec = message['worker_jobs'][0]['payload']['stats_total']['num_reqs_per_sec']
            self.locust_num_fail_per_sec = message['worker_jobs'][0]['payload']['stats_total']['num_fail_per_sec']
            if self.generate_view:
                self.generateView()


class ConsumerZipkin(Thread):
# Methods:
#  retrieveView: To retrieve a generated view. This call automatically set the property generate_view to False for allowing next view generation.
#  stop: to pause zipkin thread
#  unstop: to unpause zipkin thread (the kafka stream continue at the most recent message if property RestartOnLastMessage = True or continue from stopped point if RestartOnLastMessage = False)

# Properties:
#  generate_view : Set this property to True each time you want a view generation.
#  RestartOnLastMessage = True : for restarting kafka stream at the most recent message otherwise continue from stopped point.
#  service: Array of service endpoint name to collect.  

    def __init__(self, dataframe_trace_number=zipkin_dataframe_trace_number,debug=zipkin_debug):
        Thread.__init__(self)
        self.dataframe_trace_number=dataframe_trace_number
        self.debug=debug
        self.debug_level = 1
        self.Zipkin_consumer = KafkaConsumer(bootstrap_servers=['{{hostvars[groups['master'][0]].ansible_default_ipv4.address}}:{{kafka_component.spec.ports[0].port}}'],value_deserializer=lambda x: loads(x.decode('utf-8')))
        self.tp = TopicPartition('zipkin', 0)
        self.Zipkin_consumer.assign([self.tp])
        self.RestartOnLastMessage = False #When unpaused if True continue reading from kafka from last message. If False continue reading from position at stop time.
        self.pause = False
        self.service = ['istio-ingressgateway']
        self.latency_dataframe_view = None
        self.generate_view = False
        self.view_ready = False
        self.zipkin_table = []

    def reset(self):
        self.zipkin_table = []
        self.latency_dataframe_view = None
        self.view_ready = False

    def generateView(self):
        self.generate_view = False
        self.latency_dataframe_view = self.zipkin_table
        self.view_ready = True
        #self.Zipkin_consumer.seek_to_end()

    def retrieveView(self,empty=False):
        self.view_ready = False
        return self.latency_dataframe_view

    def unstop(self):
        self.pause = False

    def stop(self):
        self.pause = True

    def run(self):    
        print("Zipkin thread : started")
        for message in self.Zipkin_consumer:
            if self.debug:
                print("zipkin.dataframe_trace_number:", self.dataframe_trace_number)
            while self.pause:
                if self.debug:
                    print("Zipkin thread paused")
                if self.RestartOnLastMessage:
                    self.Zipkin_consumer.seek_to_end()
                time.sleep(1)
            message = message.value
            if self.debug:
                print("offset:", str(self.Zipkin_consumer.position(self.tp)))
                print("last offset:", str(self.Zipkin_consumer.end_offsets([self.tp])[self.tp]))
            for trace in message:
                if trace['localEndpoint']['serviceName'] in self.service:
                    data_entry = []
                    if self.debug and self.debug_level == 2:
                        print(trace)
                        print("traceId:", trace['traceId'])
                        print("id:", trace['id'])
                        print("kind:",trace['kind'])
                        print("name:",trace['name'])
                        print("timestamp:",datetime.fromtimestamp(int(str(trace['timestamp'])[:10])))
                        print("duration:",trace['duration'] / 1000)
                        print("serviceName:",trace['localEndpoint']['serviceName'])
                        print("ipv4:",trace['localEndpoint']['ipv4'])
                        print("component:",trace['tags']['component'])
                        print("downstream_cluster:",trace['tags']['downstream_cluster'])
                        print("http.method:",trace['tags']['http.method'])
                        print("http.protocol:",trace['tags']['http.protocol'])
                        print("http.status_code:",trace['tags']['http.status_code'])
                        print("http.url:",trace['tags']['http.url'])
                        print("node_id:",trace['tags']['node_id'])
                        print("peer.address:",trace['tags']['peer.address'])
                        print("request_size:",trace['tags']['request_size'])
                        print("response_flags:",trace['tags']['response_flags'])
                        print("response_size:",trace['tags']['response_size'])
                        print("upstream_cluster:",trace['tags']['upstream_cluster'])
                        print("user_agent:",trace['tags']['user_agent'])
                    data_entry.append(trace['traceId'])
                    if 'parentId' in trace:
                        if self.debug and self.debug_level == 2:
                            print("parentId:", trace['parentId'])
                        data_entry.append(trace['parentId'])
                    else:
                        data_entry.append('-')
                        if self.debug and self.debug_level == 2:
                            print("parentId: -")
                    data_entry.append(trace['id'])
                    data_entry.append(trace['kind'])
                    data_entry.append(trace['name'])
                    data_entry.append(datetime.fromtimestamp(int(str(trace['timestamp'])[:10])))
                    data_entry.append(trace['duration'] / 1000)
                    data_entry.append(trace['localEndpoint']['serviceName']) 
                    data_entry.append(trace['localEndpoint']['ipv4'])
                    data_entry.append(trace['tags']['component'])
                    data_entry.append(trace['tags']['downstream_cluster'])
                    data_entry.append(trace['tags']['http.method'])
                    data_entry.append(trace['tags']['http.protocol'])
                    data_entry.append(trace['tags']['http.status_code'])
                    data_entry.append(trace['tags']['http.url'])
                    data_entry.append(trace['tags']['node_id'])
                    data_entry.append(trace['tags']['peer.address'])
                    data_entry.append(trace['tags']['request_size'])
                    data_entry.append(trace['tags']['response_flags'])
                    data_entry.append(trace['tags']['response_size'])
                    data_entry.append(trace['tags']['upstream_cluster'])
                    data_entry.append(trace['tags']['user_agent'])
                    self.zipkin_table.append(data_entry)
            if len(self.zipkin_table) >= self.dataframe_trace_number:
                del self.zipkin_table[0:len(self.zipkin_table) - self.dataframe_trace_number]
            if self.generate_view:
                self.generateView()

class ConsumerMetricServer(Thread):
    def __init__(self,dataframe_trace_number=metricserver_dataframe_trace_number,metricserver_WaitBetweenCall=5, debug=metricserver_debug ): # agent_producer ,
        Thread.__init__(self)
        self.debug = metricserver_debug
        self.debug_level = 1
        self.waitBetweenCall = metricserver_WaitBetweenCall
        self.pause = False
        self.ressource_dataframe_view = None
        self.generate_view = False
        self.services = ['front-dynamic-component']
        self.last_component_number = {}
        self.view_ready = False
        #self.last_component_number = 1
        self.sample_number_before_accepting_scaling = 0
        self.dataframe_trace_number = dataframe_trace_number
        self.count_sample = 0
        self.namespace = 'default'
        if os.path.exists('/var/run/secrets/kubernetes.io/serviceaccount/token'):
            config.load_incluster_config()
            print("connection inside kubernetes")
        else:
            try:
                config.load_kube_config()
                print("connection outside kubernetes")
            except:
                print('Unable to find cluster configuration')
                exit(1)
        self.conf = config.new_client_from_config()
        self.core_api = client.CoreV1Api()
        self.apis_api = client.AppsV1Api()
        self.metrics_last = {}
        self.metrics_view = {}
        self.dataframe_header = ['timestamp','component','componentNumber','cpu_usage_min','cpu_usage_max','cpu_usage_median','cpu_usage_mean','cpu_usage_std','cpu_usage_var','cpu_perc_request_min','cpu_perc_request_max','cpu_perc_request_median','cpu_perc_request_mean','cpu_perc_request_std','cpu_perc_request_var','cpu_perc_limit_min','cpu_perc_limit_max','cpu_perc_limit_median','cpu_perc_limit_mean','cpu_perc_limit_std','cpu_perc_limit_var','mem_usage_min','mem_usage_max','mem_usage_median','mem_usage_mean','mem_usage_std','mem_usage_var','mem_perc_request_min','mem_perc_request_max','mem_perc_request_median','mem_perc_request_mean','mem_perc_request_std','mem_perc_request_var','mem_perc_limit_min','mem_perc_limit_max','mem_perc_limit_median','mem_perc_limit_mean','mem_perc_limit_std','mem_perc_limit_var','recv_bandwidth_min','recv_bandwidth_max','recv_bandwidth_median','recv_bandwidth_mean','recv_bandwidth_std','recv_bandwidth_var','trans_bandwidth_min','trans_bandwidth_max','trans_bandwidth_median','trans_bandwidth_mean','trans_bandwidth_std','trans_bandwidth_var','recv_packet_min','recv_packet_max','recv_packet_median','recv_packet_mean','recv_packet_std','recv_packet_var','trans_packet_min','trans_packet_max','trans_packet_median','trans_packet_mean','trans_packet_std','trans_packet_var','recv_packet_drop_min','recv_packet_drop_max','recv_packet_drop_median','recv_packet_drop_mean','recv_packet_drop_std','recv_packet_drop_var','trans_packet_drop_min','trans_packet_drop_max','trans_packet_drop_median','trans_packet_drop_mean','trans_packet_drop_std','trans_packet_drop_var']
        self.ressource_dataframe = pd.DataFrame(data=[],columns=self.dataframe_header)

    def reset(self):
        self.ressource_dataframe = pd.DataFrame(data=[],columns=self.dataframe_header)
        self.ressource_dataframe_view = None
        self.view_ready = False

    def generateView(self):
        self.generate_view = False
        self.ressource_dataframe_view = self.ressource_dataframe
        self.view_ready = True

    def retrieveView(self,empty = False):
        self.view_ready = False
        if empty:
            return pd.DataFrame(data=[],columns=self.dataframe_header)
        else:
            return self.ressource_dataframe_view

    def unstop(self):
        self.pause = False

    def stop(self):
        self.pause = True

    def run(self):
        print("Metric server thread : started")
        while True:
            status = True
            metrics = {}
            ret= self.conf.call_api('/apis/metrics.k8s.io/v1beta1/namespaces/' + self.namespace + '/pods/', 'GET', auth_settings = ['BearerToken'], response_type='json', _preload_content=False)
            response = loads(ret[0].data.decode('utf-8'))
            for entry in response['items']:
                try:
                    pod = self.core_api.read_namespaced_pod(name=entry['metadata']['name'], namespace=self.namespace)
                except:
                    status = False
                    break
                owner_references = pod.metadata.owner_references
                if isinstance(owner_references, list):
                    owner_name = owner_references[0].name
                    owner_kind = owner_references[0].kind
                    if owner_kind == 'ReplicaSet':
                        try:
                            replica_set = self.apis_api.read_namespaced_replica_set(name=owner_name, namespace=self.namespace)
                        except:
                            status = False
                            break
                        owner_references2 = replica_set.metadata.owner_references
                        if isinstance(owner_references2, list):
                            if owner_references2[0].name not in metrics:
                                metrics[owner_references2[0].name] = {'timestamp': entry['timestamp'], 'cpu_usage': [],'cpu_usage_sum': 0, 'mem_usage': [],'mem_usage_sum': 0, 'count': 1}
                            else:
                                metrics[owner_references2[0].name]['count'] += 1
                                metrics[owner_references2[0].name]['timestamp'] = entry['timestamp']
                            cpu = 0
                            mem = 0
                            for container in entry['containers']:
                                if container['usage']['cpu'] != '0':
                                    cpu = cpu + int(container['usage']['cpu'][:-1])
                                else:
                                    status = False
                                    break
                                if container['usage']['memory'] != '0':
                                    mem = mem + int(container['usage']['memory'][:-2])
                                else:
                                    status = False
                                    break
                            if status:
                                cpu = cpu / 1000000
                                metrics[owner_references2[0].name]['cpu_usage'].append(cpu)
                                metrics[owner_references2[0].name]['cpu_usage_sum'] += cpu
                                metrics[owner_references2[0].name]['mem_usage'].append(mem)
                                metrics[owner_references2[0].name]['mem_usage_sum'] += mem
                            else:
                                break
            if status:
                isDiff = False
                if self.metrics_last == {}:
                    self.metrics_last = metrics
                    isDiff = True
                else:
                    for entry in metrics:
                        if entry not in self.metrics_last:
                            self.metrics_last[entry] = metrics[entry]
                            isDiff = True
                        else:
                            if metrics[entry]['cpu_usage_sum'] != self.metrics_last[entry]['cpu_usage_sum']:
                                isDiff = True
                            if metrics[entry]['mem_usage_sum'] != self.metrics_last[entry]['mem_usage_sum']:
                                isDiff = True
                            if isDiff:
                                self.metrics_last[entry] = metrics[entry]
                if isDiff:
                    #print("metrics last:", self.metrics_last)
                    #print("metrics can be kept")
                    #print("front component count:", self.metrics_last["front-dynamic-component"]["count"])
                    for service in self.metrics_last.keys():
                        if service not in self.last_component_number:
                            self.last_component_number[service] = 1
                        data_entry = []
                        data_entry.append(self.metrics_last[service]['timestamp'])
                        data_entry.append(service)
                        data_entry.append(self.metrics_last[service]['count'])
                        print("last seen component for service:",service,":",self.metrics_last[service]['count']) 
                        self.last_component_number[service] = self.metrics_last[service]['count']
                        data_entry.append(np.amin(self.metrics_last[service]['cpu_usage']))
                        data_entry.append(np.amax(self.metrics_last[service]['cpu_usage']))
                        data_entry.append(np.median(self.metrics_last[service]['cpu_usage']))
                        data_entry.append(np.mean(self.metrics_last[service]['cpu_usage']))
                        print("cpu usage in metric server:", np.mean(self.metrics_last[service]['cpu_usage']))
                        data_entry.append(np.std(self.metrics_last[service]['cpu_usage']))
                        data_entry.append(np.var(self.metrics_last[service]['cpu_usage']))
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        data_entry.append(0)
                        if self.debug:
                            print("data entry:", data_entry)
                        df = pd.DataFrame(data=[data_entry],columns=self.dataframe_header)
                        self.ressource_dataframe = self.ressource_dataframe.append(df, ignore_index=False)
                    if self.count_sample < self.sample_number_before_accepting_scaling:
                        self.count_sample += 1
                    if len(self.ressource_dataframe) > self.dataframe_trace_number:
                        self.ressource_dataframe = self.ressource_dataframe.iloc[len(self.ressource_dataframe) - self.dataframe_trace_number:]
                    if self.debug:
                        print("last component number:", self.last_component_number)
                        print("MetricServer thread wait ", self.waitBetweenCall, " seconds for next mesures")
                    
                    if self.generate_view:
                        self.generateView()
                else:
                    if self.debug:
                        print("reject")
            print("MetricServer thread wait ", self.waitBetweenCall, " seconds for next mesures")
            time.sleep(self.waitBetweenCall)

class ConsumerPrometheus(Thread):

    def __init__(self,dataframe_trace_number=prometheus_dataframe_trace_number,prometheus_WaitBetweenCall=5, debug=prometheus_debug ): # agent_producer ,
        Thread.__init__(self)
        self.debug = prometheus_debug
        self.debug_level = 1
        self.waitBetweenCall = prometheus_WaitBetweenCall
        self.pause = False
        self.base_url = 'http://{{hostvars[groups['master'][0]].ansible_default_ipv4.address}}:{{prometheus_component.spec.ports[0].nodePort}}/api/v1/query?query='
        self.url_cpu_usage = self.base_url + 'sum(node_namespace_pod_container:container_cpu_usage_seconds_total:sum_rate{namespace="default"} * on(namespace,pod) group_left(workload, workload_type) mixin_pod_workload{namespace="default", workload_type="deployment"} ) by (pod)'
        self.url_cpu_perc_request = self.base_url + 'sum(node_namespace_pod_container:container_cpu_usage_seconds_total:sum_rate{namespace="default"} * on(namespace,pod) group_left(workload, workload_type) mixin_pod_workload{namespace="default", workload_type="deployment"} ) by (pod) /sum(kube_pod_container_resource_requests_cpu_cores{namespace="default"} * on(namespace,pod) group_left(workload, workload_type) mixin_pod_workload{namespace="default", workload_type="deployment"} ) by (pod)'
        self.url_cpu_perc_limit = self.base_url + 'sum(node_namespace_pod_container:container_cpu_usage_seconds_total:sum_rate{namespace="default"} * on(namespace,pod) group_left(workload, workload_type) mixin_pod_workload{namespace="default", workload_type="deployment"} ) by (pod) /sum(kube_pod_container_resource_limits_cpu_cores{namespace="default"} * on(namespace,pod) group_left(workload, workload_type) mixin_pod_workload{namespace="default", workload_type="deployment"} ) by (pod)'
        self.url_mem_usage = self.base_url + 'sum(container_memory_working_set_bytes{namespace="default", container!=""} * on(namespace,pod) group_left(workload, workload_type) mixin_pod_workload{namespace="default", workload_type="deployment"} ) by (pod)'
        self.url_mem_perc_request = self.base_url + 'sum(container_memory_working_set_bytes{namespace="default", container!=""} * on(namespace,pod) group_left(workload, workload_type) mixin_pod_workload{namespace="default", workload_type="deployment"}) by (pod) /sum(kube_pod_container_resource_requests_memory_bytes{namespace="default"} * on(namespace,pod) group_left(workload, workload_type) mixin_pod_workload{namespace="default", workload_type="deployment"}) by (pod)'
        self.url_mem_perc_limit = self.base_url + 'sum(container_memory_working_set_bytes{namespace="default", container!=""} * on(namespace,pod) group_left(workload, workload_type) mixin_pod_workload{namespace="default", workload_type="deployment"} ) by (pod) /sum(kube_pod_container_resource_limits_memory_bytes{namespace="default"} * on(namespace,pod) group_left(workload, workload_type) mixin_pod_workload{namespace="default", workload_type="deployment"}) by (pod)'
        self.url_recv_bandwidth = self.base_url + '(sum(irate(container_network_receive_bytes_total{namespace="default"}[4h]) * on (namespace,pod) group_left(workload,workload_type) mixin_pod_workload{namespace="default", workload_type="deployment"}) by (pod))'
        self.url_trans_bandwidth = self.base_url + '(sum(irate(container_network_transmit_bytes_total{namespace="default"}[4h]) * on (namespace,pod) group_left(workload,workload_type) mixin_pod_workload{namespace="default", workload_type="deployment"}) by (pod))'
        self.url_recv_packet = self.base_url + '(sum(irate(container_network_receive_packets_total{namespace="default"}[4h]) * on (namespace,pod) group_left(workload,workload_type) mixin_pod_workload{namespace="default", workload_type="deployment"}) by (pod))'
        self.url_trans_packet = self.base_url + '(sum(irate(container_network_transmit_packets_total{namespace="default"}[4h]) * on (namespace,pod) group_left(workload,workload_type) mixin_pod_workload{namespace="default", workload_type="deployment"}) by (pod))'
        self.url_recv_packet_drop = self.base_url + '(sum(irate(container_network_receive_packets_dropped_total{namespace="default"}[4h]) * on (namespace,pod) group_left(workload,workload_type) mixin_pod_workload{namespace="default", workload_type="deployment"}) by (pod))'
        self.url_trans_packet_drop = self.base_url + '(sum(irate(container_network_transmit_packets_dropped_total{namespace="default"}[4h]) * on (namespace,pod) group_left(workload,workload_type) mixin_pod_workload{namespace="default", workload_type="deployment"}) by (pod))'
        self.dataframe_trace_number = prometheus_dataframe_trace_number
        self.dataframe_header = ['timestamp','component','componentNumber','cpu_usage_min','cpu_usage_max','cpu_usage_median','cpu_usage_mean','cpu_usage_std','cpu_usage_var','cpu_perc_request_min','cpu_perc_request_max','cpu_perc_request_median','cpu_perc_request_mean','cpu_perc_request_std','cpu_perc_request_var','cpu_perc_limit_min','cpu_perc_limit_max','cpu_perc_limit_median','cpu_perc_limit_mean','cpu_perc_limit_std','cpu_perc_limit_var','mem_usage_min','mem_usage_max','mem_usage_median','mem_usage_mean','mem_usage_std','mem_usage_var','mem_perc_request_min','mem_perc_request_max','mem_perc_request_median','mem_perc_request_mean','mem_perc_request_std','mem_perc_request_var','mem_perc_limit_min','mem_perc_limit_max','mem_perc_limit_median','mem_perc_limit_mean','mem_perc_limit_std','mem_perc_limit_var','recv_bandwidth_min','recv_bandwidth_max','recv_bandwidth_median','recv_bandwidth_mean','recv_bandwidth_std','recv_bandwidth_var','trans_bandwidth_min','trans_bandwidth_max','trans_bandwidth_median','trans_bandwidth_mean','trans_bandwidth_std','trans_bandwidth_var','recv_packet_min','recv_packet_max','recv_packet_median','recv_packet_mean','recv_packet_std','recv_packet_var','trans_packet_min','trans_packet_max','trans_packet_median','trans_packet_mean','trans_packet_std','trans_packet_var','recv_packet_drop_min','recv_packet_drop_max','recv_packet_drop_median','recv_packet_drop_mean','recv_packet_drop_std','recv_packet_drop_var','trans_packet_drop_min','trans_packet_drop_max','trans_packet_drop_median','trans_packet_drop_mean','trans_packet_drop_std','trans_packet_drop_var']
        self.ressource_dataframe = pd.DataFrame(data=[],columns=self.dataframe_header)
        self.ressource_dataframe_view = None
        self.generate_view = False
        self.services = ['front-dynamic-component']
        self.last_component_number = {}
        self.view_ready = False
        #self.last_component_number = 1
        self.sample_number_before_accepting_scaling = 0
        self.count_sample = 0

    def reset(self):
        self.ressource_dataframe = pd.DataFrame(data=[],columns=self.dataframe_header)
        self.ressource_dataframe_view = None
        self.view_ready = False

    def generateView(self):
        self.generate_view = False
        self.ressource_dataframe_view = self.ressource_dataframe
        self.count_sample = 0
        self.view_ready = True

    def retrieveView(self,empty = False):
        self.view_ready = False
        if empty:
            return pd.DataFrame(data=[],columns=self.dataframe_header) 
        else:
            return self.ressource_dataframe_view

    def unstop(self):
        self.pause = False

    def stop(self):
        self.pause = True

    def run(self):
        print("Prometheus thread : started")
        while True:
            if self.debug:
                print("prometheus.dataframe_trace_number:", self.dataframe_trace_number) 
            while self.pause:
                if self.debug:
                    print("Prometheus thread paused")
                time.sleep(1)
            if self.generate_view and len(self.ressource_dataframe) >= self.dataframe_trace_number and self.count_sample >= self.sample_number_before_accepting_scaling:
                self.generateView()
            while True:
                try:
                    response_cpu_usage = json.loads((http.request('GET',self.url_cpu_usage).data).decode('ascii'))['data']['result']
                except:
                    print('Prometheus thread: I did not have a value for CPU usage')
                    time.sleep(1)
                    continue
                break
            while True:
                try:
                    response_cpu_perc_request = json.loads((http.request('GET',self.url_cpu_perc_request).data).decode('ascii'))['data']['result']
                except:
                    print('Prometheus thread: I did not have a value for cpu perc request')
                    time.sleep(1)
                    continue
                break
            while True:
                try:
                    response_cpu_perc_limit = json.loads((http.request('GET',self.url_cpu_perc_limit).data).decode('ascii'))['data']['result']
                except:
                    print('Prometheus thread: I did not have a value for cpu perc limit')
                    time.sleep(1)
                    continue
                break
            while True:
                try:
                    response_mem_usage = json.loads((http.request('GET',self.url_mem_usage).data).decode('ascii'))['data']['result']
                except:
                    print('Prometheus thread: I did not have a value for MEM usage')
                    time.sleep(1)
                    continue
                break
            while True:
                try:
                    response_mem_perc_request = json.loads((http.request('GET',self.url_mem_perc_request).data).decode('ascii'))['data']['result']
                except:
                    print('Prometheus thread: I did not have a value for mem perc request')
                    time.sleep(1)
                    continue
                break
            while True:
                try:
                    response_mem_perc_limit = json.loads((http.request('GET',self.url_mem_perc_limit).data).decode('ascii'))['data']['result']
                except:
                    print('Prometheus thread: I did not have a value for mem perc limit')
                    time.sleep(1)
                    continue
                break

            while True:
                try:
                    response_recv_bandwidth = json.loads((http.request('GET',self.url_recv_bandwidth).data).decode('ascii'))['data']['result']
                except:
                    print('Prometheus thread: I did not have a value for RECV bandwidth')
                    time.sleep(1)
                    continue
                break
            while True:
                try:
                    response_trans_bandwidth = json.loads((http.request('GET',self.url_trans_bandwidth).data).decode('ascii'))['data']['result']
                except:
                    print('Prometheus thread: I did not have a value for cpu TRANS bandwidth')
                    time.sleep(1)
                    continue
                break
            while True:
                try:
                    response_recv_packet = json.loads((http.request('GET',self.url_recv_packet).data).decode('ascii'))['data']['result']
                except:
                    print('Prometheus thread: I did not have a value for RECV packet')
                    time.sleep(1)
                    continue
                break
            while True:
                try:
                    response_trans_packet = json.loads((http.request('GET',self.url_trans_packet).data).decode('ascii'))['data']['result']
                except:
                    print('Prometheus thread: I did not have a value for TRANS packet')
                    time.sleep(1)
                    continue
                break
            while True:
                try:
                    response_recv_packet_drop = json.loads((http.request('GET',self.url_recv_packet_drop).data).decode('ascii'))['data']['result']
                except:
                    print('Prometheus thread: I did not have a value for RECV packet drop')
                    time.sleep(1)
                    continue
                break
            while True:
                try:
                    response_trans_packet_drop = json.loads((http.request('GET',self.url_trans_packet_drop).data).decode('ascii'))['data']['result']
                except:
                    print('Prometheus thread: I did not have a value for TRANS packet drop')
                    time.sleep(1)
                    continue
                break
            metrics = {}
            for service in self.services:
                metrics[service] = {'timestamp': 0, 'cpu_usage': [], 'cpu_perc_request': [], 'cpu_perc_limit': [], 'mem_usage': [], 'mem_perc_request': [], 'mem_perc_limit': [], 'recv_bandwidth': [], 'trans_bandwidth': [], 'recv_packet': [], 'trans_packet': [], 'recv_packet_drop': [], 'trans_packet_drop': []}
                if service not in self.last_component_number:
                    self.last_component_number[service] = 1
            #cpu_usage = np.array([])
            #cpu_perc_request = np.array([])
            #cpu_perc_limit = np.array([])
            #mem_usage = np.array([])
            #mem_perc_request = np.array([])
            #mem_perc_limit = np.array([])
            #recv_bandwidth = np.array([])
            #trans_bandwidth = np.array([])
            #recv_packet = np.array([])
            #trans_packet = np.array([])
            #recv_packet_drop = np.array([])
            #trans_packet_drop = np.array([])
            for entry in response_cpu_usage:
                for service in self.services:
                    if re.match('^' + service + '.*', entry['metric']['pod']):
                        metrics[service]['timestamp'] = datetime.fromtimestamp(int(str(entry['value'][0])[:10]))
                        metrics[service]['cpu_usage'].append(float(entry['value'][1]))
                        break
            for entry in response_cpu_perc_request:
                for service in self.services:
                    if re.match('^' + service + '.*', entry['metric']['pod']):
                        metrics[service]['cpu_perc_request'].append(float(entry['value'][1]))
                        #print("prom metric:", metrics[service]['cpu_perc_request'])
                        break
            for entry in response_cpu_perc_limit:
                for service in self.services:
                    if re.match('^' + service + '.*', entry['metric']['pod']):
                        metrics[service]['cpu_perc_limit'].append(float(entry['value'][1]))
                        break
            for entry in response_mem_usage:
                for service in self.services:
                    if re.match('^' + service + '.*', entry['metric']['pod']):
                        metrics[service]['mem_usage'].append(float(entry['value'][1]))
                        break
            for entry in response_mem_perc_request:
                for service in self.services:
                    if re.match('^' + service + '.*', entry['metric']['pod']):
                        metrics[service]['mem_perc_request'].append(float(entry['value'][1]))
                        break
            for entry in response_mem_perc_limit:
                for service in self.services:
                    if re.match('^' + service + '.*', entry['metric']['pod']):
                        metrics[service]['mem_perc_limit'].append(float(entry['value'][1]))
                        break
            for entry in response_recv_bandwidth:
                for service in self.services:
                    if re.match('^' + service + '.*', entry['metric']['pod']):
                        metrics[service]['recv_bandwidth'].append(float(entry['value'][1]))
                        break
            for entry in response_trans_bandwidth:
                for service in self.services:
                    if re.match('^' + service + '.*', entry['metric']['pod']):
                        metrics[service]['trans_bandwidth'].append(float(entry['value'][1]))
                        break
            for entry in response_recv_packet:
                for service in self.services:
                    if re.match('^' + service + '.*', entry['metric']['pod']):
                        metrics[service]['recv_packet'].append(float(entry['value'][1]))
                        break
            for entry in response_trans_packet:
                for service in self.services:
                    if re.match('^' + service + '.*', entry['metric']['pod']):
                        metrics[service]['trans_packet'].append(float(entry['value'][1]))
                        break
            for entry in response_recv_packet_drop:
                for service in self.services:
                    if re.match('^' + service + '.*', entry['metric']['pod']):
                        metrics[service]['recv_packet_drop'].append(float(entry['value'][1]))
                        break
            for entry in response_trans_packet_drop:
                for service in self.services:
                    if re.match('^' + service + '.*', entry['metric']['pod']):
                        metrics[service]['trans_packet_drop'].append(float(entry['value'][1]))
                        break
            for service in self.services:
                data_entry = []
                data_entry.append(metrics[service]['timestamp'])
                data_entry.append(service)
                data_entry.append(len(metrics[service]['cpu_usage']))
                self.last_component_number[service] = len(metrics[service]['cpu_usage'])
                #self.last_component_number = len(metrics[service]['cpu_usage'])
                data_entry.append(np.amin(metrics[service]['cpu_usage']))
                data_entry.append(np.amax(metrics[service]['cpu_usage']))
                data_entry.append(np.median(metrics[service]['cpu_usage']))
                data_entry.append(np.mean(metrics[service]['cpu_usage']))
                data_entry.append(np.std(metrics[service]['cpu_usage']))
                data_entry.append(np.var(metrics[service]['cpu_usage']))
                data_entry.append(np.amin(metrics[service]['cpu_perc_request']))
                data_entry.append(np.amax(metrics[service]['cpu_perc_request']))
                data_entry.append(np.median(metrics[service]['cpu_perc_request']))
                data_entry.append(np.mean(metrics[service]['cpu_perc_request']))
                print("prom mean:", np.mean(metrics[service]['cpu_perc_request']))
                data_entry.append(np.std(metrics[service]['cpu_perc_request']))
                data_entry.append(np.var(metrics[service]['cpu_perc_request']))
                data_entry.append(np.amin(metrics[service]['cpu_perc_limit']))
                data_entry.append(np.amax(metrics[service]['cpu_perc_limit']))
                data_entry.append(np.median(metrics[service]['cpu_perc_limit']))
                data_entry.append(np.mean(metrics[service]['cpu_perc_limit']))
                data_entry.append(np.std(metrics[service]['cpu_perc_limit']))
                data_entry.append(np.var(metrics[service]['cpu_perc_limit']))
                data_entry.append(np.amin(metrics[service]['mem_usage']))
                data_entry.append(np.amax(metrics[service]['mem_usage']))
                data_entry.append(np.median(metrics[service]['mem_usage']))
                data_entry.append(np.mean(metrics[service]['mem_usage']))
                data_entry.append(np.std(metrics[service]['mem_usage']))
                data_entry.append(np.var(metrics[service]['mem_usage']))
                data_entry.append(np.amin(metrics[service]['mem_perc_request']))
                data_entry.append(np.amax(metrics[service]['mem_perc_request']))
                data_entry.append(np.median(metrics[service]['mem_perc_request']))
                data_entry.append(np.mean(metrics[service]['mem_perc_request']))
                data_entry.append(np.std(metrics[service]['mem_perc_request']))
                data_entry.append(np.var(metrics[service]['mem_perc_request']))
                data_entry.append(np.amin(metrics[service]['mem_perc_limit']))
                data_entry.append(np.amax(metrics[service]['mem_perc_limit']))
                data_entry.append(np.median(metrics[service]['mem_perc_limit']))
                data_entry.append(np.mean(metrics[service]['mem_perc_limit']))
                data_entry.append(np.std(metrics[service]['mem_perc_limit']))
                data_entry.append(np.var(metrics[service]['mem_perc_limit']))
                data_entry.append(np.amin(metrics[service]['recv_bandwidth']))
                data_entry.append(np.amax(metrics[service]['recv_bandwidth']))
                data_entry.append(np.median(metrics[service]['recv_bandwidth']))
                data_entry.append(np.mean(metrics[service]['recv_bandwidth']))
                data_entry.append(np.std(metrics[service]['recv_bandwidth']))
                data_entry.append(np.var(metrics[service]['recv_bandwidth']))
                data_entry.append(np.amin(metrics[service]['trans_bandwidth']))
                data_entry.append(np.amax(metrics[service]['trans_bandwidth']))
                data_entry.append(np.median(metrics[service]['trans_bandwidth']))
                data_entry.append(np.mean(metrics[service]['trans_bandwidth']))
                data_entry.append(np.std(metrics[service]['trans_bandwidth']))
                data_entry.append(np.var(metrics[service]['trans_bandwidth']))
                data_entry.append(np.amin(metrics[service]['recv_packet']))
                data_entry.append(np.amax(metrics[service]['recv_packet']))
                data_entry.append(np.median(metrics[service]['recv_packet']))
                data_entry.append(np.mean(metrics[service]['recv_packet']))
                data_entry.append(np.std(metrics[service]['recv_packet']))
                data_entry.append(np.var(metrics[service]['recv_packet']))
                data_entry.append(np.amin(metrics[service]['trans_packet']))
                data_entry.append(np.amax(metrics[service]['trans_packet']))
                data_entry.append(np.median(metrics[service]['trans_packet']))
                data_entry.append(np.mean(metrics[service]['trans_packet']))
                data_entry.append(np.std(metrics[service]['trans_packet']))
                data_entry.append(np.var(metrics[service]['trans_packet']))
                data_entry.append(np.amin(metrics[service]['recv_packet_drop']))
                data_entry.append(np.amax(metrics[service]['recv_packet_drop']))
                data_entry.append(np.median(metrics[service]['recv_packet_drop']))
                data_entry.append(np.mean(metrics[service]['recv_packet_drop']))
                data_entry.append(np.std(metrics[service]['recv_packet_drop']))
                data_entry.append(np.var(metrics[service]['recv_packet_drop']))
                data_entry.append(np.amin(metrics[service]['trans_packet_drop']))
                data_entry.append(np.amax(metrics[service]['trans_packet_drop']))
                data_entry.append(np.median(metrics[service]['trans_packet_drop']))
                data_entry.append(np.mean(metrics[service]['trans_packet_drop']))
                data_entry.append(np.std(metrics[service]['trans_packet_drop']))
                data_entry.append(np.var(metrics[service]['trans_packet_drop']))
                if self.debug:
                    print("data entry:", data_entry)
                df = pd.DataFrame(data=[data_entry],columns=self.dataframe_header)
                self.ressource_dataframe = self.ressource_dataframe.append(df, ignore_index=False)
            if self.count_sample < self.sample_number_before_accepting_scaling:
                self.count_sample += 1
            if len(self.ressource_dataframe) > self.dataframe_trace_number:
                self.ressource_dataframe = self.ressource_dataframe.iloc[len(self.ressource_dataframe) - self.dataframe_trace_number:]
            if self.debug:
                print("last component number:", self.last_component_number)
                print("Prometheus thread wait ", self.waitBetweenCall, " seconds for next mesures")
            time.sleep(self.waitBetweenCall)

consumer_locust = ConsumerLocust(debug=locust_debug)
consumer_zipkin = ConsumerZipkin(dataframe_trace_number=zipkin_dataframe_trace_number,debug=zipkin_debug)
consumer_metricserver = ConsumerMetricServer(dataframe_trace_number=metricserver_dataframe_trace_number,metricserver_WaitBetweenCall=metricserver_WaitBetweenCall, debug=metricserver_debug)
consumer_prometheus = ConsumerPrometheus(dataframe_trace_number=prometheus_dataframe_trace_number,prometheus_WaitBetweenCall=prometheus_WaitBetweenCall,debug=prometheus_debug)
orchestrator = Orchestrator(consumer_locust=consumer_locust,consumer_zipkin=consumer_zipkin,consumer_prometheus=consumer_prometheus,consumer_metricserver=consumer_metricserver,debug=orchestrator_debug)
consumer_locust.daemon = True
consumer_locust.start()
consumer_zipkin.daemon = True
consumer_zipkin.start()
consumer_metricserver.daemon = True
consumer_metricserver.start()
consumer_prometheus.daemon = True
consumer_prometheus.start()
orchestrator.daemon = True
orchestrator.start()

n = sdnotify.SystemdNotifier()
n.notify("READY=1")
try:
    while True:
        n.notify("WATCHDOG=1")
        time.sleep(10)
except KeyboardInterrupt:
    print('Exiting...')

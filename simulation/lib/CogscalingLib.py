# Software Name : HSLinUCB
# SPDX-FileCopyrightText: Copyright (c) 2021 Orange
# SPDX-License-Identifier: GPL-2.0
#
# This software is distributed under the GNU General Public License v2.0 license
#
# Author: David DELANDE <david.delande@orange.com> et al.
import time
import sys
import os
import h5py
import sdnotify
from threading import Thread
from kafka import KafkaProducer
from kafka import KafkaConsumer
from json import loads
from json import dumps
import pandas as pd
import numpy as np
import json
import urllib3
from collections import OrderedDict
from datetime import datetime
http = urllib3.PoolManager()

from kubernetes import client, config
from kubernetes.client.models.v1_scale import V1Scale

pd.set_option("display.max_rows", None, "display.max_columns", None)

class OrchestratorActionResult(Thread):
    def __init__(self, debug=False):
        Thread.__init__(self)
        self.debug=debug
        replay = True
        if replay == False:
            self.OrchestratorActionResult_consumer = KafkaConsumer('action_result',bootstrap_servers=['kafka.service.pf1:9092'],value_deserializer=lambda x: loads(x.decode('utf-8')))
        else:
            self.OrchestratorActionResult_consumer = None
        self.resultTable = {}

    def AddTransaction(self,message):
        if 'reason' in message:
            self.resultTable[message['transactionId']] = {"order": message['order'], "result": message['result'], "reason": message['reason']}
        else:
            self.resultTable[message['transactionId']] = {"order": message['order'], "result": message['result']}

    def CheckTransaction(self,transactionId):
        Action_Result = False
        Error_Reason = ''
        while True:
            if transactionId in self.resultTable:
                if self.debug:
                    print("checktransaction:", transactionId, " found in table")
                if self.resultTable[transactionId]['result'] == 'OK':
                    if self.debug:
                        print("Action OK")
                    Action_Result = True
                    if 'reason' in self.resultTable[transactionId]:
                        Error_Reason = self.resultTable[transactionId]['reason']
                else:
                    if self.debug:
                        print("Action KO")
                    Action_Result = False
                    Error_Reason = self.resultTable[transactionId]['reason']
                del self.resultTable[transactionId]
                break
            else:
                if self.debug:
                    print("transaction:", transactionId, " not found in table")
            time.sleep(1)
        return Action_Result, Error_Reason

    def run(self):
        print("OrchestratorActionResult thread : started")
        print("Orchestrator: wait 2 seconds for kafka initialization...")
        time.sleep(2)
        for message in self.OrchestratorActionResult_consumer:
            message = message.value
            if self.debug:
                print(message)
            self.AddTransaction(message)

class StateResult(Thread):
    def __init__(self, debug=False):
        Thread.__init__(self)
        self.debug=debug
        replay = True
        if replay == False:
            self.StateResult_consumer = KafkaConsumer('state',bootstrap_servers=['kafka.service.pf1:9092'],value_deserializer=lambda x: loads(x.decode('utf-8')))
        else:
            self.StateResult_consumer = None
        self.stateTable = {}

    def AddState(self,message):
            self.stateTable[message['transactionId']] = {"zipkin": message['zipkin'], "prometheus": message['prometheus'], "locust": message['locust']}
            if self.debug:
                print("stateTable after update:", self.stateTable)

    def RetrieveState(self,transactionId,zipkin_format='pandas',prometheus_format='pandas', zipkinOnly = False, prometheusOnly = False):
        zipkin = {}
        prometheus = {}
        locust = {}
        while True:
            if self.debug:
                print("state table in Retrieve state:", self.stateTable)
            if transactionId in self.stateTable:
                if self.debug:
                    print("state:", transactionId, " found in table")
                if zipkin_format == 'pandas' and not prometheusOnly:
                    zipkin = pd.read_json(self.stateTable[transactionId]['zipkin'], orient='split')
                if prometheus_format == 'pandas' and not zipkinOnly:
                    prometheus = pd.read_json(self.stateTable[transactionId]['prometheus'], orient='split')
                if zipkin_format == 'numpy' and not prometheusOnly:
                    zipkin = pd.read_json(self.stateTable[transactionId]['zipkin'], orient='split').to_numpy()
                if prometheus_format == 'numpy' and not zipkinOnly:
                    prometheus = pd.read_json(self.stateTable[transactionId]['prometheus'], orient='split').to_numpy()
                if zipkin_format == 'json' and not prometheusOnly:
                    zipkin = self.stateTable[transactionId]['zipkin']
                if prometheus_format == 'json' and not zipkinOnly:
                    prometheus = self.stateTable[transactionId]['prometheus']
                if zipkin_format != 'pandas' and zipkin_format != 'numpy' and zipkin_format != 'json' and not prometheusOnly:
                    print("zipkin_format is unknown")
                if prometheus_format != 'pandas' and prometheus_format != 'numpy' and prometheus_format != 'json' and not zipkinOnly:
                    print("prometheus_format is unknown")
                if prometheusOnly:
                    zipkin = []
                if zipkinOnly:
                    prometheus = []
                locust = self.stateTable[transactionId]['locust']
                del self.stateTable[transactionId]
                break
            else:
                if self.debug:
                    print("state:", transactionId, " not found in table")
            time.sleep(1)
        if self.debug:
            print("zipkin state ,prometheus state and locust state returned from RetrieveState:", zipkin, prometheus, locust)
        return zipkin, prometheus, locust

    def run(self):
        print("StateResult thread : started")
        print("State result: wait 2 seconds for kafka initialization...")
        time.sleep(2)
        for message in self.StateResult_consumer:
            message = message.value
            if self.debug:
                print(message)
            self.AddState(message)

class Orchestrator():
    def __init__(self,debug=False, sessionFile=None):
        self.debug=debug
        replay = True
        if replay == False:
            self.kafka_producer = KafkaProducer(bootstrap_servers = ['kafka.service.pf1:9092'],acks='all',value_serializer=lambda x: dumps(x).encode('utf-8'))
        else:
            self.kafka_producter = None
        self.orchestratorActionResult = OrchestratorActionResult(debug=self.debug)
        self.orchestratorActionResult.daemon = True
        self.data_index = np.zeros((101, 11),dtype=int)
        self.sessionFile = sessionFile
        self.orchestratorActionResult.start()
        self.stateResult = StateResult(debug=self.debug)
        self.stateResult.daemon = True
        self.stateResult.start()

    def getAgregatedState(self, components=[],zipkinOnly = False, prometheusOnly = False, record = False, replay = False, load = None, level = None,useMetricServer = False, externalScaling = False):
        #components = [{'prometheus': 'ROOT', 'zipkin': 'istio-ingressgateway'},{'prometheus': 'front-dynamic-component','zipkin': 'front-dynamic-component-service.default.svc.cluster.local:80/*'},{'prometheus': 'back-dynamic-component', 'zipkin': 'back-dynamic-component-service.default.svc.cluster.local:80/*'}]
        if zipkinOnly:
            dataframe_header = ['timestamp','component','lastcomponentNumber','duration','req_perc_sec','target_user_count','global_user_count','worker_count','last_request_timestamp','num_requests','num_none_requests','num_failure','total_response_time','max_response_time','min_response_time','total_content_length','response_times','num_reqs_per_sec','num_fail_per_sec']
        else:
            dataframe_header = ['timestamp','component','lastcomponentNumber','duration','req_perc_sec','meancomponentNumber','cpu_usage_min','cpu_usage_max','cpu_usage_median','cpu_usage_mean','cpu_usage_std','cpu_usage_var','cpu_perc_request_min','cpu_perc_request_max','cpu_perc_request_median','cpu_perc_request_mean','cpu_perc_request_std','cpu_perc_request_var','cpu_perc_limit_min','cpu_perc_limit_max','cpu_perc_limit_median','cpu_perc_limit_mean','cpu_perc_limit_std','cpu_perc_limit_var','mem_usage_min','mem_usage_max','mem_usage_median','mem_usage_mean','mem_usage_std','mem_usage_var','mem_perc_request_min','mem_perc_request_max','mem_perc_request_median','mem_perc_request_mean','mem_perc_request_std','mem_perc_request_var','mem_perc_limit_min','mem_perc_limit_max','mem_perc_limit_median','mem_perc_limit_mean','mem_perc_limit_std','mem_perc_limit_var','recv_bandwidth_min','recv_bandwidth_max','recv_bandwidth_median','recv_bandwidth_mean','recv_bandwidth_std','recv_bandwidth_var','trans_bandwidth_min','trans_bandwidth_max','trans_bandwidth_median','trans_bandwidth_mean','trans_bandwidth_std','trans_bandwidth_var','recv_packet_min','recv_packet_max','recv_packet_median','recv_packet_mean','recv_packet_std','recv_packet_var','trans_packet_min','trans_packet_max','trans_packet_median','trans_packet_mean','trans_packet_std','trans_packet_var','recv_packet_drop_min','recv_packet_drop_max','recv_packet_drop_median','recv_packet_drop_mean','recv_packet_drop_std','recv_packet_drop_var','trans_packet_drop_min','trans_packet_drop_max','trans_packet_drop_median','trans_packet_drop_mean','trans_packet_drop_std','trans_packet_drop_var','target_user_count','global_user_count','worker_count','last_request_timestamp','num_requests','num_none_requests','num_failure','total_response_time','max_response_time','min_response_time','total_content_length','response_times','num_reqs_per_sec','num_fail_per_sec']


        state_dataframe = pd.DataFrame(data=[],columns=dataframe_header)
        if record and replay:
            print("record and replay can not be activated together")
        elif (record or replay) and self.sessionFile == None:
            print("sessionFile must be specified when record or replay is activated")
        elif replay and (load == None or level == None):
            print("load and level parameter must be specified if replay is activated")
        elif record and (zipkinOnly or prometheusOnly):
            print("Record can not be activated when zipkinOnly or prometheusOnly options are activated")
        elif replay and (zipkinOnly or prometheusOnly):
            print("Replay can not be activated when zipkinOnly or prometheusOnly options are activated")
        elif replay and load != None and level != None and zipkinOnly == False and prometheusOnly == False:
            #print("replay activated")
            index = None
            with h5py.File(self.sessionFile, "r") as f:
                for component in components:
                    try:
                        load_grp = f.get(str(load))
                        component_grp = load_grp.get(str(component['prometheus']))
                        level_grp = component_grp.get(str(level))
                        d = level_grp.get('measure')
                        #ordered way
                        index = self.data_index[load,level]
                        if index == len(d):
                            self.data_index[load,level] = 0
                            index = 0
                        #End ordered way
                        #if index == None:
                        #    index = np.random.choice(len(d), 1)[0]
                        #print("load:", load)
                        #print("level:", level)
                        #print("index to use:", index)
                        try:
                            data = d[index]
                            data = np.asarray(data)
                            data[0] = np.datetime64(data[0])
                            df = pd.DataFrame(data=[data],columns=dataframe_header)
                            state_dataframe = state_dataframe.append(df, ignore_index=False)
                        except:
                            print("index : ", index, " not found in dataset:", component)
                    except:
                        print("dataset : " , component, " not found")
                    self.data_index[load,level] += 1
            f.close()  
            #print("dataframe:", state_dataframe)

        else:
            if components != []:
                zipkin_state, prometheus_state, locust_state, status, message = self.getState(zipkin_format='pandas',prometheus_format='pandas',zipkinOnly = zipkinOnly, prometheusOnly = prometheusOnly, useMetricServer = useMetricServer, externalScaling = externalScaling)
                zipkin = {}
                prometheus = {}
                for component in components:
                    if self.debug:
                        print("component:", component)
                    prometheus[component['prometheus']] = {'timestamp': 0, 'ressources': [], 'lastcomponentNumber': 0}
                    zipkin[component['prometheus']] = { 'duration': 0, 'req_per_sec': 0}
                    if component['zipkin'] == 'istio-ingressgateway':
                        if not prometheusOnly:
                            zipkin[component['prometheus']]["duration"] = np.percentile(zipkin_state[['duration']].loc[(zipkin_state['parentId'] == '-')].to_numpy().ravel(), 95)
                            #zipkin[component['prometheus']]["duration"] = zipkin_state[['duration']].loc[(zipkin_state['parentId'] == '-')].mean(numeric_only=True).to_numpy()   
                            diff_date = zipkin_state[['timestamp']].loc[(zipkin_state['parentId'] == '-')].max() - zipkin_state[['timestamp']].loc[(zipkin_state['parentId'] == '-')].min()
                            nbrq = len(zipkin_state[['timestamp']].loc[(zipkin_state['parentId'] == '-')])
                            if diff_date[0].total_seconds() != 0:
                                zipkin[component['prometheus']]['req_per_sec'] = nbrq / diff_date[0].total_seconds()
                            else:
                                print("All datas are aligned on 1 second. Increase the buffer length")
                                zipkin[component['prometheus']]['req_per_sec'] = nbrq
                                print("zipkin_state[['timestamp']]:", zipkin_state[['timestamp']])
                        if not zipkinOnly:
                            prometheus[component['prometheus']]["ressources"] = np.zeros(73)
                    else:
                        if not prometheusOnly:
                            zipkin[component['prometheus']]["duration"] = np.percentile(zipkin_state[['duration']].loc[(zipkin_state['kind'] == 'SERVER') & (zipkin_state['name'] == component['zipkin'])].to_numpy().ravel(), 95)
                            diff_date = zipkin_state[['timestamp']].loc[(zipkin_state['kind'] == 'SERVER') & (zipkin_state['name'] == component['zipkin'])].max() - zipkin_state[['timestamp']].loc[(zipkin_state['kind'] == 'SERVER') & (zipkin_state['name'] == component['zipkin'])].min()
                            nbrq = len(zipkin_state[['timestamp']].loc[(zipkin_state['kind'] == 'SERVER') & (zipkin_state['name'] == component['zipkin'])])
                            if diff_date[0].total_seconds() != 0:
                                zipkin[component['prometheus']]['req_per_sec'] = nbrq / diff_date[0].total_seconds()
                            else:
                                print("All datas are aligned on 1 second. Increase the buffer length")
                                zipkin[component['prometheus']]['req_per_sec'] = nbrq
                                print("zipkin_state[['timestamp']]:", zipkin_state[['timestamp']].loc[(zipkin_state['kind'] == 'SERVER') & (zipkin_state['name'] == component['zipkin'])])
                        if not zipkinOnly:
                            prometheus[component['prometheus']]["ressources"] = prometheus_state.loc[prometheus_state['component'] == component['prometheus']].mean(numeric_only=True).to_numpy()
                            prometheus[component['prometheus']]["timestamp"] = prometheus_state['timestamp'].loc[prometheus_state['component'] == component['prometheus']].iloc[len(prometheus_state['timestamp'].loc[prometheus_state['component'] == component['prometheus']]) - 1].to_numpy()
                            prometheus[component['prometheus']]["lastcomponentNumber"] = lastcomponent_number = prometheus_state['componentNumber'].loc[prometheus_state['component'] == component['prometheus']].iloc[len(prometheus_state['componentNumber'].loc[prometheus_state['component'] == component['prometheus']]) - 1]
                    data = []   
                    data.append(prometheus[component['prometheus']]['timestamp'])
                    #data.append("back-dynamic-component")
                    data.append(str(component['prometheus']))
                    data.append(prometheus[component['prometheus']]['lastcomponentNumber'])
                    data.append(zipkin[component['prometheus']]['duration'])
                    data.append(zipkin[component['prometheus']]['req_per_sec'])
                    data.extend(prometheus[component['prometheus']]['ressources'])
                    data.append(locust_state['target_user_count'])
                    data.append(locust_state['global_user_count']) 
                    data.append(locust_state['worker_count'])
                    data.append(locust_state['last_request_timestamp'])
                    data.append(locust_state['num_requests'])
                    data.append(locust_state['num_none_requests'])
                    data.append(locust_state['num_failure'])
                    data.append(locust_state['total_response_time'])
                    data.append(locust_state['max_response_time'])
                    data.append(locust_state['min_response_time'])
                    data.append(locust_state['total_content_length'])
                    data.append(locust_state['response_times'])
                    data.append(locust_state['num_reqs_per_sec'])
                    data.append(locust_state['num_fail_per_sec'])
                    data = np.asarray(data)
                    if record and self.sessionFile != None and zipkinOnly == False and prometheusOnly == False:
                        with h5py.File(self.sessionFile, "a") as f:
                            load_grp = f.require_group(str(locust_state['global_user_count'])) 
                            #component_grp = load_grp.require_group('back-dynamic-component')
                            component_grp = load_grp.require_group(str(component['prometheus'])) 
                            level_grp = component_grp.require_group(str(prometheus[component['prometheus']]['lastcomponentNumber']))
                            if 'measure' in level_grp:
                                d = level_grp.get('measure')
                                new_shape = ( d.shape[0]+1,d.shape[1] )
                                d.resize( new_shape )
                                d[new_shape[0] -1:] = [data]
                                d.flush()
                            else:
                                print("dataset do not exist. Creating it with data entry") 
                                dt = h5py.string_dtype(encoding='utf-8')
                                d = level_grp.create_dataset("measure", maxshape=(None,None), data=[data], dtype=dt)
                                d.flush()
                        f.close()
                    df = pd.DataFrame(data=[data],columns=dataframe_header)
                    state_dataframe = state_dataframe.append(df, ignore_index=False)
        return state_dataframe



    def getState(self,zipkin_format='pandas',prometheus_format='pandas', zipkinOnly = False, prometheusOnly = False, record = False, replay = False,useMetricServer = False,externalScaling = False):
        zipkin = None
        prometheus = None
        timestamp = time.time()
        if record and replay:
            print("record and replay can not be activated together")
        else:
            if zipkinOnly:
                self.kafka_producer.send('action', value={"transactionId": timestamp, "order": "getState", "zipkinOnly": True, "externalScaling": externalScaling})
            elif prometheusOnly:
                self.kafka_producer.send('action', value={"transactionId": timestamp, "order": "getState", "prometheusOnly": True, "externalScaling": externalScaling})
            else:
                self.kafka_producer.send('action', value={"transactionId": timestamp, "order": "getState", "useMetricServer": useMetricServer, "externalScaling": externalScaling})
            self.kafka_producer.flush()
            status, error = self.orchestratorActionResult.CheckTransaction(timestamp)
            if status:
                zipkin, prometheus, locust = self.stateResult.RetrieveState(timestamp,zipkin_format=zipkin_format,prometheus_format=prometheus_format)
                if self.debug:
                    print("state retrieve successfully")
                if prometheus_format == 'numpy' and zipkin_format != 'numpy' and not zipkinOnly and not prometheusOnly:
                    message="state retrieve successfully. Prometheus format: ['timestamp','component','componentNumber','cpu_usage_min','cpu_usage_max','cpu_usage_median','cpu_usage_mean','cpu_usage_std','cpu_usage_var','cpu_perc_request_min','cpu_perc_request_max','cpu_perc_request_median','cpu_perc_request_mean','cpu_perc_request_std','cpu_perc_request_var','cpu_perc_limit_min','cpu_perc_limit_max','cpu_perc_limit_median','cpu_perc_limit_mean','cpu_perc_limit_std','cpu_perc_limit_var','mem_usage_min','mem_usage_max','mem_usage_median','mem_usage_mean','mem_usage_std','mem_usage_var','mem_perc_request_min','mem_perc_request_max','mem_perc_request_median','mem_perc_request_mean','mem_perc_request_std','mem_perc_request_var','mem_perc_limit_min','mem_perc_limit_max','mem_perc_limit_median','mem_perc_limit_mean','mem_perc_limit_std','mem_perc_limit_var','recv_bandwidth_min','recv_bandwidth_max','recv_bandwidth_median','recv_bandwidth_mean','recv_bandwidth_std','recv_bandwidth_var','trans_bandwidth_min','trans_bandwidth_max','trans_bandwidth_median','trans_bandwidth_mean','trans_bandwidth_std','trans_bandwidth_var','recv_packet_min','recv_packet_max','recv_packet_median','recv_packet_mean','recv_packet_std','recv_packet_var','trans_packet_min','trans_packet_max','trans_packet_median','trans_packet_mean','trans_packet_std','trans_packet_var','recv_packet_drop_min','recv_packet_drop_max','recv_packet_drop_median','recv_packet_drop_mean','recv_packet_drop_std','recv_packet_drop_var','trans_packet_drop_min','trans_packet_drop_max','trans_packet_drop_median','trans_packet_drop_mean','trans_packet_drop_std','trans_packet_drop_var']"
                if zipkin_format == 'numpy' and prometheus_format != 'numpy' and not zipkinOnly and not prometheusOnly:
                    message="state retrieve successfully. Zipkin format: ['traceId','parentId','id','kind','name','timestamp','duration','serviceName','ipv4','component','downstream_cluster','http_method','http_protocol','http_status','http_url','node_id','peer_address','request_size','response_flags','response_size','upstream_cluster','user_agent']"
                if zipkin_format == 'numpy' and prometheus_format == 'numpy' and not prometheusOnly:
                    message="state retrieve successfully. Zipkin format: ['traceId','parentId','id','kind','name','timestamp','duration','serviceName','ipv4','component','downstream_cluster','http_method','http_protocol','http_status','http_url','node_id','peer_address','request_size','response_flags','response_size','upstream_cluster','user_agent'], prometheus format: ['timestamp','component','componentNumber','cpu_usage_min','cpu_usage_max','cpu_usage_median','cpu_usage_mean','cpu_usage_std','cpu_usage_var','cpu_perc_request_min','cpu_perc_request_max','cpu_perc_request_median','cpu_perc_request_mean','cpu_perc_request_std','cpu_perc_request_var','cpu_perc_limit_min','cpu_perc_limit_max','cpu_perc_limit_median','cpu_perc_limit_mean','cpu_perc_limit_std','cpu_perc_limit_var','mem_usage_min','mem_usage_max','mem_usage_median','mem_usage_mean','mem_usage_std','mem_usage_var','mem_perc_request_min','mem_perc_request_max','mem_perc_request_median','mem_perc_request_mean','mem_perc_request_std','mem_perc_request_var','mem_perc_limit_min','mem_perc_limit_max','mem_perc_limit_median','mem_perc_limit_mean','mem_perc_limit_std','mem_perc_limit_var','recv_bandwidth_min','recv_bandwidth_max','recv_bandwidth_median','recv_bandwidth_mean','recv_bandwidth_std','recv_bandwidth_var','trans_bandwidth_min','trans_bandwidth_max','trans_bandwidth_median','trans_bandwidth_mean','trans_bandwidth_std','trans_bandwidth_var','recv_packet_min','recv_packet_max','recv_packet_median','recv_packet_mean','recv_packet_std','recv_packet_var','trans_packet_min','trans_packet_max','trans_packet_median','trans_packet_mean','trans_packet_std','trans_packet_var','recv_packet_drop_min','recv_packet_drop_max','recv_packet_drop_median','recv_packet_drop_mean','recv_packet_drop_std','recv_packet_drop_var','trans_packet_drop_min','trans_packet_drop_max','trans_packet_drop_median','trans_packet_drop_mean','trans_packet_drop_std','trans_packet_drop_var']"

                if zipkin_format != 'numpy' and prometheus_format != 'numpy':
                    message="state retrieve successfully"
            else:
                if self.debug:
                    print("Error in getting state , error reason: ", error)
                message="Error in getting state , error reason: " + error
            if self.debug:
                print("zipkin and prometheus state returned from getState:", zipkin, prometheus)
        return zipkin, prometheus, locust, status, message

    def setLocustUser(self,user=1,spawn_rate=1):
        timestamp = time.time()
        self.kafka_producer.send('action', value={"transactionId": timestamp, "order": "LocustMgmt", "payload": { "order": "set_user_level", "level": user , "spawn_rate": spawn_rate}})
        self.kafka_producer.flush()
        status, error = self.orchestratorActionResult.CheckTransaction(timestamp)
        if status:
            if self.debug:
                print("locust user set to: ", user, " with spawn_rate: ", spawn_rate)
            message="locust user set to: " + str(user) + " with spawn_rate: " + str(spawn_rate)
        else:
            if self.debug:
                print("Error in setting locust user to: ", user, " with spawn_rate: ", spawn_rate, " error reason: ", error)
            message="Error in setting locust user to: " + str(user) + " with spawn_rate: " + str(spawn_rate) + " error reason: " + error
        return status, message

    def incrementalLocustUser(self,step=1,spawn_rate=1):
        timestamp = time.time()
        self.kafka_producer.send('action', value={"transactionId": timestamp, "order": "LocustMgmt", "payload": { "order": "step_user_level", "level": step , "spawn_rate": spawn_rate}})
        self.kafka_producer.flush()
        status, error = self.orchestratorActionResult.CheckTransaction(timestamp)
        if status:
            if self.debug:
                print("incremental locust user with step: ", step, " with spawn_rate: ", spawn_rate)
            message="incremental locust user with step: " + str(step) + " with spawn_rate: " + str(spawn_rate)
        else:
            if self.debug:
                print("Error in incremental locust user with step: ", step, " with spawn_rate: ", spawn_rate, " error reason: ", error)
            message="Error in incremental locust user with step: " + str(step) + " with spawn_rate: " + str(spawn_rate) + " error reason: " + error 
        return status, message

    def resetLocustStats(self):
        timestamp = time.time()
        self.kafka_producer.send('action', value={"transactionId": timestamp, "order": "LocustMgmt", "payload": { "order": "reset" }})
        self.kafka_producer.flush()
        status, error = self.orchestratorActionResult.CheckTransaction(timestamp)
        if status:
            if self.debug:
                print("reset locust stats done")
            message="reset locust stats done"
        else:
            if self.debug:
                print("Error in resetting locust stats, error reason: ", error)
            message="Error in resetting locust stats, error reason: " + error
        return status, message

    def stopLocustInjection(self):
        timestamp = time.time()
        self.kafka_producer.send('action', value={"transactionId": timestamp, "order": "LocustMgmt", "payload": { "order": "stop" }})
        self.kafka_producer.flush()
        status, error = self.orchestratorActionResult.CheckTransaction(timestamp)
        if status:
            if self.debug:
                print("stop locust injection done")
            message="stop locust injection done"
        else:
            if self.debug:
                print("Error in stopping locust injection, error reason: ", error)
            message="Error in stopping locust injection, error reason: " + error
        return status, message

    def changePrometheusTraceNumber(self,trace_number=30):
        timestamp = time.time()
        self.kafka_producer.send('action', value={ "transactionId": timestamp, "order": "ChangeConfig", "component": "prometheus", "trace_number": trace_number})
        self.kafka_producer.flush()
        status, error = self.orchestratorActionResult.CheckTransaction(timestamp)
        if status:
            if self.debug:
                print("prometheus trace number changed to: ", trace_number)
            message="prometheus trace number changed to: " + str(trace_number)
        else:
            if self.debug:
                print("Error in changing prometheus trace number to: ", trace_number, ", error reason: ", error)
            message="Error in changing prometheus trace number to: " + str(trace_number) + ", error reason: " + error
        return status, message

    def changeZipkinTraceNumber(self,trace_number=30):
        timestamp = time.time()
        self.kafka_producer.send('action', value={ "transactionId": timestamp, "order": "ChangeConfig", "component": "zipkin", "trace_number": trace_number})
        self.kafka_producer.flush()
        status, error = self.orchestratorActionResult.CheckTransaction(timestamp)
        if status:
            if self.debug:
                print("zipkin trace number changed to: ", trace_number)
            message="zipkin trace number changed to: " + str(trace_number)
        else:
            if self.debug:
                print("Error in changing zipkin trace number to: ", trace_number, ", error reason: ", error)
            message="Error in changing zipkin trace number to: " + str(trace_number) + ", error reason: " + error
        return status, message

    def setKubernetesDeploymentScale(self,deployment="front-dynamic-component",number=1,waitKubernetes=True,waitPrometheus=True, useMetricServer = False):
        timestamp = time.time()
        self.kafka_producer.send('action', value={ "transactionId": timestamp, "order": "scaleSUT", "level": number, "deployment": deployment, "mode": "fixed", "waitKubernetes": waitKubernetes, "waitPrometheus": waitPrometheus, "useMetricServer": useMetricServer})
        self.kafka_producer.flush()
        status, error = self.orchestratorActionResult.CheckTransaction(timestamp)
        if status:
            if self.debug:
                print("Deployment: ", deployment, " scaled to: ", number , " with waitKubernetes:", waitKubernetes, " and waitPrometheus:", waitPrometheus)
            message="Deployment: " + deployment + " scaled to: " + str(number) + " with waitKubernetes:" + str(waitKubernetes) + " and waitPrometheus:" + str(waitPrometheus)
        else:
            if self.debug:
                print("Error in scaling deployment: ", deployment, " to: ", number, " with waitKubernetes:", waitKubernetes, " and waitPrometheus:", waitPrometheus, ", error reason: ", error)
            message="Error in scaling deployment: " + deployment + " to: " + str(number) + " with waitKubernetes:" + str(waitKubernetes) + " and waitPrometheus:" + str(waitPrometheus) + ", error reason: " + error
        return status, message

    def incrementalKubernetesDeploymentScale(self,deployment="front-dynamic-component",step=1,waitKubernetes=True,waitPrometheus=True,useMetricServer = False):
        timestamp = time.time()
        self.kafka_producer.send('action', value={ "transactionId": timestamp, "order": "scaleSUT", "level": step, "deployment": deployment, "mode": "incremental", "waitKubernetes": waitKubernetes, "waitPrometheus": waitPrometheus, "useMetricServer": useMetricServer})
        self.kafka_producer.flush()
        status, error = self.orchestratorActionResult.CheckTransaction(timestamp)
        if status:
            if self.debug:
                print("Deployment: ", deployment, " scaled incrementaly with step: ", step, " with waitKubernetes:", waitKubernetes, " and waitPrometheus:", waitPrometheus)
            message="Deployment: " + deployment + " scaled incrementaly with step: " + str(step) + " with waitKubernetes:" + str(waitKubernetes) + " and waitPrometheus:" + str(waitPrometheus)
        else:
            if self.debug:
                print("Error in incremental scaling deployment: ", deployment, " with step: ", step, " with waitKubernetes:", waitKubernetes, " and waitPrometheus:", waitPrometheus," error reason: ", error)
            message="Error in incremental scaling deployment: " + deployment + " with step: " + str(step) + " with waitKubernetes:" + str(waitKubernetes) + " and waitPrometheus:" + str(waitPrometheus) + " error reason: " + error
        return status, message

    def stopZipkinThread(self):
        timestamp = time.time()
        self.kafka_producer.send('action', value={ "transactionId": timestamp, "order": "stopZipkin"})
        self.kafka_producer.flush()
        status, error = self.orchestratorActionResult.CheckTransaction(timestamp)
        if status:
            if self.debug:
                print("zipkin thread stopped")
            message="zipkin thread stopped"
        else:
            if self.debug:
                print("Error in stopping zipkin thread, error reason: ", error)
            message="Error in stopping zipkin thread, error reason: " + error
        return status, message

    def startZipkinThread(self):
        timestamp = time.time()
        self.kafka_producer.send('action', value={ "transactionId": timestamp, "order": "startZipkin"})
        self.kafka_producer.flush()
        status, error = self.orchestratorActionResult.CheckTransaction(timestamp)
        if status:
            if self.debug:
                print("zipkin thread started")
            message="zipkin thread started"
        else:
            if self.debug:
                print("Error in starting zipkin thread, error reason: ", error)
            message="Error in starting zipkin thread, error reason: " + error
        return status, message

    def stopPrometheusThread(self):
        timestamp = time.time()
        self.kafka_producer.send('action', value={ "transactionId": timestamp, "order": "stopPrometheus"})
        self.kafka_producer.flush()
        status, error = self.orchestratorActionResult.CheckTransaction(timestamp)
        if status:
            if self.debug:
                print("prometheus thread stopped")
            message="prometheus thread stopped"
        else:
            if self.debug:
                print("Error in stopping prometheus thread, error reason: ", error)
            message="Error in stopping prometheus thread, error reason: " + error
        return status, message

    def startPrometheusThread(self):
        timestamp = time.time()
        self.kafka_producer.send('action', value={ "transactionId": timestamp, "order": "startPrometheus"})
        self.kafka_producer.flush()
        status, error = self.orchestratorActionResult.CheckTransaction(timestamp)
        if status:
            if self.debug:
                print("prometheus thread started")
            message="prometheus thread started"
        else:
            if self.debug:
                print("Error in starting prometheus thread, error reason: ", error)
            message="Error in starting prometheus thread, error reason: " + error
        return status, message

    def resetZipkinStats(self):
        timestamp = time.time()
        self.kafka_producer.send('action', value={ "transactionId": timestamp, "order": "resetZipkinStats"})
        self.kafka_producer.flush()
        status, error = self.orchestratorActionResult.CheckTransaction(timestamp)
        if status:
            if self.debug:
                print("zipkin stats reset done")
            message="zipkin stats reset done"
        else:
            if self.debug:
                print("Error in resetting zipkin stats, error reason: ", error)
            message="Error in resetting zipkin stats, error reason: " + error
        return status, message

    def resetPrometheusStats(self):
        timestamp = time.time()
        self.kafka_producer.send('action', value={ "transactionId": timestamp, "order": "resetPrometheusStats"})
        self.kafka_producer.flush()
        status, error = self.orchestratorActionResult.CheckTransaction(timestamp)
        if status:
            if self.debug:
                print("prometheus stats reset done")
            message="prometheus stats reset done"
        else:
            if self.debug:
                print("Error in resetting prometheus stats, error reason: ", error)
            message="Error in resetting prometheus stats, error reason: " + error
        return status, message

    def activateDebug(self,component=None,level=1):
        if component != None:
            timestamp = time.time()
            self.kafka_producer.send('action', value={ "transactionId": timestamp, "order": "activateDebug", "component": component, "level": level})
            self.kafka_producer.flush()
            status, error = self.orchestratorActionResult.CheckTransaction(timestamp)
            if status:
                if self.debug:
                    print(component, " debug activated with level: ", level)
                message=component + " debug activated with level: " + str(level)
            else:
                if self.debug:
                    print("Error in activating debug for component: ", component, " , error reason: ", error)
                message="Error in activating debug for component: " + component + " , error reason: " + error
        return status, message

    def deactivateDebug(self,component=None):
        if component != None:
            timestamp = time.time()
            self.kafka_producer.send('action', value={ "transactionId": timestamp, "order": "deactivateDebug", "component": component})
            self.kafka_producer.flush()
            status, error = self.orchestratorActionResult.CheckTransaction(timestamp)
            if status:
                if self.debug:
                    print(component, " debug deactivated")
                message=component + " debug deactivated"
            else:
                if self.debug:
                    print("Error in deactivating debug for component: ", component, " , error reason: ", error)
                message="Error in deactivating debug for component: " + component + " , error reason: " + error
        return status, message

    def setDeploymentLimit(self,deployment="front-dynamic-component", min=1, max=10):
        timestamp = time.time()
        self.kafka_producer.send('action', value={ "transactionId": timestamp, "order": "setDeploymentLimit", "deployment": deployment, "min": min, "max": max})
        self.kafka_producer.flush()
        status, error = self.orchestratorActionResult.CheckTransaction(timestamp)
        if status:
            if self.debug:
                print("Limit set for deployment: ", deployment, " with min: ", min, " and max: ", max)
            message="Limit set for deployment: " + deployment + " with min: " + str(min) + " and max: " + str(max)
        else:
            if self.debug:
                print("Error in setting limit min: ", min, " and max: ", max, " for deployment: ", deployment ," ,error reason: ", error)
            message="Error in setting limit min: " + str(min) + " and max: " + str(max) + " for deployment: " + deployment + " ,error reason: " + error
        return status, message

    def setSampleNumberBeforeAcceptScaling(self,sampleNumber=0):
        timestamp = time.time()
        self.kafka_producer.send('action', value={ "transactionId": timestamp, "order": "setSampleNumberBeforeAcceptScaling", "number": sampleNumber})
        self.kafka_producer.flush()
        status, error = self.orchestratorActionResult.CheckTransaction(timestamp)
        if status:
            if self.debug:
                print("Sample number before accept scaling is set to: ", sampleNumber)
            message="Sample number before accept scaling is set to: " + str(sampleNumber)
        else:
            if self.debug:
                print("Error in setting sample number before accept scaling to: ", sampleNumber, " ,error reason: ", error)
            message="Error in setting sample number before accept scaling to: " + str(sampleNumber) + " ,error reason: " + error
        return status, message

    def getConfig(self):
        timestamp = time.time()
        self.kafka_producer.send('action', value={ "transactionId": timestamp, "order": "getConfig"})
        self.kafka_producer.flush()
        status, error = self.orchestratorActionResult.CheckTransaction(timestamp)
        if status:
            if self.debug:
                print("Orchestrator configuration dumped in message")
            message=error
        else:
            if self.debug:
                print("Error in retrieving orchestrator configuration ,error reason: ", error)
            message="Error in retrieving orchestrator configuration ,error reason: " + error
        return status, message

    def getDeploymentState(self, deployment):
        timestamp = time.time()
        self.kafka_producer.send('action', value={ "transactionId": timestamp, "order": "getDeploymentState", "deployment": deployment})
        self.kafka_producer.flush()
        status, error = self.orchestratorActionResult.CheckTransaction(timestamp)
        if status:
            if self.debug:
                print("Deployment: ", deployment, " dumped in message")
            message=error
        else:
            if self.debug:
                print("Error in retrieving deployment: " , deployment , " state from orchestrator ,error reason: ", error)
            message="Error in retrieving deployment: " + deployment + " state from orchestrator ,error reason: " + error
        return status, message

    def setZipkinService(self,services=['istio-ingressgateway']):
        timestamp = time.time()
        self.kafka_producer.send('action', value={ "transactionId": timestamp, "order": "setZipkinService", "services": services})
        self.kafka_producer.flush()
        status, error = self.orchestratorActionResult.CheckTransaction(timestamp)
        if status:
            if self.debug:
                print("Zipkin now watching service: ", services)
            message="Zipkin now watching service: " + str(services)
        else:
            if self.debug:
                print("Error in setting zipkin service to: ", services, " ,error reason: ", error)
            message="Error in setting zipkin service to: " + str(services) + " ,error reason: " + error
        return status, message

    def setPrometheusService(self,deployments=['front-dynamic-component']):
        timestamp = time.time()
        self.kafka_producer.send('action', value={ "transactionId": timestamp, "order": "setPrometheusService", "services": deployments})
        self.kafka_producer.flush()
        status, error = self.orchestratorActionResult.CheckTransaction(timestamp)
        if status:
            if self.debug:
                print("Prometheus now watching deployment: ", deployments)
            message="Prometheus now watching deployment: " + str(deployments)
        else:
            if self.debug:
                print("Error in setting prometheus service to: ", deployments, " ,error reason: ", error)
            message="Error in setting prometheus service to: " + str(deployments) + " ,error reason: " + error
        return status, message

    def setZipkinLookback(self,lookback=12):
        timestamp = time.time()
        self.kafka_producer.send('action', value={ "transactionId": timestamp, "order": "setZipkinLookback", "lookback": lookback})
        self.kafka_producer.flush()
        status, error = self.orchestratorActionResult.CheckTransaction(timestamp)
        if status:
            if self.debug:
                print("Zipkin lookback set to: ", lookback, " seconds")
            message="Zipkin lookback set to: " + str(lookback) + " seconds"
        else:
            if self.debug:
                print("Error in setting zipkin lookback to: ", lookback, " seconds ,error reason: ", error)
            message="Error in setting zipkin lookback to: " + str(lookback) + " seconds ,error reason: " + error
        return status, message

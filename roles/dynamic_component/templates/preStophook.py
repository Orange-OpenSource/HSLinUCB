# Software Name : HSLinUCB
# SPDX-FileCopyrightText: Copyright (c) 2021 Orange
# SPDX-License-Identifier: GPL-2.0
#
# This software is distributed under the GNU General Public License v2.0 license
#
# Author: David DELANDE <david.delande@orange.com> et al.

from kubernetes import config
from kubernetes import client
from kubernetes.client.models.v1_scale import V1Scale
import os
import socket
import time
import json
import requests

if os.path.exists('/var/run/secrets/kubernetes.io/serviceaccount/token'):
    config.load_incluster_config()
else:
    try:
        config.load_kube_config()
    except:
        print('Unable to find cluster configuration')
        exit(1)

## getting the hostname by socket.gethostname() method
hostname = socket.gethostname()
## getting the IP address using socket.gethostbyname() method
ip_address = socket.gethostbyname(hostname)
v1 = client.CoreV1Api()
while(True):
    found=False
    endpoint = v1.list_namespaced_endpoints(namespace="default",label_selector='app=front-dynamic-component')
    for entry in endpoint.items[0].subsets[0].addresses:
        if entry.ip == ip_address:
            found=True
    if found:
        print("Pod IP is still here..")
        time.sleep(2)
    else:
        print("Pod IP is not here so we can exit this script")
        break

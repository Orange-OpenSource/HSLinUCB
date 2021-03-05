# Software Name : HSLinUCB
# SPDX-FileCopyrightText: Copyright (c) 2021 Orange
# SPDX-License-Identifier: GPL-2.0
#
# This software is distributed under the GNU General Public License v2.0 license
#
# Author: David DELANDE <david.delande@orange.com> et al.

from random import uniform
import time
import os
import math
import requests
from cgi import parse_qs

BackHostname = "back-dynamic-component-service.default.svc.cluster.local" if (os.environ.get("BACK_COMPONENT_HOSTNAME") == None) else os.environ.get("BACK_COMPONENT_HOSTNAME")
BackHostname2 = "back2-dynamic-component-service.default.svc.cluster.local" if (os.environ.get("BACK2_COMPONENT_HOSTNAME") == None) else os.environ.get("BACK2_COMPONENT_HOSTNAME")

ComponentName = "front" if (os.environ.get("COMPONENT_NAME") == None) else os.environ.get("COMPONENT_NAME")

def getForwardHeaders(environ):
    headers = {}
    if 'HTTP_X_REQUEST_ID' in environ:
        headers['x-request-id'] = environ['HTTP_X_REQUEST_ID']
    if 'HTTP_X_B3_TRACEID' in environ:
        headers['x-b3-traceid'] = environ['HTTP_X_B3_TRACEID']
    if 'HTTP_X_B3_SPANID' in environ:
        headers['x-b3-spanid'] = environ['HTTP_X_B3_SPANID']
    if 'HTTP_X_B3_PARENTSPANID' in environ:
        headers['x-b3-parentspanid'] = environ['HTTP_X_B3_PARENTSPANID']
    if 'HTTP_X_B3_SAMPLED' in environ:
        headers['x-b3-sampled'] = environ['HTTP_X_B3_SAMPLED']
    if 'HTTP_X_B3_FLAGS' in environ:
        headers['x-b3-flags'] = environ['HTTP_X_B3_FLAGS']
    if 'HTTP_X_OT_SPAN_CONTEXT' in environ:
        headers['x-ot-span-context'] = environ['HTTP_X_OT_SPAN_CONTEXT']
    if 'HTTP_USER_AGENT' in environ:
        headers['user-agent'] = environ['HTTP_USER_AGENT']
    return headers

def application(environ, start_response):
    start = time.time()
    headers = getForwardHeaders(environ)
    argument = parse_qs(environ['QUERY_STRING'])
    status = '200 OK'
    try:
        url = "http://" + BackHostname + ":80/" + str(argument.get('path',[''])[0])
        res = requests.get(url, headers=headers, timeout=20.0)
    except:
        res = None
    try:
        url = "http://" + BackHostname2 + ":80/" + str(argument.get('path',[''])[0])
        res2 = requests.get(url, headers=headers, timeout=20.0)
    except:
        res2 = None
    if res and res.status_code == 200 and res2 and res2.status_code == 200:
        output = bytes(res.text + " , " + res2.text + " through " + ComponentName, encoding= 'utf-8')
    else:
        #status = res.status_code if res is not None and res.status_code else 500
        output = bytes('Error contacting back component from ' + ComponentName, encoding= 'utf-8')
    response_headers = [('Content-type', 'text/plain'),
                        ('Content-Length', str(len(output)))]
    start_response(status, response_headers)

    return [output]

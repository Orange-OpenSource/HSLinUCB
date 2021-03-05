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

ComponentName = "front" if (os.environ.get("COMPONENT_NAME") == None) else os.environ.get("COMPONENT_NAME")

def application(environ, start_response):
    start = time.time()
    i = 0
    array = []
    argument = parse_qs(environ['QUERY_STRING'])
    max = int(argument.get('cpu',[0])[0]) * 1000
    max_wait = float(argument.get('wait',[0])[0])/1000
    while (i < max):
        array.append(i)
        i += 1
        array.pop()
    stop = time.time()
    job_time = stop - start
    if (max_wait - job_time > 0):
        time.sleep(max_wait - job_time)
        output = bytes("Job time:" + str(max_wait) + " by " + ComponentName, encoding= 'utf-8')
    else:
        output = bytes("Job time:" + str(job_time) + " by " + ComponentName, encoding= 'utf-8')
    status = '200 OK'

    response_headers = [('Content-type', 'text/plain'),
                        ('Content-Length', str(len(output)))]
    start_response(status, response_headers)

    return [output]

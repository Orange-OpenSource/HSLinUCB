#!/usr/bin/python3
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
import signal
import sys
loop = True
def signal_handler(sig, frame):
    global loop
    print("You press ctrl c")
    loop = False
signal.signal(signal.SIGINT, signal_handler)
try:
   print("Response size expected : " + sys.argv[1] + "octets")
except:
   print("ERROR: You must pass the expected response size as first argument")
   print("Usage: ./" + sys.argv[0] + " ExpectedResponseSize IterationNumber")
   print("ResponseSize: Expected response size in octets")
   print("IterationNumber: Number of component calls. If IterationNumber is not passed, the component will be called forever")
   exit(0)
try:
   if sys.argv[2]:
      IterationNumber = sys.argv[2]
except:
   IterationNumber = -1
if int(IterationNumber) == -1:
   print("Number of component calls : Infinite")
else:
   print("Number of component calls : " + str(IterationNumber))
print("Wait 2 seconds before starting..")
time.sleep(2)
Iteration = 0
while loop:
   start = time.time()
   try:
      headers = {}
      headers['Host'] = "dynamic-component.service.hslinucb"
      url = "http://{{hostvars[groups['master'][0]].ansible_default_ipv4.address}}:{{ingress_gateway_port}}/ResponseSize?size=" + sys.argv[1]
      res = requests.get(url, headers=headers, timeout=20.0)
   except:
      res = None
   if res and res.status_code == 200:
      print(res.text)
   else:
      status = res.status_code if res is not None and res.status_code else 500
      print('Error contacting component', status)
   stop = time.time()
   print("duration:", stop - start)
   Iteration += 1
   if int(Iteration) == int(IterationNumber):
      loop = False

# Software Name : HSLinUCB
# SPDX-FileCopyrightText: Copyright (c) 2021 Orange
# SPDX-License-Identifier: GPL-2.0
#
# This software is distributed under the GNU General Public License v2.0 license
#
# Author: David DELANDE <david.delande@orange.com> et al.

curl -i "http://{{hostvars[groups['master'][0]].ansible_default_ipv4.address}}:{{ingress_gateway_port}}/code/Proxy2BackSerial?path1=ResponseTime?time=100&path2=Proxy?path=ResponseTime?time=200" -H "Host: dynamic-component.service.hslinucb"

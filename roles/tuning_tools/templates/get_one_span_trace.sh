# Software Name : HSLinUCB
# SPDX-FileCopyrightText: Copyright (c) 2021 Orange
# SPDX-License-Identifier: GPL-2.0
#
# This software is distributed under the GNU General Public License v2.0 license
#
# Author: David DELANDE <david.delande@orange.com> et al.

curl "http://{{ zipkin.spec.clusterIP }}:9411/api/v2/traces?serviceName=front-dynamic-component.default&spanName=front-dynamic-component-service.default.svc.cluster.local:80/*&limit=1" | jq .

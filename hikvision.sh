#!/bin/bash

#curl -v --basic --user admin:petecus00  http://192.168.1.245/ISAPI/System/deviceInfo
curl -v --basic --user admin:petecus00  http://192.168.1.245/ISAPI/Streaming/channels/400/picture > /tmp/some.jpg; eom /tmp/some.jpg

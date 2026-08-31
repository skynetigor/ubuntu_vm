#!/bin/bash
set -e
chown -R elasticsearch:elasticsearch /var/lib/elasticsearch
exec su -s /bin/bash elasticsearch -c "/start-es.sh"

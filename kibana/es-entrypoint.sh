#!/bin/bash
set -e
chown -R elasticsearch:elasticsearch /es
exec su -s /bin/bash elasticsearch -c "/start-es.sh"

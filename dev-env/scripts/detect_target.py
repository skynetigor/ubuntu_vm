import os
import re
from urllib.parse import urlparse


def detect_target(environment=None):
    environment = os.environ if environment is None else environment
    target = environment['KIBANA_TARGET']
    parsed = urlparse(target)
    match = re.fullmatch(r'/([^/]+)/([^/]+)/pull/(\d+)(?:/.*)?', parsed.path)
    result = {'is_pr': False, 'owner': '', 'repo': '', 'number': 0}
    if match and parsed.hostname == 'github.com':
        result = {
            'is_pr': True,
            'owner': match.group(1),
            'repo': match.group(2).removesuffix('.git'),
            'number': int(match.group(3)),
        }
    return result
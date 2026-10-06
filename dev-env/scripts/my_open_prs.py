import json
import os
import re
import urllib.parse
import urllib.request

STATE_PATH = '/opt/kibana-cache/pr-sweep-state.json'


def github(environment, path):
    token = environment.get('GH_TOKEN', '').strip()
    if not token:
        raise RuntimeError('GH_TOKEN is required to list pull requests')
    request = urllib.request.Request(
        'https://api.github.com' + path,
        headers={
            'Accept': 'application/vnd.github+json',
            'Authorization': f'Bearer {token}',
            'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': 'kibana-pr-sweep-workflow',
        },
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.load(response)


def github_graphql(environment, query):
    token = environment.get('GH_TOKEN', '').strip()
    request = urllib.request.Request(
        'https://api.github.com/graphql',
        data=json.dumps({'query': query}).encode('utf-8'),
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'User-Agent': 'kibana-pr-sweep-workflow',
        },
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.load(response)


def is_queued_for_merge(environment, repository, number, pull):
    """True when auto-merge is enabled or the PR sits in the GitHub merge queue."""
    if pull.get('auto_merge'):
        return True
    owner, name = repository.split('/')
    query = (
        'query { repository(owner: "%s", name: "%s") { pullRequest(number: %d) '
        '{ isInMergeQueue autoMergeRequest { enabledAt } } } }' % (owner, name, number)
    )
    node = ((github_graphql(environment, query).get('data') or {}).get('repository') or {}).get('pullRequest') or {}
    return bool(node.get('isInMergeQueue') or node.get('autoMergeRequest'))


def read_state():
    try:
        with open(STATE_PATH, encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def check_repository(environment):
    repository = environment['REPOSITORY'].strip()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('REPOSITORY must use owner/repository format')
    return repository


def list_my_open_prs(environment=None):
    """Open, non-draft PRs authored by the token's user that changed since their last sweep."""
    environment = os.environ if environment is None else environment
    repository = check_repository(environment)
    author = (environment.get('AUTHOR') or '').strip() or github(environment, '/user')['login']
    if not re.fullmatch(r'[A-Za-z0-9-]+', author):
        raise ValueError('AUTHOR contains invalid characters')
    force = environment.get('FORCE', '').lower() == 'true'
    max_prs = max(1, int(environment.get('MAX_PRS') or 10))

    query = urllib.parse.quote(f'repo:{repository} is:pr is:open draft:false author:{author}')
    found = github(environment, f'/search/issues?q={query}&per_page=100&sort=created&order=asc')
    state = read_state()
    selected, skipped, queued_for_merge = [], [], []
    for item in found.get('items', []):
        number = item['number']
        pull = github(environment, f'/repos/{repository}/pulls/{number}')
        if pull.get('draft') or pull.get('state') != 'open':
            continue
        if is_queued_for_merge(environment, repository, number, pull):
            queued_for_merge.append(number)
            continue
        entry = {
            'number': number,
            'url': pull['html_url'],
            'title': pull['title'],
            'head_sha': pull['head']['sha'],
        }
        if not force and state.get(f'{repository}#{number}') == entry['head_sha']:
            skipped.append(number)
        elif len(selected) < max_prs:
            selected.append(entry)
        else:
            skipped.append(number)
    return {'author': author, 'prs': selected, 'skipped': skipped, 'queued_for_merge': queued_for_merge, 'total_open': len(found.get('items', []))}


def record_swept_pr(environment=None):
    """Remember the PR head after a run, so the run's own fix commits are not reviewed again."""
    environment = os.environ if environment is None else environment
    repository = check_repository(environment)
    number = int(environment['PR_NUMBER'])
    head_sha = github(environment, f'/repos/{repository}/pulls/{number}')['head']['sha']
    state = read_state()
    state[f'{repository}#{number}'] = head_sha
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    temporary = STATE_PATH + '.tmp'
    with open(temporary, 'w', encoding='utf-8') as handle:
        json.dump(state, handle, indent=2)
    os.replace(temporary, STATE_PATH)
    return {'number': number, 'head_sha': head_sha}

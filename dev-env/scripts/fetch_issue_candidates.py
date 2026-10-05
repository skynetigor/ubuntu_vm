import json
import os
import re
import subprocess

IDENTIFIER = re.compile(r'[A-Za-z0-9_.-]+')


def gh_api(environment, owner, *args):
    token_name = 'GH_UPSTREAM_TOKEN' if owner.lower() == 'elastic' else 'GH_TOKEN'
    token = environment.get(token_name, '').strip()
    if not token:
        raise RuntimeError(f'{token_name} is required for GitHub issue access')
    try:
        result = subprocess.run(
            ['gh', 'api', *args], text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=90,
            env={**os.environ, **environment, 'GH_TOKEN': token},
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError('GitHub API request timed out after 90 seconds') from error
    if result.returncode:
        raise RuntimeError('GitHub API request failed: ' + result.stderr[-3000:])
    return json.loads(result.stdout)


def fetch_issue_candidates(environment=None):
    environment = os.environ if environment is None else environment
    max_chars = int(environment.get('MAX_BODY_CHARS', '8000'))
    max_commits = int(environment.get('MAX_COMMITS', '100'))
    base_commit = environment['BASE_COMMIT'].strip()
    if not re.fullmatch(r'[0-9a-f]{7,40}', base_commit):
        raise ValueError('BASE_COMMIT must be a commit SHA')

    print(f'Reading commit messages since {base_commit[:12]}', flush=True)
    log = subprocess.run(
        ['git', 'log', f'--max-count={max_commits}', '--format=%H%x1f%s%x1f%b%x1e', f'{base_commit}..HEAD'],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, check=True,
    ).stdout
    commits = []
    for record in log.split('\x1e'):
        parts = record.strip().split('\x1f')
        if len(parts) == 3:
            commits.append({'sha': parts[0], 'subject': parts[1], 'body': parts[2][:max_chars]})

    result = {
        'source_branch': environment.get('SOURCE_BRANCH', ''),
        'commits': commits,
        'pull_request': None,
        'closing_issues': [],
    }
    if environment.get('IS_PR', '').lower() != 'true':
        return result

    owner = environment['PR_OWNER']
    repo = environment['PR_REPO']
    number = environment['PR_NUMBER']
    if not IDENTIFIER.fullmatch(owner) or not IDENTIFIER.fullmatch(repo) or not number.isdigit():
        raise ValueError('Invalid PR owner, repo, or number')

    print(f'Fetching closing issues for {owner}/{repo}#{number}', flush=True)
    query = '''query($owner:String!, $name:String!, $number:Int!) {
      repository(owner:$owner, name:$name) {
        pullRequest(number:$number) {
          title body url headRefName
          closingIssuesReferences(first:20) {
            nodes { number title url state repository { nameWithOwner } }
          }
        }
      }
    }'''
    data = gh_api(
        environment, owner, 'graphql', '-f', 'query=' + query,
        '-F', 'owner=' + owner, '-F', 'name=' + repo, '-F', 'number=' + number,
    )
    pull = (data.get('data') or {}).get('repository', {}).get('pullRequest')
    if pull is None:
        raise RuntimeError('GitHub did not return the pull request')
    result['pull_request'] = {
        'title': pull.get('title', ''),
        'body': (pull.get('body') or '')[:max_chars],
        'url': pull.get('url', ''),
        'head_ref': pull.get('headRefName', ''),
    }
    # GitHub returns null nodes for linked issues the token cannot read, e.g. in private repos.
    nodes = pull['closingIssuesReferences']['nodes']
    result['inaccessible_closing_issues'] = sum(1 for node in nodes if not node)
    if result['inaccessible_closing_issues']:
        print(f"Skipping {result['inaccessible_closing_issues']} inaccessible closing issue(s)", flush=True)
    result['closing_issues'] = [
        {
            'ref': f"{node['repository']['nameWithOwner']}#{node['number']}",
            'title': node.get('title', ''),
            'url': node.get('url', ''),
            'state': node.get('state', ''),
        }
        for node in nodes
        if node and node.get('repository')
    ]
    return result

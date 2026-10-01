import json
import os
import re
import urllib.error
import urllib.request


def sync_github_fork(environment=None):
    environment = os.environ if environment is None else environment
    token = environment.get('GH_TOKEN', '').strip()
    if not token:
        raise RuntimeError('GH_TOKEN is required to synchronize GitHub forks')

    fork = json.loads(environment['FORK_JSON'])
    owner = str(fork.get('owner', '')).strip()
    repository = str(fork.get('repository', '')).strip()
    branch = str(fork.get('branch', 'main')).strip()
    expected_parent = environment.get('EXPECTED_PARENT', '').strip()
    identifier = re.compile(r'[A-Za-z0-9_.-]+')
    if not identifier.fullmatch(owner) or not identifier.fullmatch(repository):
        raise ValueError('Fork owner and repository contain invalid characters')
    if not re.fullmatch(r'[A-Za-z0-9._/-]+', branch) or '..' in branch:
        raise ValueError('Fork branch contains invalid characters')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', expected_parent):
        raise ValueError('EXPECTED_PARENT must use owner/repository format')

    headers = {
        'Accept': 'application/vnd.github+json',
        'Authorization': f'Bearer {token}',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'kibana-fork-sync-workflow',
    }

    metadata_request = urllib.request.Request(
        f'https://api.github.com/repos/{owner}/{repository}',
        headers=headers,
    )
    try:
        with urllib.request.urlopen(metadata_request, timeout=90) as response:
            metadata = json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError) as error:
        raise RuntimeError(
            f'Unable to verify fork metadata for {owner}/{repository}'
        ) from error
    parent = (metadata.get('parent') or {}).get('full_name')
    if metadata.get('fork') is not True or parent != expected_parent:
        raise RuntimeError(
            f'{owner}/{repository} is not a fork of expected parent {expected_parent}'
        )

    request = urllib.request.Request(
        f'https://api.github.com/repos/{owner}/{repository}/merge-upstream',
        data=json.dumps({'branch': branch}).encode(),
        method='POST',
        headers={
            **headers,
            'Content-Type': 'application/json',
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        try:
            details = json.load(error)
            message = details.get('message', 'GitHub API request failed')
        except (json.JSONDecodeError, AttributeError):
            message = 'GitHub API request failed'
        raise RuntimeError(
            f'Unable to synchronize {owner}/{repository}:{branch}: '
            f'GitHub returned HTTP {error.code}: {message}'
        ) from error
    except urllib.error.URLError as error:
        raise RuntimeError(
            f'Unable to synchronize {owner}/{repository}:{branch}: GitHub request failed'
        ) from error

    merge_type = result.get('merge_type', 'unknown')
    return {
        'fork': f'{owner}/{repository}',
        'upstream': expected_parent,
        'branch': branch,
        'status': 'up_to_date' if merge_type == 'none' else 'synchronized',
        'changed': merge_type != 'none',
        'merge_type': merge_type,
        'message': result.get('message', ''),
    }
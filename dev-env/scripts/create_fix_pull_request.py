import json
import os
import urllib.error
import urllib.parse
import urllib.request


def create_fix_pull_request(environment=None):
    environment = os.environ if environment is None else environment
    token = environment.get('GH_TOKEN', '').strip()
    if not token:
        raise RuntimeError('GH_TOKEN is required to create the fix pull request')

    publish = json.loads(environment['PUBLISH_RESULT_JSON'])
    draft = json.loads(environment['PR_DRAFT_JSON'])
    repository = publish.get('fork_repository')
    head_branch = publish.get('fix_branch')
    base_branch = publish.get('base_branch')
    title = str(draft.get('title', '')).strip()
    body = str(draft.get('body', '')).strip()
    if not repository or not head_branch or not base_branch:
        raise RuntimeError('Published branch metadata is incomplete')
    if not title or not body:
        raise RuntimeError('Agent PR draft must include title and body')
    comment_review = environment.get('COMMENT_REVIEW', '').strip()
    if comment_review:
        body += '\n\n' + comment_review
    if len(body) > 65536:
        raise RuntimeError('Fix PR body and proposed review replies exceed the GitHub body limit')

    owner = repository.split('/', 1)[0]
    headers = {
        'Accept': 'application/vnd.github+json',
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'User-Agent': 'kibana-workflow-review-fixes',
        'X-GitHub-Api-Version': '2022-11-28',
    }

    query = urllib.parse.urlencode({
        'state': 'open',
        'head': f'{owner}:{head_branch}',
        'base': base_branch,
    })
    existing_request = urllib.request.Request(
        f'https://api.github.com/repos/{repository}/pulls?{query}',
        headers=headers,
    )
    try:
        with urllib.request.urlopen(existing_request, timeout=90) as response:
            existing = json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError) as error:
        raise RuntimeError('Unable to check for an existing fix pull request') from error

    if existing:
        pull_request = existing[0]
        if comment_review and pull_request.get('body') != body:
            update_request = urllib.request.Request(
                f'https://api.github.com/repos/{repository}/pulls/{pull_request["number"]}',
                data=json.dumps({'body': body}).encode(),
                method='PATCH',
                headers=headers,
            )
            try:
                with urllib.request.urlopen(update_request, timeout=90) as response:
                    pull_request = json.load(response)
            except (urllib.error.HTTPError, urllib.error.URLError) as error:
                raise RuntimeError('Unable to update the fix PR with proposed comment replies') from error
        return {
            'status': 'existing',
            'created': False,
            'number': pull_request['number'],
            'url': pull_request['html_url'],
            'repository': repository,
            'head_branch': head_branch,
            'base_branch': base_branch,
            'body': pull_request.get('body') or body,
        }

    request = urllib.request.Request(
        f'https://api.github.com/repos/{repository}/pulls',
        data=json.dumps({
            'title': title[:256],
            'body': body,
            'head': head_branch,
            'base': base_branch,
        }).encode(),
        method='POST',
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            pull_request = json.load(response)
    except urllib.error.HTTPError as error:
        try:
            details = json.load(error)
            message = details.get('message', 'GitHub API request failed')
        except (json.JSONDecodeError, AttributeError):
            message = 'GitHub API request failed'
        raise RuntimeError(
            f'Unable to create fix pull request: GitHub returned HTTP {error.code}: {message}'
        ) from error
    except urllib.error.URLError as error:
        raise RuntimeError('Unable to create fix pull request: GitHub request failed') from error

    return {
        'status': 'created',
        'created': True,
        'number': pull_request['number'],
        'url': pull_request['html_url'],
        'repository': repository,
        'head_branch': head_branch,
        'base_branch': base_branch,
        'body': body,
    }
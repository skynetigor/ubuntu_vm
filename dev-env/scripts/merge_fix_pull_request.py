import json
import os
import urllib.error
import urllib.request


def merge_fix_pull_request(environment=None):
    environment = os.environ if environment is None else environment
    token = environment.get('GH_TOKEN', '').strip()
    if not token:
        raise RuntimeError('GH_TOKEN is required to merge the fix pull request')

    fix_pr = json.loads(environment['FIX_PR_RESULT_JSON'])
    repository = fix_pr.get('repository')
    number = fix_pr.get('number')
    expected_sha = environment.get('EXPECTED_HEAD_SHA', '').strip()
    merge_method = environment.get('MERGE_METHOD', 'squash')
    if not repository or not number or not expected_sha:
        raise RuntimeError('Fix pull request metadata is incomplete')

    headers = {
        'Accept': 'application/vnd.github+json',
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'User-Agent': 'kibana-workflow-review-fixes',
        'X-GitHub-Api-Version': '2022-11-28',
    }
    url = f'https://api.github.com/repos/{repository}/pulls/{number}'

    def github(method, path, body=None):
        request = urllib.request.Request(
            url + path, method=method, headers=headers,
            data=json.dumps(body).encode() if body is not None else None,
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            try:
                message = json.load(error).get('message', 'GitHub API request failed')
            except (json.JSONDecodeError, AttributeError):
                message = 'GitHub API request failed'
            return error.code, {'message': message}
        except urllib.error.URLError as error:
            raise RuntimeError('GitHub request failed while merging the fix pull request') from error

    result = {'repository': repository, 'number': number, 'url': fix_pr.get('url'), 'merge_method': merge_method}
    status, pull = github('GET', '')
    if status != 200:
        return {**result, 'status': 'failed', 'merged': False, 'error': f'HTTP {status}: {pull["message"]}'}
    if pull.get('merged'):
        return {**result, 'status': 'merged', 'merged': True, 'already_merged': True,
                'merge_commit_sha': pull.get('merge_commit_sha')}
    if pull.get('state') != 'open':
        return {**result, 'status': 'failed', 'merged': False, 'error': 'Fix pull request is closed without merge'}
    # Never merge commits the approver did not see.
    if pull['head']['sha'] != expected_sha:
        return {**result, 'status': 'head_changed', 'merged': False,
                'error': f'Fix branch moved to {pull["head"]["sha"]} after approval of {expected_sha}'}

    status, merge = github('PUT', '/merge', {'merge_method': merge_method, 'sha': expected_sha})
    if status != 200 or not merge.get('merged'):
        return {**result, 'status': 'failed', 'merged': False, 'error': f'HTTP {status}: {merge.get("message")}'}
    return {**result, 'status': 'merged', 'merged': True, 'already_merged': False,
            'merge_commit_sha': merge.get('sha')}

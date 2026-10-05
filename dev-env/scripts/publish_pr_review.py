import json
import os
import re
import subprocess


def publish_pr_review(environment=None):
    environment = os.environ if environment is None else environment
    pr = json.loads(environment['PR_JSON'])
    review = json.loads(environment['REVIEW_JSON'])
    marker = environment['MARKER']
    owner, repo, number = pr['owner'], pr['repo'], int(pr['number'])
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', owner) or not re.fullmatch(r'[A-Za-z0-9_.-]+', repo):
        raise ValueError('Invalid PR owner or repo')
    token_name = 'GH_UPSTREAM_TOKEN' if owner.lower() == 'elastic' else 'GH_TOKEN'
    token = environment.get(token_name, '').strip()
    if not token:
        raise RuntimeError(f'{token_name} is required to publish PR reviews')

    def gh_api(*args, payload=None):
        try:
            result = subprocess.run(
                ['gh', 'api', *args], text=True,
                input=None if payload is None else json.dumps(payload),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=90,
                env={**os.environ, **environment, 'GH_TOKEN': token},
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError('GitHub API request timed out after 90 seconds') from error
        if result.returncode:
            raise RuntimeError('GitHub API request failed: ' + result.stderr[-2500:])
        return json.loads(result.stdout) if result.stdout.strip() else {}

    pull = gh_api(f'repos/{owner}/{repo}/pulls/{number}')
    current_head = pull['head']['sha']
    if current_head != review['commit_id']:
        print(f'PR head moved from {review["commit_id"][:12]} to {current_head[:12]}; not publishing', flush=True)
        return {'status': 'head_moved', 'review_id': None, 'url': '', 'current_head': current_head}

    page = 1
    while True:
        reviews = gh_api(f'repos/{owner}/{repo}/pulls/{number}/reviews?per_page=100&page={page}')
        for existing in reviews:
            if marker in (existing.get('body') or ''):
                print('Review for this commit was already published', flush=True)
                return {
                    'status': 'already_published',
                    'review_id': existing['id'],
                    'url': existing.get('html_url', ''),
                    'current_head': current_head,
                }
        if len(reviews) < 100:
            break
        page += 1

    print(f'Publishing review with {len(review["comments"])} inline comments', flush=True)
    created = gh_api(
        '--method', 'POST', f'repos/{owner}/{repo}/pulls/{number}/reviews', '--input', '-',
        payload=review,
    )
    return {
        'status': 'published',
        'review_id': created.get('id'),
        'url': created.get('html_url', ''),
        'current_head': current_head,
    }

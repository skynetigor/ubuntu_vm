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

    def gh_api(*args, payload=None):
        try:
            result = subprocess.run(
                ['gh', 'api', *args], text=True,
                input=None if payload is None else json.dumps(payload),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=90,
                env={**os.environ, **environment},
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
        return {'status': 'head_moved', 'event': '', 'review_id': None, 'url': '', 'current_head': current_head}

    page = 1
    while True:
        reviews = gh_api(f'repos/{owner}/{repo}/pulls/{number}/reviews?per_page=100&page={page}')
        for existing in reviews:
            if marker in (existing.get('body') or ''):
                print('Review for this commit was already published', flush=True)
                return {
                    'status': 'already_published',
                    'event': existing.get('state', ''),
                    'review_id': existing['id'],
                    'url': existing.get('html_url', ''),
                    'current_head': current_head,
                }
        if len(reviews) < 100:
            break
        page += 1

    print(f'Publishing {review["event"]} review with {len(review["comments"])} inline comments', flush=True)
    try:
        created = gh_api(
            '--method', 'POST', f'repos/{owner}/{repo}/pulls/{number}/reviews', '--input', '-',
            payload=review,
        )
        status = 'published'
    except RuntimeError as error:
        # GitHub forbids approving or requesting changes on a PR authored by the token owner.
        if review['event'] == 'COMMENT' or 'your own pull request' not in str(error):
            raise
        print('Token owner authored this PR; publishing as a plain comment review', flush=True)
        created = gh_api(
            '--method', 'POST', f'repos/{owner}/{repo}/pulls/{number}/reviews', '--input', '-',
            payload={**review, 'event': 'COMMENT'},
        )
        status = 'published_as_comment'
    return {
        'status': status,
        'event': review['event'] if status == 'published' else 'COMMENT',
        'review_id': created.get('id'),
        'url': created.get('html_url', ''),
        'current_head': current_head,
    }

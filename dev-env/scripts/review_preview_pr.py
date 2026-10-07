import json
import os
import re
import subprocess


def gh_api(environment, *args, payload=None, allow_status=()):
    result = subprocess.run(
        ['gh', 'api', *args, *(['--input', '-'] if payload is not None else [])], text=True,
        input=None if payload is None else json.dumps(payload),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90,
        env={**os.environ, **environment},
    )
    if result.returncode:
        if any(status in result.stderr for status in allow_status):
            return None
        raise RuntimeError('GitHub API request failed: ' + result.stderr[-2000:])
    return json.loads(result.stdout) if result.stdout.strip() else {}


def check_repository(repository):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('PREVIEW_REPOSITORY must use owner/repository format')
    return repository


def preview_refs(number, merge_base, head_commit):
    return (
        f'review-preview/pr-{number}-base-{merge_base[:10]}',
        f'review-preview/pr-{number}-head-{head_commit[:10]}',
    )


def create_review_preview(environment=None):
    """Mirrors an external PR into a fork (base = merge base, head = PR head) and posts the review there."""
    environment = os.environ if environment is None else environment
    pr = json.loads(environment['PR_JSON'])
    review = json.loads(environment['REVIEW_JSON'])
    repository = check_repository(environment['PREVIEW_REPOSITORY'])
    merge_base, head_commit = environment['MERGE_BASE'], environment['HEAD_COMMIT']
    for sha in (merge_base, head_commit):
        if not re.fullmatch(r'[0-9a-f]{40}', sha):
            raise ValueError('MERGE_BASE and HEAD_COMMIT must be full commit SHAs')
    number = int(pr['number'])
    original = f"{pr['owner']}/{pr['repo']}#{number}"
    original_url = environment['PR_URL']
    base_ref, head_ref = preview_refs(number, merge_base, head_commit)

    # Forks share one object store, so refs to the PR's commits can be created without pushing anything.
    for ref, sha in ((base_ref, merge_base), (head_ref, head_commit)):
        gh_api(
            environment, '--method', 'POST', f'repos/{repository}/git/refs',
            payload={'ref': f'refs/heads/{ref}', 'sha': sha}, allow_status=('Reference already exists',),
        )

    owner = repository.split('/', 1)[0]
    existing = gh_api(
        environment,
        f'repos/{repository}/pulls?state=open&head={owner}:{head_ref}&base={base_ref}',
    ) or []
    marker = f'<!-- external-review-preview:{number}:{head_commit} -->'
    if existing:
        pull = existing[0]
    else:
        title = environment.get('PR_TITLE', '').strip() or original
        pull = gh_api(
            environment, '--method', 'POST', f'repos/{repository}/pulls',
            payload={
                'title': f'[review preview] {title}'[:250],
                'head': head_ref,
                'base': base_ref,
                'body': (
                    f'Preview of the review for {original_url} ({original}).\n\n'
                    'The diff is the same as the original PR. The review below is not posted upstream '
                    'until it is approved in Slack.\n\n' + marker
                ),
            },
        )
    number_in_fork = pull['number']

    reviews = gh_api(environment, f'repos/{repository}/pulls/{number_in_fork}/reviews?per_page=100') or []
    posted = next((item for item in reviews if marker in (item.get('body') or '')), None)
    if posted is None:
        # A PR authored by the token owner can only receive plain comment reviews.
        posted = gh_api(
            environment, '--method', 'POST', f'repos/{repository}/pulls/{number_in_fork}/reviews',
            payload={
                'commit_id': head_commit,
                'event': 'COMMENT',
                'body': f"Preview of the review for {original} (would be posted as {review['event']}).\n\n"
                        + (review.get('body') or '') + '\n\n' + marker,
                'comments': review.get('comments') or [],
            },
        )
    return {
        'preview_pr_url': pull['html_url'],
        'preview_pr_number': number_in_fork,
        'preview_review_url': posted.get('html_url', ''),
        'preview_repository': repository,
        'base_ref': base_ref,
        'head_ref': head_ref,
    }


def close_review_preview(environment=None):
    """Closes the preview PR and deletes its two branches; safe to run again."""
    environment = os.environ if environment is None else environment
    repository = check_repository(environment['PREVIEW_REPOSITORY'])
    number = (environment.get('PREVIEW_PR_NUMBER') or '').strip()
    outcome = {
        'rejected': 'discarded',
        'no_response': 'not answered in time',
        'published_as_comment': 'published as a comment review',
    }.get(environment.get('OUTCOME', ''), environment.get('OUTCOME') or 'finished')
    if number:
        pull = gh_api(environment, f'repos/{repository}/pulls/{int(number)}')
        if pull.get('state') == 'open':
            gh_api(
                environment, '--method', 'POST', f'repos/{repository}/issues/{int(number)}/comments',
                payload={'body': f'Closing the preview: the review was {outcome}.'},
            )
            gh_api(
                environment, '--method', 'PATCH', f'repos/{repository}/pulls/{int(number)}',
                payload={'state': 'closed'},
            )
    for ref in (environment.get('BASE_REF', ''), environment.get('HEAD_REF', '')):
        if ref.startswith('review-preview/'):
            gh_api(
                environment, '--method', 'DELETE', f'repos/{repository}/git/refs/heads/{ref}',
                allow_status=('Reference does not exist', 'Not Found'),
            )
    return {'closed': bool(number), 'outcome': outcome}

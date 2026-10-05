import json
import os
import re

from fetch_issue_candidates import gh_api

REF_PATTERNS = (
    re.compile(r'^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/issues/(\d+)/?$'),
    re.compile(r'^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)#(\d+)$'),
)


def parse_issue_ref(ref, default_repo):
    ref = str(ref or '').strip()
    short = re.fullmatch(r'#?(\d+)', ref)
    if short:
        owner, repo = default_repo.split('/')
        return owner, repo, int(short.group(1))
    for pattern in REF_PATTERNS:
        match = pattern.fullmatch(ref)
        if match:
            return match.group(1), match.group(2), int(match.group(3))
    return None


def fetch_linked_issues(environment=None):
    environment = os.environ if environment is None else environment
    default_repo = environment.get('DEFAULT_REPO', 'elastic/kibana')
    allowed = {repo.lower() for repo in json.loads(environment.get('ALLOWED_REPOS_JSON', '[]'))}
    max_issues = int(environment.get('MAX_ISSUES', '5'))
    max_body_chars = int(environment.get('MAX_BODY_CHARS', '6000'))
    max_comments = int(environment.get('MAX_COMMENTS', '5'))
    max_comment_chars = int(environment.get('MAX_COMMENT_CHARS', '1500'))

    refs = [item.get('ref') for item in json.loads(environment.get('CLOSING_ISSUES_JSON', '[]'))]
    for finding in json.loads(environment.get('AGENT_FINDINGS_JSON', '[]')):
        if isinstance(finding, dict):
            refs.append(finding.get('issue_ref'))
        elif isinstance(finding, str):
            refs.append(finding)

    issues = []
    skipped = []
    seen = set()
    for ref in refs:
        parsed = parse_issue_ref(ref, default_repo)
        if parsed is None:
            skipped.append({'ref': ref, 'reason': 'unparseable'})
            continue
        owner, repo, number = parsed
        key = f'{owner}/{repo}#{number}'.lower()
        if key in seen:
            continue
        seen.add(key)
        if f'{owner}/{repo}'.lower() not in allowed:
            skipped.append({'ref': ref, 'reason': 'repository_not_allowed'})
            continue
        if len(issues) >= max_issues:
            skipped.append({'ref': ref, 'reason': 'max_issues_reached'})
            continue

        print(f'Fetching issue {owner}/{repo}#{number}', flush=True)
        try:
            issue = gh_api(environment, owner, f'repos/{owner}/{repo}/issues/{number}')
            if issue.get('pull_request'):
                skipped.append({'ref': ref, 'reason': 'is_pull_request'})
                continue
            comments = gh_api(
                environment, owner,
                f'repos/{owner}/{repo}/issues/{number}/comments?per_page={max_comments}',
            ) if issue.get('comments') else []
        except RuntimeError as error:
            print(f'Skipping {owner}/{repo}#{number}: {str(error)[:300]}', flush=True)
            skipped.append({'ref': ref, 'reason': 'fetch_failed'})
            continue
        issues.append({
            'ref': f'{owner}/{repo}#{number}',
            'title': issue.get('title', ''),
            'url': issue.get('html_url', ''),
            'state': issue.get('state', ''),
            'labels': [label.get('name') for label in issue.get('labels', [])],
            'body': (issue.get('body') or '')[:max_body_chars],
            'comments': [
                {
                    'author': (comment.get('user') or {}).get('login'),
                    'body': (comment.get('body') or '')[:max_comment_chars],
                }
                for comment in comments[:max_comments]
            ],
        })

    return {'issues': issues, 'skipped': skipped}

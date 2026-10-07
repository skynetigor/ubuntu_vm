import json
import os
import re
import urllib.parse
from datetime import datetime, timedelta, timezone

from my_open_prs import check_repository, github, is_queued_for_merge

STATE_PATH = '/opt/kibana-cache/team-review-state.json'


def read_state():
    try:
        with open(STATE_PATH, encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def fetch_reviews(environment, repository, number):
    """All reviews of a PR, oldest first."""
    reviews, page = [], 1
    while True:
        batch = github(environment, f'/repos/{repository}/pulls/{number}/reviews?per_page=100&page={page}')
        reviews.extend(batch)
        if len(batch) < 100:
            return reviews
        page += 1


def latest_verdicts(reviews):
    """Each reviewer's latest approve / request-changes / dismiss verdict, keyed by lowercase login.

    Plain comments and pending drafts never change a verdict.
    """
    verdicts = {}
    for review in reviews:
        login = (review.get('user') or {}).get('login', '').lower()
        if login and review.get('state') in {'APPROVED', 'CHANGES_REQUESTED', 'DISMISSED'}:
            verdicts[login] = review['state']
    return verdicts


def approved_by(environment, repository, number, login):
    """True when the user's latest approve/request-changes/dismiss verdict on the PR is an approval."""
    return latest_verdicts(fetch_reviews(environment, repository, number)).get(login.lower()) == 'APPROVED'


def list_team_prs(environment=None):
    """Open, non-draft PRs by team members (never the token's user) whose head changed since the last review."""
    environment = os.environ if environment is None else environment
    repository = check_repository(environment)
    authors = json.loads(environment['AUTHORS_JSON'])
    me = github(environment, '/user')['login'].lower()
    excluded = {name.lower() for name in json.loads(environment.get('EXCLUDE_AUTHORS_JSON') or '[]')} | {me}
    for name in authors:
        if not re.fullmatch(r'[A-Za-z0-9-]+', name):
            raise ValueError('Invalid author login: ' + name)
    force = environment.get('FORCE', '').lower() == 'true'
    max_prs = max(1, int(environment.get('MAX_PRS') or 10))
    max_age = timedelta(days=int(environment.get('MAX_AGE_DAYS') or 30))
    oldest = datetime.now(timezone.utc) - max_age

    items = {}
    for author in authors:
        if author.lower() in excluded:
            continue
        query = urllib.parse.quote(f'repo:{repository} is:pr is:open draft:false author:{author}')
        found = github(environment, f'/search/issues?q={query}&per_page=100&sort=updated&order=desc')
        for item in found.get('items', []):
            items[item['number']] = item

    state = read_state()
    selected, unchanged, stale, queued, approved = [], [], [], [], []
    for number, item in sorted(items.items(), key=lambda pair: pair[1]['updated_at'], reverse=True):
        updated = datetime.strptime(item['updated_at'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
        if updated < oldest:
            stale.append(number)
            continue
        pull = github(environment, f'/repos/{repository}/pulls/{number}')
        if pull.get('draft') or pull.get('state') != 'open' or pull['user']['login'].lower() in excluded:
            continue
        head_sha = pull['head']['sha']
        # A PR the token's user already approved is never reviewed again, whatever force says.
        if approved_by(environment, repository, number, me):
            approved.append(number)
            continue
        if not force and state.get(f'{repository}#{number}') == head_sha:
            unchanged.append(number)
        elif is_queued_for_merge(environment, repository, number, pull):
            queued.append(number)
        elif len(selected) < max_prs:
            selected.append({
                'number': number,
                'url': pull['html_url'],
                'title': pull['title'],
                'author': pull['user']['login'],
                'head_sha': head_sha,
                'updated_at': item['updated_at'],
            })
    return {
        'prs': selected,
        'candidates': len(items),
        'unchanged': unchanged,
        'stale': stale,
        'queued_for_merge': queued,
        'approved_by_me': approved,
        'excluded_authors': sorted(excluded),
    }


def record_team_pr_reviewed(environment=None):
    """Remember the reviewed head so the next scan skips the PR until it changes."""
    environment = os.environ if environment is None else environment
    repository = check_repository(environment)
    state = read_state()
    state[f"{repository}#{int(environment['PR_NUMBER'])}"] = environment['HEAD_SHA']
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    temporary = STATE_PATH + '.tmp'
    with open(temporary, 'w', encoding='utf-8') as handle:
        json.dump(state, handle, indent=2)
    os.replace(temporary, STATE_PATH)
    return {'number': int(environment['PR_NUMBER']), 'head_sha': environment['HEAD_SHA']}

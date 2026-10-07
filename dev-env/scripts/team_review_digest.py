import json
import os
import re
import urllib.parse
from datetime import datetime, timezone

from format_slack_approval import escape, link
from format_slack_summary import one_line
from list_team_prs import fetch_reviews, latest_verdicts
from my_open_prs import check_repository, github, github_graphql

OVER_A_WEEK = 7
GRAPHQL = (
    'query { repository(owner: "%s", name: "%s") { pullRequest(number: %d) {'
    ' reviewDecision mergeStateStatus isInMergeQueue autoMergeRequest { enabledAt }'
    ' commits(last: 1) { nodes { commit { statusCheckRollup { state } } } } } } }'
)


def parse_time(value):
    return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)


def now(environment):
    return parse_time(environment['NOW']) if environment.get('NOW') else datetime.now(timezone.utc)


def search_prs(environment, query):
    items, page = [], 1
    while page <= 10:
        found = github(environment, f"/search/issues?q={urllib.parse.quote(query)}&per_page=100&page={page}")
        items.extend(found.get('items', []))
        if len(found.get('items', [])) < 100:
            break
        page += 1
    return items


def is_bot(item, bot_authors):
    user = item.get('user') or {}
    login = user.get('login', '')
    return user.get('type') == 'Bot' or login.endswith('[bot]') or login.lower() in bot_authors


def pr_details(environment, repository, number):
    owner, name = repository.split('/')
    data = github_graphql(environment, GRAPHQL % (owner, name, number))
    pull = ((data.get('data') or {}).get('repository') or {}).get('pullRequest') or {}
    commits = (pull.get('commits') or {}).get('nodes') or []
    checks = (((commits[0] if commits else {}).get('commit') or {}).get('statusCheckRollup') or {}).get('state')
    return {
        'review_decision': pull.get('reviewDecision') or '',
        'merge_state': pull.get('mergeStateStatus') or '',
        'checks': checks or '',
        'auto_merge': bool(pull.get('autoMergeRequest')),
        'in_merge_queue': bool(pull.get('isInMergeQueue')),
    }


def team_requested_since(environment, repository, number, team_slug, fallback):
    """When the team's review was last requested; the PR creation time when no event says."""
    since, page = fallback, 1
    while page <= 10:
        events = github(environment, f'/repos/{repository}/issues/{number}/events?per_page=100&page={page}')
        for event in events:
            if event.get('event') == 'review_requested' and (event.get('requested_team') or {}).get('slug') == team_slug:
                since = event['created_at']
        if len(events) < 100:
            break
        page += 1
    return since


def merge_labels(details):
    """Short reasons an approved PR is still open, most important first."""
    state, checks = details['merge_state'], details['checks']
    labels = []
    if state == 'DIRTY':
        labels.append('merge conflicts')
    if checks in {'FAILURE', 'ERROR'}:
        labels.append('checks failing')
    if state == 'BEHIND':
        labels.append('branch behind')
    if not labels:
        if state in {'CLEAN', 'HAS_HOOKS'}:
            labels.append('ready to merge')
        elif state == 'UNSTABLE':
            labels.append('ready to merge, some checks not passing')
        elif checks == 'PENDING':
            labels.append('checks running')
        else:
            labels.append('blocked (reviews or checks)')
    if details['in_merge_queue']:
        labels.append('in merge queue')
    if details['auto_merge']:
        labels.append('auto-merge on')
    return labels


def collect_pending_reviews(environment=None):
    environment = os.environ if environment is None else environment
    repository = check_repository(environment)
    team = environment['TEAM']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', team):
        raise ValueError('TEAM must use org/team format')
    team_slug = team.split('/', 1)[1]
    members = json.loads(environment['AUTHORS_JSON'])
    for member in members:
        if not re.fullmatch(r'[A-Za-z0-9-]+', member):
            raise ValueError('Invalid member login: ' + member)
    member_logins = {member.lower() for member in members}
    bot_authors = {name.lower() for name in json.loads(environment.get('BOT_AUTHORS_JSON') or '[]')}
    max_age_days = int(environment.get('MAX_AGE_DAYS') or 60)
    current = now(environment)
    details_cache = {}

    def details(number):
        if number not in details_cache:
            details_cache[number] = pr_details(environment, repository, number)
        return details_cache[number]

    pending_items = search_prs(
        environment, f'repo:{repository} is:pr is:open draft:false team-review-requested:{team}')
    pending, contributors, bots, stale = [], [], 0, 0
    for item in pending_items:
        if is_bot(item, bot_authors):
            bots += 1
            continue
        if (current - parse_time(item['updated_at'])).days >= max_age_days:
            stale += 1
            continue
        number = item['number']
        # GitHub already counts these as approved, so they belong to the other group.
        if details(number)['review_decision'] == 'APPROVED':
            continue
        verdicts = latest_verdicts(fetch_reviews(environment, repository, number))
        row = {
            'number': number,
            'title': item['title'],
            'url': item['html_url'],
            'author': item['user']['login'],
            'since': team_requested_since(environment, repository, number, team_slug, item['created_at']),
            'approvals': sum(1 for state in verdicts.values() if state == 'APPROVED'),
            'changes_requested': any(state == 'CHANGES_REQUESTED' for state in verdicts.values()),
        }
        # Authors outside the team are contributors whose code owner review (the team) is still outstanding.
        (pending if row['author'].lower() in member_logins else contributors).append(row)

    team_items = {}
    for member in members:
        for item in search_prs(environment, f'repo:{repository} is:pr is:open draft:false author:{member}'):
            team_items[item['number']] = item
    approved = []
    for number, item in team_items.items():
        info = details(number)
        if info['review_decision'] != 'APPROVED':
            continue
        reviews = fetch_reviews(environment, repository, number)
        approvers = {login for login, state in latest_verdicts(reviews).items() if state == 'APPROVED'}
        approved_at = max(
            (review['submitted_at'] for review in reviews
             if review.get('state') == 'APPROVED' and (review.get('user') or {}).get('login', '').lower() in approvers
             and review.get('submitted_at')),
            default=item['updated_at'],
        )
        approved.append({
            'number': number,
            'title': item['title'],
            'url': item['html_url'],
            'author': item['user']['login'],
            'since': approved_at,
            'labels': merge_labels(info),
        })

    pending.sort(key=lambda row: row['since'])
    contributors.sort(key=lambda row: row['since'])
    approved.sort(key=lambda row: row['since'])
    return {
        'pending': pending,
        'contributors': contributors,
        'approved': approved,
        'bot_count': bots,
        'stale_count': stale,
        'repository': repository,
        'team': team,
        'max_age_days': max_age_days,
    }


def days_since(value, current):
    return max(0, (current - parse_time(value)).days)


def age_text(days):
    return 'today' if days == 0 else f'{days}d'


def pr_line(row, detail):
    handle = link('https://github.com/' + row['author'], '@' + row['author'])
    return f"• <{escape(row['url'])}|#{row['number']} {escape(one_line(row['title'], 90))}> by {handle} - {detail}"


def format_review_digest(environment=None):
    environment = os.environ if environment is None else environment
    data = json.loads(environment['DIGEST_JSON'])
    max_listed = max(1, int(environment.get('MAX_LISTED') or 30))
    current = now(environment)
    repository, team = data['repository'], data['team']
    search = f"https://github.com/{repository}/pulls?q=" + urllib.parse.quote(
        f'is:pr is:open draft:false team-review-requested:{team}')

    def section(title, rows, empty, detail):
        lines = [title]
        if not rows:
            return lines + [empty]
        lines += [pr_line(row, detail(row)) for row in rows[:max_listed]]
        if len(rows) > max_listed:
            lines.append(f"• ...and {len(rows) - max_listed} more")
        return lines

    def pending_detail(row):
        days = days_since(row['since'], current)
        parts = [f"waiting {age_text(days)}" + (' :warning:' if days > OVER_A_WEEK else '')]
        parts.append(f"{row['approvals']} approval{'s' if row['approvals'] != 1 else ''}")
        if row['changes_requested']:
            parts.append('changes requested')
        return ', '.join(parts)

    def approved_detail(row):
        days = days_since(row['since'], current)
        return ', '.join([f"approved {age_text(days)}{'' if days == 0 else ' ago'}"] + row['labels'])

    team_name = team.split('/', 1)[1]
    lines = section(
        f":eyes: *Team PRs pending review ({len(data['pending'])})*",
        data['pending'], '_Nothing is waiting for review._', pending_detail)
    lines += [''] + section(
        f":handshake: *Contributor PRs needing {team_name} code owner review ({len(data['contributors'])})*",
        data['contributors'], '_No contributor PRs need our review._', pending_detail)
    notes = []
    if data['bot_count']:
        notes.append(f"{data['bot_count']} automated PRs ({link(search, 'view on GitHub')})")
    if data['stale_count']:
        notes.append(f"{data['stale_count']} with no activity for {data['max_age_days']}+ days")
    if notes:
        lines.append('_Not shown: ' + ', '.join(notes) + '._')
    lines += [''] + section(
        f":white_check_mark: *Approved, not merged yet ({len(data['approved'])})*",
        data['approved'], '_No approved PRs are waiting to merge._', approved_detail)
    return {
        'message': '\n'.join(lines),
        'pending_count': len(data['pending']),
        'contributor_count': len(data['contributors']),
        'approved_count': len(data['approved']),
    }


def run_review_digest(environment=None):
    """Collects both groups and builds the Slack message in one step."""
    environment = os.environ if environment is None else environment
    data = collect_pending_reviews(environment)
    digest = format_review_digest({**environment, 'DIGEST_JSON': json.dumps(data)})
    return {
        **digest,
        'bot_count': data['bot_count'],
        'stale_count': data['stale_count'],
    }

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


def relevance(row):
    """How close a contributor PR is to merging once the team's review is given; higher means more relevant."""
    score = min(row['approvals'], 3) * 2          # others already reviewed it, so the team is the blocker
    score += 2 if row['checks'] == 'SUCCESS' else -2 if row['checks'] in {'FAILURE', 'ERROR'} else 0
    score -= 2 if row['merge_state'] == 'DIRTY' else 0
    score -= 3 if row['changes_requested'] else 0
    return score


def approved_relevance(labels):
    """How actionable an approved PR is: mergeable now beats blocked, conflicted or failing ones."""
    text = ' '.join(labels)
    score = 3 if 'ready to merge' in text else 0
    score -= 2 if 'merge conflicts' in text else 0
    score -= 1 if 'checks failing' in text else 0
    score -= 1 if 'branch behind' in text else 0
    return score


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
            'checks': details(number)['checks'],
            'merge_state': details(number)['merge_state'],
        }
        row['relevance'] = relevance(row)
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
        approved[-1]['relevance'] = approved_relevance(approved[-1]['labels'])

    # Longest waiting first, but PRs already waiting on their author (changes requested) go last.
    pending.sort(key=lambda row: (row['changes_requested'], row['since']))
    contributors.sort(key=lambda row: (-row['relevance'], row['since']))
    # Approved PRs that can be merged right now come first, then the ones with the fewest blockers.
    approved.sort(key=lambda row: (-row['relevance'], row['since']))
    return {
        'pending': pending,
        'contributors': contributors,
        'approved': approved,
        'bot_count': bots,
        'stale_count': stale,
        'repository': repository,
        'team': team,
        'members': members,
        'max_age_days': max_age_days,
    }


FALLBACK_GREETING = 'Good morning, team! :sunrise:'


def pick_intro(environment):
    """Greeting and call to action written by the agent: findings of kind greeting / nudge."""
    greeting, nudge = environment.get('GREETING'), ''
    raw = (environment.get('INTRO_JSON') or '').strip()
    try:
        findings = json.loads(raw) if raw else []
    except ValueError:
        findings = []
    for finding in findings if isinstance(findings, list) else []:
        if isinstance(finding, dict) and finding.get('kind') == 'greeting':
            greeting = finding.get('comment')
        elif isinstance(finding, dict) and finding.get('kind') == 'nudge':
            nudge = finding.get('comment')
    return greeting, nudge


def clean_greeting(raw, limit=220, fallback=FALLBACK_GREETING):
    """Makes generated text safe for the channel: one line, no markup, no pings, bounded length."""
    text = re.sub(r'<[^>]*>', ' ', str(raw or ''))          # no <!channel>, <@user> or links
    text = re.sub(r'[`*_~>@]', '', text)                    # no Slack/Markdown formatting or mentions
    text = re.sub(r'^#+\s+', '', text)                       # no leading Markdown heading (but keep #123)
    text = re.sub(r'\s+', ' ', text).strip().strip('"\'\u201c\u201d')
    if len(text) < 5:
        return fallback
    return escape(text if len(text) <= limit else text[:limit - 1].rstrip() + '\u2026')


def days_since(value, current):
    return max(0, (current - parse_time(value)).days)


def age_text(days):
    return 'today' if days == 0 else f'{days}d'


def pr_line(row, parts):
    """One compact line: linked title, author, then only the short facts worth reading."""
    title = f"<{escape(row['url'])}|#{row['number']} {escape(one_line(row['title'], 60))}>"
    return ' \u00b7 '.join([f"\u2022 {title}", '@' + row['author']] + parts)


def format_review_digest(environment=None):
    environment = os.environ if environment is None else environment
    data = json.loads(environment['DIGEST_JSON'])
    max_team = max(1, int(environment.get('MAX_TEAM_PRS') or 10))
    max_approved = max(1, int(environment.get('MAX_APPROVED_PRS') or 5))
    max_contributors = max(1, int(environment.get('MAX_CONTRIBUTOR_PRS') or 5))
    current = now(environment)
    repository, team = data['repository'], data['team']
    search = f"https://github.com/{repository}/pulls?q=" + urllib.parse.quote(
        f'is:pr is:open draft:false team-review-requested:{team}')
    approved_search = f"https://github.com/{repository}/pulls?q=" + urllib.parse.quote(
        'is:pr is:open review:approved ' + ' '.join('author:' + member for member in data.get('members', [])))

    def age(since, prefix=''):
        days = days_since(since, current)
        text = prefix + age_text(days) if days == 0 else f"{prefix}{days}d"
        return f"*{text}*" if days > OVER_A_WEEK else text

    def section(title, rows, limit, empty, parts, more_url):
        count = len(rows)
        lines = [f"{title} ({limit} of {count})" if count > limit else f"{title} ({count})"]
        if not rows:
            return lines + [empty]
        lines += [pr_line(row, parts(row)) for row in rows[:limit]]
        if count > limit:
            lines.append(f"_+{count - limit} more on {link(more_url, 'GitHub')}_")
        return lines

    def team_parts(row):
        return [age(row['since'])] + (['changes requested'] if row['changes_requested'] else [])

    def contributor_parts(row):
        parts = [age(row['since'])]
        if row['approvals']:
            parts.append(f"{row['approvals']} approval{'s' if row['approvals'] != 1 else ''}")
        if row.get('checks') in {'FAILURE', 'ERROR'}:
            parts.append('checks failing')
        if row.get('merge_state') == 'DIRTY':
            parts.append('conflicts')
        return parts

    def approved_parts(row):
        days = days_since(row['since'], current)
        parts = ['approved ' + ('today' if days == 0 else f'{days}d ago')]
        # Only what stops a merge is worth mentioning; ready-to-merge PRs need no note.
        parts += [label for label in row['labels'] if label in {'merge conflicts', 'checks failing', 'branch behind'}]
        return parts

    greeting_raw, nudge_raw = pick_intro(environment)
    lines = [clean_greeting(greeting_raw)]
    nudge = clean_greeting(nudge_raw, 200, '') if nudge_raw else ''
    if nudge:
        lines.append(nudge)
    lines += [''] + section(
        ':eyes: *Team PRs waiting for review*', data['pending'], max_team,
        '_Nothing is waiting for review._', team_parts, search)
    lines += [''] + section(
        ':handshake: *Contributor PRs for our code owner review*', data['contributors'], max_contributors,
        '_No contributor PRs need our review._', contributor_parts, search)
    lines += [''] + section(
        ':white_check_mark: *Approved, ready for merge*', data['approved'], max_approved,
        '_No approved PRs are waiting to merge._', approved_parts, approved_search)
    notes = []
    if data['bot_count']:
        notes.append(f"{data['bot_count']} bot PRs")
    if data['stale_count']:
        notes.append(f"{data['stale_count']} inactive for {data['max_age_days']}+ days")
    if notes:
        lines += ['', '_Not shown: ' + ', '.join(notes) + '._']
    return {
        'message': '\n'.join(lines),
        'pending_count': len(data['pending']),
        'contributor_count': len(data['contributors']),
        'approved_count': len(data['approved']),
    }


def digest_stats(data, current):
    """Facts about the digest that the intro writer may use; nothing else is available to it."""
    # A PR with changes requested waits on its author, not on reviewers, so it is not the longest wait.
    waiting = [row for row in data['pending'] + data['contributors'] if not row['changes_requested']]
    oldest = min(waiting, key=lambda row: row['since'], default=None)
    ready = [row for row in data['approved'] if 'ready to merge' in row['labels']]
    easy = data['contributors'][0] if data['contributors'] and data['contributors'][0]['relevance'] >= 4 else None
    return {
        'weekday': current.strftime('%A'),
        'team_prs_waiting': len(data['pending']),
        'contributor_prs_waiting': len(data['contributors']),
        'approved_not_merged': len(data['approved']),
        'ready_to_merge': len(ready),
        'longest_wait_days': days_since(oldest['since'], current) if oldest else 0,
        'longest_wait_pr': oldest['number'] if oldest else None,
        'easy_win_pr': easy['number'] if easy else None,
        'easy_win_approvals': easy['approvals'] if easy else None,
    }


def collect_digest(environment=None):
    """Collects both groups and the facts used for the intro."""
    environment = os.environ if environment is None else environment
    data = collect_pending_reviews(environment)
    return {'data': data, 'stats': digest_stats(data, now(environment))}


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

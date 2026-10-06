import json
import os
import re

from format_slack_approval import escape, github_markdown_to_slack, link, short_url_label

MAX_MESSAGE_CHARS = 3500
MAX_LISTED_ITEMS = 8


def load(environment, name, default):
    raw = (environment.get(name) or '').strip()
    if not raw:
        return default
    try:
        value = json.loads(raw)
    except ValueError:
        return default
    return default if value is None else value


def one_line(text, limit):
    text = re.sub(r'\s+', ' ', str(text or '')).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def describe(item):
    """Short label for a finding, test or UI result whose exact shape depends on the phase."""
    if isinstance(item, str):
        return escape(one_line(item, 160))
    if not isinstance(item, dict):
        return escape(one_line(json.dumps(item), 160))
    for key in ('comment', 'title', 'summary', 'description', 'project', 'id', 'name'):
        if item.get(key):
            label = escape(one_line(item[key], 160))
            break
    else:
        label = escape(one_line(json.dumps(item), 160))
    path = item.get('file') or item.get('path')
    where = ''
    if path:
        where = os.path.basename(str(path)) + (f":{item['line']}" if item.get('line') else '')
        where = f'`{escape(where)}` '
    severity = f"_{escape(str(item['severity']))}_ " if item.get('severity') else ''
    url = item.get('comment_url')
    text = f'{severity}{where}{label}'
    return f'{text} (<{escape(url)}|PR comment>)' if url else text


def bullets(items):
    lines = [f'• {describe(item)}' for item in items[:MAX_LISTED_ITEMS]]
    if len(items) > MAX_LISTED_ITEMS:
        lines.append(f'• …and {len(items) - MAX_LISTED_ITEMS} more')
    return lines


def publish_line(env):
    publish = env['publish_status']
    fix_pr_url = env['fix_pr_url']
    fix_pr = link(fix_pr_url, 'fix PR ' + short_url_label(fix_pr_url)) if fix_pr_url else ''
    if env['dry_run']:
        return 'Dry run: nothing was published.'
    if env['merge_status'] == 'merged':
        who = f" by {escape(env['approved_by'])}" if env['approved_by'] else ''
        return f'{fix_pr} approved{who} and squash-merged.'
    if fix_pr_url:
        status = {'rejected': 'rejected', 'no_response': 'got no response'}.get(
            env['approval_status'], f"is {env['approval_status']}")
        return f'{fix_pr} {status}; it is still open and was not merged.'
    return {
        'no_changes': 'No code changes to publish.',
        'not_pr': 'Not a pull request, so nothing was published.',
        'blocked_unresolved': 'Not published: unresolved findings remain.',
    }.get(publish, f'Publish status: {escape(publish)}.')


def format_slack_summary(environment=None):
    environment = os.environ if environment is None else environment
    pr = load(environment, 'PR_CONTEXT_JSON', {})
    public_url = environment['PUBLIC_URL'].rstrip('/')
    execution_url = f"{public_url}/app/workflows/review-and-fix-kibana-pr?executionId={environment['EXECUTION_ID']}"
    target = environment.get('KIBANA_TARGET', '')
    if pr.get('number'):
        pr_label = f"{pr['owner']}/{pr['repo']}#{pr['number']}"
        pr_url = f"https://github.com/{pr['owner']}/{pr['repo']}/pull/{pr['number']}"
    else:
        pr_label, pr_url = short_url_label(target) if target else 'target', target

    lists = {
        name: load(environment, name.upper() + '_JSON', [])
        for name in (
            'fixed_agent_comments', 'fixed_pr_comments', 'fixed_tests', 'fixed_ui_findings',
            'remaining_agent_comments', 'remaining_pr_comments', 'remaining_tests',
            'remaining_ui_findings', 'remaining_lint_failures', 'lint_fixed_files',
            'test_fixed', 'test_remaining_failed',
        )
    }
    fixed_tests = lists['fixed_tests'] or lists['test_fixed']
    remaining_tests = lists['remaining_tests'] or lists['test_remaining_failed']
    remaining = {
        'review findings': lists['remaining_agent_comments'],
        'PR comments': lists['remaining_pr_comments'],
        'failing tests': remaining_tests,
        'lint errors': lists['remaining_lint_failures'],
        'UI findings': lists['remaining_ui_findings'],
    }
    open_total = sum(len(v) for v in remaining.values())
    env = {
        'publish_status': environment.get('PUBLISH_STATUS', ''),
        'fix_pr_url': environment.get('FIX_PR_URL', '').strip(),
        'approval_status': environment.get('APPROVAL_STATUS', ''),
        'approved_by': environment.get('APPROVED_BY', '').strip(),
        'merge_status': environment.get('MERGE_STATUS', ''),
        'dry_run': environment.get('DRY_RUN', '').lower() == 'true',
    }
    needs_work = environment.get('NEEDS_WORK', '').lower() == 'true' or open_total > 0
    headline = ':warning: Needs work' if needs_work else ':white_check_mark: Clean'
    user_id = environment.get('SLACK_USER_ID', '').strip()
    # Only a run that left work behind needs an action from the reviewer, so only then is the reviewer pinged.
    mention = f'<@{user_id}> ' if needs_work and re.fullmatch(r'[UW][A-Z0-9]+', user_id) else ''

    lines = [
        f"{mention}*Review and fix finished* for {link(pr_url, pr_label)} - {headline}",
        f"{link(execution_url, 'Open the execution')}"
        f" | rounds: {escape(environment.get('ROUNDS', '?'))}"
        f" | test rounds: {escape(environment.get('TEST_ROUNDS', '?'))}",
        '',
        '*Fixed*',
        f"• review findings: {len(lists['fixed_agent_comments'])} | PR comments: {len(lists['fixed_pr_comments'])}"
        f" | failing test projects: {len(fixed_tests)} | UI findings: {len(lists['fixed_ui_findings'])}"
        f" | files auto-fixed by lint: {len(lists['lint_fixed_files'])}",
    ]
    detail = lists['fixed_agent_comments'] + lists['fixed_pr_comments'] + fixed_tests + lists['fixed_ui_findings']
    lines += bullets(detail)

    lines += ['', '*Still open*']
    if open_total:
        for label, items in remaining.items():
            if items:
                lines.append(f'• {label}: {len(items)}')
                lines += ['  ' + line for line in bullets(items)[:3]]
    else:
        lines.append('• Nothing')

    lines += ['', '*Published*', f"• {publish_line(env)}"]
    resolution = environment.get('COMMENT_RESOLUTION_STATUS', '')
    counts = (load(environment, 'COMMENT_RESOLUTION_RESULT_JSON', {}) or {}).get('counts') or {}
    if resolution and resolution != 'not_created':
        replied = counts.get('replied_and_resolved', 0)
        lines.append(f"• PR comment replies: {escape(resolution)} ({replied} replied and resolved)")
    test_publish = environment.get('TEST_FIX_PUBLISH_STATUS', '')
    test_pr_url = environment.get('TEST_FIX_PR_URL', '').strip()
    if test_pr_url:
        lines.append(
            f"• Test fixes: {link(test_pr_url, 'test fix PR ' + short_url_label(test_pr_url))}"
            f" - approval {escape(environment.get('TEST_FIX_APPROVAL_STATUS', ''))},"
            f" merge {escape(environment.get('TEST_FIX_MERGE_STATUS', ''))}"
        )
    elif test_publish:
        lines.append(f"• Test fixes: {escape(test_publish.replace('_', ' '))}")

    summary = github_markdown_to_slack(environment.get('RUN_SUMMARY', '').strip())
    message = '\n'.join(lines)
    room = MAX_MESSAGE_CHARS - len(message) - len('\n\n*Agent summary*\n') - len('\n...')
    if summary and room > 200:
        if len(summary) > room:
            summary = summary[:room].rsplit('\n', 1)[0] + '\n...'
            if summary.count('```') % 2:
                summary += '\n```'
        message += '\n\n*Agent summary*\n' + summary
    return {'message': message[:MAX_MESSAGE_CHARS + 200], 'execution_url': execution_url}

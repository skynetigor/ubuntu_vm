import json
import os
import re


def escape(text):
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def short_url_label(url):
    pull = re.match(r'https?://github\.com/([^/]+/[^/]+)/(?:pull|issues)/(\d+)', url)
    if pull:
        return f'{pull.group(1)}#{pull.group(2)}'
    label = re.sub(r'^https?://(www\.)?', '', url).rstrip('/')
    return label if len(label) <= 60 else label[:57] + '...'


def convert_line(line):
    """Escapes one prose line and turns every link, markdown or bare, into <url|text>."""
    held = []

    def hold(value):
        held.append(value)
        return f'\x00{len(held) - 1}\x00'

    line = re.sub(r'`[^`]*`', lambda m: hold(escape(m.group(0))), line)
    line = re.sub(
        r'\[([^\]]+)\]\((https?://[^)\s]+)\)',
        lambda m: hold(f'<{escape(m.group(2))}|{escape(m.group(1))}>'), line,
    )
    line = re.sub(
        r'<(https?://[^>\s|]+)>',
        lambda m: hold(f'<{escape(m.group(1))}|{escape(short_url_label(m.group(1)))}>'), line,
    )
    line = re.sub(
        r'https?://[^\s<>)\]]+',
        lambda m: hold(f"<{escape(m.group(0).rstrip('.,;:'))}|{escape(short_url_label(m.group(0).rstrip('.,;:')))}>")
        + m.group(0)[len(m.group(0).rstrip('.,;:')):],
        line,
    )
    line = escape(line)
    line = re.sub(r'^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$', r'*\1*', line)
    line = re.sub(r'^(\s*)[-*+]\s+', r'\1• ', line)
    line = re.sub(r'(\*\*|__)(.+?)\1', r'*\2*', line)
    line = re.sub(r'~~(.+?)~~', r'~\1~', line)
    return re.sub(r'\x00(\d+)\x00', lambda m: held[int(m.group(1))], line)


def github_markdown_to_slack(markdown):
    """Converts GitHub-flavored Markdown to Slack mrkdwn; fenced code is left untouched."""
    lines, in_code = [], False
    for line in markdown.splitlines():
        if line.lstrip().startswith('```'):
            in_code = not in_code
            lines.append('```')
        elif in_code:
            lines.append(escape(line))
        else:
            lines.append(convert_line(line))
    return '\n'.join(lines)


def link(url, label):
    return f'<{url}|{escape(label)}>' if url else escape(label)


def format_slack_approval(environment=None):
    environment = os.environ if environment is None else environment
    pr = json.loads(environment['PR_CONTEXT_JSON'])
    public_url = environment['PUBLIC_URL'].rstrip('/')
    owner, repo, number = pr['owner'], pr['repo'], pr['number']
    pr_label = f'{owner}/{repo}#{number}'
    pr_url = f'https://github.com/{owner}/{repo}/pull/{number}'
    fix_pr_url = environment.get('FIX_PR_URL', '').strip()
    execution_url = f"{public_url}/app/workflows/{environment['WORKFLOW_ID']}?executionId={environment['EXECUTION_ID']}"
    parent_id = environment.get('PARENT_EXECUTION_ID', '').strip()
    parent_workflow = environment.get('PARENT_WORKFLOW_ID', '').strip()
    parent_url = f'{public_url}/app/workflows/{parent_workflow}?executionId={parent_id}' if parent_id and parent_workflow else ''

    user_id = environment.get('SLACK_USER_ID', '').strip()
    handle = environment.get('SLACK_HANDLE', '').strip().lstrip('@')
    mention = f'<@{user_id}>' if re.fullmatch(r'[UW][A-Z0-9]+', user_id) else (f'@{handle}' if handle else '')

    note = escape(environment.get('APPROVAL_NOTE', '').strip())
    body = github_markdown_to_slack(environment.get('FIX_PR_BODY', '')[:6000])
    parts = [
        f"{mention} Approval needed to merge the fix PR for {link(pr_url, pr_label)}.".strip(),
        '',
        f'*Review fixes for {link(pr_url, pr_label)}*',
        '',
        f"*Fix PR:* {link(fix_pr_url, 'fix PR ' + short_url_label(fix_pr_url)) if fix_pr_url else 'not created'}",
        f"*Branch:* `{environment.get('FIX_BRANCH', '')}` into `{environment.get('BASE_BRANCH', '')}`",
        f"*Commit:* `{environment.get('COMMIT_SHA', '')}`",
        f"*Approval (sub-workflow {environment['WORKFLOW_ID']}):* {link(execution_url, 'open the execution waiting for approval')}",
    ]
    if parent_url:
        parts.append(f"*Main workflow ({parent_workflow}):* {link(parent_url, 'open the review-and-fix execution')}")
    parts += ['', note, '', '---', '', body]
    return {'message': '\n'.join(parts).strip(), 'execution_url': execution_url}

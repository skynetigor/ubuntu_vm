import json
import os
import re

from format_slack_approval import escape, link
from format_slack_summary import one_line

MAX_MESSAGE_CHARS = 2900
EVENT_LABEL = {'APPROVE': 'an approving review', 'REQUEST_CHANGES': 'a review requesting changes', 'COMMENT': 'a comment review'}


def load(environment, name, default):
    raw = (environment.get(name) or '').strip()
    if not raw:
        return default
    value = json.loads(raw)
    return default if value is None else value


def describe_pr(environment, pr_summary_label='What the PR does'):
    pr = load(environment, 'PR_JSON', {})
    label = f"{pr['owner']}/{pr['repo']}#{pr['number']}"
    title = one_line(environment.get('PR_TITLE', ''), 120)
    author = environment.get('PR_AUTHOR', '').strip()
    head = f"{link(environment['PR_URL'], label)} {escape(title)}".strip()
    if author:
        head += f" by {link('https://github.com/' + author, '@' + author)}"
    summary = escape(one_line(environment.get('PR_SUMMARY', '') or title, 700))
    return head, f'*{pr_summary_label}*\n{summary}'


def comment_line(finding):
    where = ''
    if finding.get('file'):
        where = f"`{escape(os.path.basename(str(finding['file'])))}" + (f":{finding['line']}" if finding.get('line') else '') + '` '
    severity = f"_{escape(str(finding.get('severity', 'low')))}_ "
    return f"• {severity}{where}{escape(one_line(finding.get('comment', ''), 230))}"


def format_external_review_slack(environment=None):
    environment = os.environ if environment is None else environment
    mode = environment.get('MODE', 'approval')
    head, about = describe_pr(environment)
    dropped = int(environment.get('DROPPED_COUNT') or 0)
    dropped_note = f"\n_{dropped} candidate finding{'s' if dropped != 1 else ''} dropped as unverified._" if dropped else ''
    execution = environment.get('EXECUTION_URL', '').strip()
    execution_line = f"\n{link(execution, 'Open the workflow execution')}" if execution else ''

    if mode == 'no_comments':
        message = f":white_check_mark: Reviewed {head} - no comments found.\n\n{about}{dropped_note}{execution_line}"
        return {'message': message}

    if mode == 'clean_approval':
        mention_id = environment.get('SLACK_USER_ID', '').strip()
        mention = f'<@{mention_id}> ' if re.fullmatch(r'[UW][A-Z0-9]+', mention_id) else ''
        approval_message = one_line(re.sub(r'<!--.*?-->', '', environment.get('APPROVAL_MESSAGE', ''), flags=re.S), 300)
        message = (
            f"{mention}:white_check_mark: Reviewed {head} - *no comments found*.\n\n{about}\n\n"
            f"Approving posts an approval review on the PR with this message:\n_{escape(approval_message)}_\n"
            f"Skip leaves the PR alone.{dropped_note}{execution_line}"
        )
        return {'message': message}

    if mode == 'outcome':
        outcome = environment.get('OUTCOME', '')
        review_url = environment.get('REVIEW_URL', '').strip()
        clean = environment.get('KIND', '') == 'clean'
        text = {
            'published': (f"Approval posted on {head}" if clean else f"Review published on {head}") + (f" - {link(review_url, 'open the review')}" if review_url else ''),
            'published_as_comment': f"Review published on {head} as a comment review" + (f" - {link(review_url, 'open the review')}" if review_url else ''),
            'rejected': (f"Approval of {head} was skipped; nothing was posted." if clean
                         else f"Review for {head} was discarded; nothing was posted."),
            'no_response': f"No answer for the review of {head}; nothing was posted.",
            'head_moved': f"Review for {head} was not posted: the PR changed after the review.",
            'already_published': f"Review for {head} was already published earlier.",
        }.get(outcome, f"Review for {head}: {escape(outcome)}.")
        return {'message': text}

    findings = load(environment, 'FINDINGS_JSON', [])
    mention_id = environment.get('SLACK_USER_ID', '').strip()
    mention = f'<@{mention_id}> ' if re.fullmatch(r'[UW][A-Z0-9]+', mention_id) else ''
    preview_url = environment.get('PREVIEW_PR_URL', '').strip()
    event = environment.get('EVENT', 'COMMENT')
    lines = [
        f"{mention}*Review ready to publish* for {head}",
        '',
        about,
        '',
        f"Approving posts {EVENT_LABEL.get(event, 'a review')} with {len(findings)} comment{'s' if len(findings) != 1 else ''} on the PR.",
        (f"Check the comments first in the {link(preview_url, 'preview PR in your fork')}." if preview_url
         else '_The preview PR could not be created, so the comments are listed below only._'),
    ]
    tail = f'{dropped_note}{execution_line}'
    header = '\n'.join(lines)
    budget = MAX_MESSAGE_CHARS - len(header) - len(tail) - len('\n\n*Comments to publish*\n') - 40
    items, used = [], 0
    for finding in findings:
        line = comment_line(finding)
        if used + len(line) + 1 > budget:
            items.append(f'• ...and {len(findings) - len(items)} more (see the preview PR)')
            break
        items.append(line)
        used += len(line) + 1
    message = header + '\n\n*Comments to publish*\n' + '\n'.join(items) + tail
    return {'message': message}

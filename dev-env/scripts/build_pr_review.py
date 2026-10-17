import difflib
import json
import os
import re
import subprocess

SEVERITY_ORDER = ['critical', 'high', 'medium', 'low', 'nit', 'opinionated']
BLOCKING_SEVERITIES = {'critical', 'high'}
HUNK_HEADER = re.compile(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@')


def commentable_lines(merge_base, head_commit, path):
    diff = subprocess.run(
        ['git', 'diff', '--no-ext-diff', '--unified=3', merge_base, head_commit, '--', path],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120, check=True,
    ).stdout
    lines = set()
    new_line = None
    for row in diff.splitlines():
        header = HUNK_HEADER.match(row)
        if header:
            new_line = int(header.group(1))
            continue
        if new_line is None or row.startswith('\\'):
            continue
        if row.startswith('+') or row.startswith(' '):
            lines.add(new_line)
            new_line += 1
    return lines


PRIORITY_SEVERITY = {'0': 'critical', '1': 'high', '2': 'medium', '3': 'low'}
NAMED_SEVERITY = {'critical': 'critical', 'high': 'high', 'medium': 'medium', 'low': 'low'}
PRIORITY_HEADER = re.compile(r'Severity:\s*P(\d)\s*(?:\((\w+)\))?', re.I)
# A problem of this severity that is still open keeps the PR from being approvable.
BLOCKING_OPEN_SEVERITIES = {'critical', 'high', 'medium'}
SEVERITY_RANK = {name: index for index, name in enumerate(SEVERITY_ORDER)}


def severity_hint(body):
    """Severity written in a comment by a review bot ("Severity: P1 (High)"); None for plain comments."""
    match = PRIORITY_HEADER.search(str(body or ''))
    if not match:
        return None
    return NAMED_SEVERITY.get((match.group(2) or '').lower()) or PRIORITY_SEVERITY.get(match.group(1))


def comment_gist(body, limit=180):
    text = re.sub(r'\*\*Severity:[^*]*\*\*', ' ', str(body or ''))
    text = re.sub(r'<!--.*?-->', ' ', text, flags=re.S)
    return ' '.join(text.split())[:limit]


def build_open_items(existing_comments, duplicates, thread_checks):
    """What is still open on the PR: unresolved review threads the agent re-checked against the current code.

    A thread the agent says is no longer a problem is left out. A problem the agent confirmed in the current code
    stays in even if its thread was resolved, because the code still has it.
    """
    roots = {c.get('thread_id') or c['id']: c for c in existing_comments if not c.get('in_reply_to_id')}
    thread_of = {c['id']: c.get('thread_id') or c['id'] for c in existing_comments}
    checks = {}
    for check in thread_checks:
        key = thread_of.get(check.get('existing_comment_id'))
        if key is not None:
            checks[key] = check
    confirmed = {}
    for item in duplicates:
        key = thread_of.get(item.get('existing_comment_id'))
        if key is not None:
            confirmed[key] = item

    items = []
    for key, root in roots.items():
        resolved = root.get('is_resolved') is True
        check, dup = checks.get(key), confirmed.get(key)
        verified_problem = bool(dup) or bool(check and check.get('still_a_problem') is True and check.get('grounded', True))
        if check and check.get('still_a_problem') is False and not dup:
            continue
        if resolved and not verified_problem:
            continue
        severity = (dup or {}).get('severity') or (check or {}).get('severity') or severity_hint(root.get('body'))
        severity = str(severity).lower() if severity else None
        items.append({
            'comment_id': root['id'],
            'url': root.get('url') or root.get('comment_url'),
            'file': root.get('path'),
            'line': root.get('line'),
            'author': root.get('author'),
            'severity': severity if severity in SEVERITY_RANK else None,
            'status': 'confirmed' if verified_problem else 'unverified',
            'thread_resolved': resolved,
            'note': comment_gist((dup or {}).get('comment') or (check or {}).get('comment') or root.get('body')),
        })
    # Confirmed problems that matched no thread (similar wording without an id) still count.
    for item in duplicates:
        if thread_of.get(item.get('existing_comment_id')) in roots:
            continue
        items.append({
            'comment_id': item.get('existing_comment_id'), 'url': None, 'file': item.get('file'),
            'line': item.get('line'), 'author': None, 'severity': item.get('severity'),
            'status': 'confirmed', 'thread_resolved': False, 'note': comment_gist(item.get('comment')),
        })
    items.sort(key=lambda i: SEVERITY_RANK.get(i['severity'], len(SEVERITY_ORDER)))
    return items


def format_finding(finding):
    comment = finding['comment']
    if finding['severity'] == 'nit' and not comment.lower().startswith('nit'):
        comment = 'nit: ' + comment
    return comment


def normalize_text(text):
    return ' '.join(re.sub(r'<!--.*?-->', ' ', str(text or ''), flags=re.S).lower().split())


def is_already_posted(finding, existing_comments, existing_review_bodies):
    comment = normalize_text(format_finding(finding))
    for existing in existing_comments:
        if existing.get('path') != finding['file']:
            continue
        line = existing.get('line')
        if finding['line'] and isinstance(line, int) and abs(line - finding['line']) > 5:
            continue
        body = normalize_text(existing.get('body'))
        if comment in body or difflib.SequenceMatcher(None, comment, body).ratio() >= 0.8:
            return True
    return any(comment in body for body in existing_review_bodies)


def build_pr_review(environment=None):
    environment = os.environ if environment is None else environment
    findings = json.loads(environment.get('FINDINGS_JSON') or '[]') or []
    # An empty value (input not passed by a caller) falls back to every severity worth publishing.
    publish_severities = set(json.loads(environment.get('PUBLISH_SEVERITIES') or '["critical", "high", "medium", "low"]'))
    merge_base = environment['MERGE_BASE']
    head_commit = environment['HEAD_COMMIT']
    for sha in (merge_base, head_commit):
        if not re.fullmatch(r'[0-9a-f]{40}', sha):
            raise ValueError('MERGE_BASE and HEAD_COMMIT must be full commit SHAs')
    production_files = set(json.loads(environment.get('PRODUCTION_FILES_JSON') or '[]'))
    existing_pr = json.loads(environment.get('EXISTING_PR_CONTEXT_JSON') or '{}') or {}
    existing_comments = existing_pr.get('comments') or []
    existing_review_bodies = [normalize_text(review.get('body')) for review in existing_pr.get('reviews') or []]
    max_inline = int(environment.get('MAX_INLINE_COMMENTS', '50'))
    marker = f'<!-- kibana-agent-review:{head_commit} -->'

    normalized = []
    review_note = ''
    pr_summary = ''
    thread_checks = []
    agent_verdict = None
    for finding in findings:
        if isinstance(finding, dict) and finding.get('kind') == 'thread_check':
            thread_checks.append(finding)
            continue
        if isinstance(finding, dict) and finding.get('kind') == 'approval':
            agent_verdict = {
                'approvable': finding.get('approvable') if isinstance(finding.get('approvable'), bool) else None,
                'reason': str(finding.get('reason') or '').strip(),
            }
            continue
        if isinstance(finding, dict) and finding.get('kind') == 'pr_summary':
            pr_summary = str(finding.get('comment') or '').strip()
            continue
        if isinstance(finding, dict) and finding.get('kind') == 'review_body':
            review_note = str(finding.get('comment') or '').strip()
            continue
        if not isinstance(finding, dict) or not finding.get('comment'):
            continue
        severity = str(finding.get('severity', 'low')).lower()
        line = finding.get('line')
        normalized.append({
            'severity': severity if severity in SEVERITY_ORDER else 'low',
            'comment': str(finding['comment']).strip(),
            'file': finding.get('file'),
            'line': line if isinstance(line, int) and line > 0 else None,
            'evidence': finding.get('evidence'),
            'already_raised': finding.get('already_raised') is True,
            'existing_comment_id': finding.get('existing_comment_id'),
        })
    normalized.sort(key=lambda item: SEVERITY_ORDER.index(item['severity']))

    # Already-raised findings are never reposted but still decide the verdict while unresolved.
    duplicates = [
        item for item in normalized
        if item['already_raised'] or is_already_posted(item, existing_comments, existing_review_bodies)
    ]
    new_findings = [item for item in normalized if item not in duplicates]

    # Blocking findings are always published so a change request is never unexplained.
    publishable = [
        item for item in new_findings
        if item['severity'] in publish_severities or item['severity'] in BLOCKING_SEVERITIES
    ]
    excluded = [item for item in new_findings if item not in publishable]
    blocking_count = sum(1 for item in normalized if item['severity'] in BLOCKING_SEVERITIES)

    # Approvable means nothing is left that has to be fixed before merging: no new finding and no open problem of
    # medium severity or higher, and the agent, which saw the whole PR, agrees. A comment review is used otherwise.
    open_items = build_open_items(existing_comments, duplicates, thread_checks)
    blocking_open = [item for item in open_items if item['severity'] in BLOCKING_OPEN_SEVERITIES]
    blocking_new = [item for item in publishable if item['severity'] in BLOCKING_OPEN_SEVERITIES]
    reasons = []
    if blocking_new:
        reasons.append(f"{len(blocking_new)} new finding{'s' if len(blocking_new) != 1 else ''} of medium severity or higher")
    if blocking_open:
        reasons.append(f"{len(blocking_open)} open issue{'s' if len(blocking_open) != 1 else ''} of medium severity or higher")
    agent_says_no = bool(agent_verdict) and agent_verdict['approvable'] is False
    if agent_says_no:
        reasons.insert(0, (agent_verdict['reason'] or 'the reviewer judged it not ready to approve').strip().rstrip('.;'))
    approvable = not reasons
    approval_reason = '; '.join(reasons) if reasons else (
        (agent_verdict or {}).get('reason') or 'Nothing is left to fix before merging.'
    )
    event = 'REQUEST_CHANGES' if blocking_count else ('APPROVE' if approvable else 'COMMENT')

    lines_by_file = {}
    inline_comments = []
    general_findings = []
    for finding in publishable:
        path = finding['file']
        # Only diff lines of reviewed files can carry inline comments; GitHub rejects the whole review otherwise.
        if path in production_files and finding['line'] and len(inline_comments) < max_inline:
            if path not in lines_by_file:
                lines_by_file[path] = commentable_lines(merge_base, head_commit, path)
            if finding['line'] in lines_by_file[path]:
                inline_comments.append({
                    'path': path,
                    'line': finding['line'],
                    'side': 'RIGHT',
                    'body': format_finding(finding),
                })
                continue
        general_findings.append(finding)

    counts = {severity: 0 for severity in SEVERITY_ORDER}
    for finding in publishable:
        counts[finding['severity']] += 1
    count_text = ', '.join(f'{count} {severity}' for severity, count in counts.items() if count)

    body_parts = [review_note] if review_note else []
    if event == 'REQUEST_CHANGES' and not review_note:
        body_parts.append(
            'Left some comments, please take a look before we merge.' if publishable
            else 'The open comments above still need to be addressed before we merge.'
        )
    if general_findings:
        if inline_comments or review_note:
            body_parts.append('A few more things not tied to the changed lines:')
        for finding in general_findings:
            location = f"`{finding['file']}`" + (f" (L{finding['line']})" if finding['line'] else '') if finding['file'] else ''
            body_parts.append(f"- {location + ': ' if location else ''}{format_finding(finding)}")
    if event == 'APPROVE' and not publishable and not review_note:
        body_parts.append('Looks good to me. I went through the production changes and did not find anything to change.')
    body_parts.append(marker)

    preview = [f"**Approvable: {'yes' if approvable else 'no'}** ({approval_reason})",
               f'**Verdict: {event}** ({blocking_count} critical/high findings).',
               f'**{len(publishable)} findings to publish** ({count_text or "none"}); '
               f'{len(inline_comments)} inline, {len(general_findings)} in the review body; '
               f'{len(duplicates)} skipped as already raised.']
    if review_note:
        preview.append(f'\nReview note: {review_note}\n')
    for finding in publishable:
        location = f"{finding['file']}:{finding['line'] or '-'}" if finding['file'] else 'general'
        preview.append(f"- **{finding['severity']}** `{location}` — {finding['comment']}")

    return {
        'review': {
            'commit_id': head_commit,
            'event': event,
            'body': '\n\n'.join(body_parts),
            'comments': inline_comments,
        },
        'event': event,
        'blocking_count': blocking_count,
        'marker': marker,
        'pr_summary': pr_summary,
        'publishable_count': len(publishable),
        'inline_count': len(inline_comments),
        'general_findings': general_findings,
        'publishable_findings': publishable,
        'excluded_findings': excluded,
        'duplicate_findings': duplicates,
        'approvable': approvable,
        'approval_reason': approval_reason,
        'agent_verdict': agent_verdict,
        'open_items': open_items,
        'counts_by_severity': counts,
        'preview_markdown': '\n'.join(preview),
    }

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
    publish_severities = set(json.loads(environment['PUBLISH_SEVERITIES']))
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
    for finding in findings:
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
    event = 'REQUEST_CHANGES' if blocking_count else 'APPROVE'

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
    body_parts.append(marker)

    preview = [f'**Verdict: {event}** ({blocking_count} critical/high findings).',
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
        'publishable_count': len(publishable),
        'inline_count': len(inline_comments),
        'general_findings': general_findings,
        'publishable_findings': publishable,
        'excluded_findings': excluded,
        'duplicate_findings': duplicates,
        'counts_by_severity': counts,
        'preview_markdown': '\n'.join(preview),
    }

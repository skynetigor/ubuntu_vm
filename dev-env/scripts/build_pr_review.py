import json
import os
import re
import subprocess

SEVERITY_ORDER = ['high', 'medium', 'low', 'nit', 'opinionated']
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
    text = f"**{finding['severity'].upper()}**: {finding['comment']}"
    if finding.get('evidence'):
        text += f"\n\n<details><summary>Evidence</summary>\n\n{finding['evidence']}\n\n</details>"
    return text


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
    max_inline = int(environment.get('MAX_INLINE_COMMENTS', '50'))
    marker = f'<!-- kibana-agent-review:{head_commit} -->'

    normalized = []
    for finding in findings:
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
        })
    normalized.sort(key=lambda item: SEVERITY_ORDER.index(item['severity']))

    publishable = [item for item in normalized if item['severity'] in publish_severities]
    excluded = [item for item in normalized if item['severity'] not in publish_severities]

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

    body_parts = [f'### Automated review\n\n{count_text or "No findings"}.']
    if general_findings:
        body_parts.append('#### Findings outside changed lines')
        for finding in general_findings:
            location = f"`{finding['file']}`" + (f":{finding['line']}" if finding['line'] else '') if finding['file'] else 'General'
            body_parts.append(f'- {location} — {format_finding(finding)}')
    body_parts.append(marker)

    preview = [f'**{len(publishable)} findings to publish** ({count_text or "none"}); '
               f'{len(inline_comments)} inline, {len(general_findings)} in the review body.']
    for finding in publishable:
        location = f"{finding['file']}:{finding['line'] or '-'}" if finding['file'] else 'general'
        preview.append(f"- **{finding['severity']}** `{location}` — {finding['comment']}")

    return {
        'review': {
            'commit_id': head_commit,
            'event': 'COMMENT',
            'body': '\n\n'.join(body_parts),
            'comments': inline_comments,
        },
        'marker': marker,
        'publishable_count': len(publishable),
        'inline_count': len(inline_comments),
        'general_findings': general_findings,
        'publishable_findings': publishable,
        'excluded_findings': excluded,
        'counts_by_severity': counts,
        'preview_markdown': '\n'.join(preview),
    }

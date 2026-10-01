import json
import os


def summarize_review(environment=None):
    environment = os.environ if environment is None else environment
    fixable = set(json.loads(environment['FIXABLE_SEVERITIES']))
    code_findings = json.loads(environment.get('CODE_FINDINGS_JSON', '[]'))
    pr_comments = json.loads(environment.get('PR_COMMENTS_JSON', '[]'))
    pr_analysis = json.loads(environment.get('PR_ANALYSIS_JSON', '[]'))
    test_failures = json.loads(environment.get('TEST_FAILURES_JSON', '[]'))

    agent_comments_to_fix = []
    other_agent_comments = []
    pr_comments_to_fix = []
    pr_comments_fixed_locally = []
    other_pr_comments = []

    for finding in code_findings:
        severity = finding.get('severity', 'low')
        comment = finding.get('comment') or finding.get('impact') or finding.get('evidence') or ''
        item = {
            'severity': severity,
            'comment': comment,
            'source': 'code_review',
            'file': finding.get('file'),
            'line': finding.get('line'),
            'evidence': finding.get('evidence'),
        }
        (agent_comments_to_fix if severity in fixable else other_agent_comments).append(item)

    comments_by_id = {str(comment['id']): comment for comment in pr_comments}
    for analysis in pr_analysis:
        comment_id = str(analysis.get('comment_id', ''))
        original = comments_by_id.get(comment_id, {})
        severity = analysis.get('severity', 'low')
        status = analysis.get('status') or ('fixed_in_pr' if analysis.get('already_fixed') is True else 'open')
        comment_url = original.get('comment_url') or original.get('url')
        item = {
            'severity': severity,
            'comment': original.get('body', analysis.get('rationale', '')),
            'source': 'pr_review',
            'comment_id': comment_id,
            'path': original.get('path'),
            'line': original.get('line'),
            'url': comment_url,
            'comment_url': comment_url,
            'status': status,
            'already_fixed': status != 'open',
            'rationale': analysis.get('rationale'),
        }
        if severity in fixable and status == 'open':
            pr_comments_to_fix.append(item)
        elif severity in fixable and status == 'fixed_locally':
            pr_comments_fixed_locally.append(item)
        else:
            other_pr_comments.append(item)

    # The agent typically folds thread replies into the parent comment; keep them visible.
    classified_ids = {str(analysis.get('comment_id', '')) for analysis in pr_analysis}
    for comment in pr_comments:
        comment_id = str(comment['id'])
        if comment_id in classified_ids:
            continue
        comment_url = comment.get('comment_url') or comment.get('url')
        other_pr_comments.append({
            'severity': None,
            'comment': comment.get('body', ''),
            'source': 'pr_review',
            'comment_id': comment_id,
            'in_reply_to_id': comment.get('in_reply_to_id'),
            'path': comment.get('path'),
            'line': comment.get('line'),
            'url': comment_url,
            'comment_url': comment_url,
            'status': 'unclassified',
            'already_fixed': False,
            'rationale': None,
        })

    failed_tests = []
    for failure in test_failures:
        failed_tests.append({
            'project': failure.get('project'),
            'failures': [{key: value for key, value in failure.items() if key != 'project'}],
        })

    return {
        'agent_comments_to_fix': agent_comments_to_fix,
        'other_agent_comments': other_agent_comments,
        'pr_comments_to_fix': pr_comments_to_fix,
        'pr_comments_fixed_locally': pr_comments_fixed_locally,
        'other_pr_comments': other_pr_comments,
        'failed_tests': failed_tests,
        'needs_work': bool(agent_comments_to_fix or pr_comments_to_fix or failed_tests),
    }
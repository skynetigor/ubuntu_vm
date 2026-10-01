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
        already_fixed = analysis.get('already_fixed') is True
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
            'already_fixed': already_fixed,
            'rationale': analysis.get('rationale'),
        }
        (pr_comments_to_fix if severity in fixable and not already_fixed else other_pr_comments).append(item)

    failed_tests = []
    for failure in test_failures:
        failed_tests.append({
            'project': failure.get('project'),
            'failures': [{
                'command': failure.get('command'),
                'exit_code': failure.get('exit_code'),
                'diagnostic': failure.get('diagnostic'),
                'log_path': failure.get('log_path'),
            }],
        })

    return {
        'agent_comments_to_fix': agent_comments_to_fix,
        'other_agent_comments': other_agent_comments,
        'pr_comments_to_fix': pr_comments_to_fix,
        'other_pr_comments': other_pr_comments,
        'failed_tests': failed_tests,
        'needs_work': bool(agent_comments_to_fix or pr_comments_to_fix or failed_tests),
    }
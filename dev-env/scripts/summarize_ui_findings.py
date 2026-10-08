import json
import os

VERDICTS = {'fixed', 'partially_fixed', 'not_fixed', 'not_verifiable'}
DEFAULT_VERDICT_SEVERITY = {'not_fixed': 'high', 'partially_fixed': 'medium'}


def summarize_ui_findings(environment=None):
    environment = os.environ if environment is None else environment
    fixable = set(json.loads(environment['FIXABLE_SEVERITIES']))
    findings = json.loads(environment.get('UI_FINDINGS_JSON') or '[]') or []

    defects = []
    issue_verdicts = []
    environment_problems = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        # The test server or browser itself is broken (UI does not load, login fails, Elasticsearch is down).
        # That says nothing about the change, so it is reported but never handed to a fixing agent.
        if finding.get('kind') == 'environment':
            environment_problems.append({
                'comment': finding.get('comment') or finding.get('evidence') or '',
                'evidence': finding.get('evidence'),
            })
            continue
        if finding.get('kind') == 'issue_verdict':
            verdict = finding.get('verdict')
            issue_verdicts.append({
                'issue': finding.get('issue'),
                'verdict': verdict if verdict in VERDICTS else 'not_verifiable',
                'severity': finding.get('severity'),
                'comment': finding.get('comment', ''),
                'evidence': finding.get('evidence'),
            })
            continue
        defects.append({
            'severity': finding.get('severity', 'low'),
            'comment': finding.get('comment') or finding.get('evidence') or '',
            'source': 'ui_test',
            'issue': finding.get('issue'),
            'file': finding.get('file'),
            'line': finding.get('line'),
            'evidence': finding.get('evidence'),
        })

    # An unresolved issue must stay fixable even when the agent reported no matching defect.
    issues_with_fixable_defects = {
        defect['issue'] for defect in defects if defect['severity'] in fixable and defect['issue']
    }
    for verdict in issue_verdicts:
        default_severity = DEFAULT_VERDICT_SEVERITY.get(verdict['verdict'])
        if not default_severity or verdict['issue'] in issues_with_fixable_defects:
            continue
        severity = verdict['severity'] if verdict['severity'] in fixable else default_severity
        defects.append({
            'severity': severity,
            'comment': verdict['comment'] or f"Change does not resolve {verdict['issue']} ({verdict['verdict']}).",
            'source': 'ui_test',
            'issue': verdict['issue'],
            'file': None,
            'line': None,
            'evidence': verdict['evidence'],
        })

    return {
        'ui_findings_to_fix': [defect for defect in defects if defect['severity'] in fixable],
        'other_ui_findings': [defect for defect in defects if defect['severity'] not in fixable],
        'issue_verdicts': issue_verdicts,
        'environment_problems': environment_problems,
    }

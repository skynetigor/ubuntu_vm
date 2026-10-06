import json
import os
import re
import subprocess

PASSTHROUGH_KINDS = {'review_body', 'pr_summary'}
WINDOW = 4
SEVERITIES = {'critical', 'high', 'medium', 'low', 'nit', 'opinionated'}


def normalize(text):
    return re.sub(r'\s+', ' ', str(text or '')).strip()


def load_json(environment, name, default):
    raw = (environment.get(name) or '').strip()
    if not raw:
        return default
    value = json.loads(raw)
    return default if value is None else value


def read_head_file(head_commit, path):
    result = subprocess.run(
        ['git', 'show', f'{head_commit}:{path}'], text=True, errors='replace',
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
    )
    return result.stdout.splitlines() if result.returncode == 0 else None


def locate_quote(lines, quote, near_line):
    """Returns the 1-based line where the quote starts, preferring the one closest to near_line."""
    quote_lines = [part for part in str(quote).splitlines() if part.strip()]
    if not quote_lines:
        return None
    wanted = normalize(quote)
    first = normalize(quote_lines[0])
    span = len(quote_lines) + 1
    normalized = [normalize(line) for line in lines]
    matches = []
    for index, line in enumerate(normalized):
        if first in line and wanted in normalize(' '.join(lines[index:index + span])):
            matches.append(index + 1)
    if not matches:
        return None
    if near_line:
        return min(matches, key=lambda match: abs(match - near_line))
    return matches[0]


def ground_findings(environment=None):
    """Keeps only findings whose quoted evidence really exists in the PR head at (or near) the reported line."""
    environment = os.environ if environment is None else environment
    findings = load_json(environment, 'FINDINGS_JSON', [])
    production_files = set(load_json(environment, 'PRODUCTION_FILES_JSON', []))
    head_commit = environment['HEAD_COMMIT']
    if not re.fullmatch(r'[0-9a-f]{40}', head_commit):
        raise ValueError('HEAD_COMMIT must be a full commit SHA')

    grounded, rejected, passthrough, files = [], [], [], {}
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        if finding.get('kind') in PASSTHROUGH_KINDS:
            passthrough.append(finding)
            continue
        path = finding.get('file')
        quote = finding.get('evidence_quote')
        line = finding.get('line') if isinstance(finding.get('line'), int) and finding.get('line') > 0 else None
        reason = None
        if not str(finding.get('comment') or '').strip():
            reason = 'empty_comment'
        elif path not in production_files:
            reason = 'file_not_in_review_scope'
        elif len(normalize(quote)) < 6:
            reason = 'missing_evidence_quote'
        else:
            if path not in files:
                files[path] = read_head_file(head_commit, path)
            if files[path] is None:
                reason = 'file_missing_at_head'
            else:
                found = locate_quote(files[path], quote, line)
                if found is None:
                    reason = 'quote_not_found_in_file'
                elif line and abs(found - line) > WINDOW:
                    # The quote exists but far from the reported line: the line number is not trustworthy.
                    finding = {**finding, 'line_corrected_from': line}
                    line = found
                else:
                    line = found
        if reason:
            rejected.append({
                'reason': reason, 'file': path, 'line': finding.get('line'),
                'comment': str(finding.get('comment') or '')[:200],
            })
            continue
        grounded.append({**finding, 'line': line, 'finding_id': len(grounded) + 1})
    return {
        'grounded': grounded,
        'rejected': rejected,
        'passthrough': passthrough,
        'candidate_count': len(grounded) + len(rejected),
    }


def apply_verdicts(environment=None):
    """Keeps the grounded findings the independent verifier confirmed; unjudged findings are dropped."""
    environment = os.environ if environment is None else environment
    grounded = load_json(environment, 'GROUNDED_JSON', [])
    passthrough = load_json(environment, 'PASSTHROUGH_JSON', [])
    verdicts = {}
    for entry in load_json(environment, 'VERDICTS_JSON', []):
        if isinstance(entry, dict) and entry.get('finding_id') is not None:
            verdicts[str(entry['finding_id'])] = entry
    confirmed, rejected = [], []
    for finding in grounded:
        verdict = verdicts.get(str(finding.get('finding_id')), {})
        if str(verdict.get('verdict', '')).lower() == 'confirmed':
            severity = str(verdict.get('severity') or '').lower()
            confirmed.append({**finding, 'severity': severity} if severity in SEVERITIES else finding)
        else:
            rejected.append({
                'reason': 'verifier_' + (str(verdict.get('verdict') or 'no_verdict').lower()),
                'verifier_note': str(verdict.get('reason') or '')[:300],
                'file': finding.get('file'), 'line': finding.get('line'),
                'comment': str(finding.get('comment') or '')[:200],
            })
    ground_rejected = int(environment.get('GROUND_REJECTED_COUNT') or 0)
    return {
        'findings': confirmed + passthrough,
        'confirmed_count': len(confirmed),
        'verifier_rejected': rejected,
        'dropped_count': ground_rejected + len(rejected),
    }

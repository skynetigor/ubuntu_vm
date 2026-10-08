import json
import os
import re
import subprocess

TITLE_PREFIX = '[One Workflow] '
# gh pr create --attach uploads files to GitHub's asset store and rewrites the paths in the body.
ATTACH_MIN_VERSION = (2, 99)


def build_body(body, media, issue_ref, existing_paths):
    """Body text plus one paragraph per video, with the path alone in its own paragraph as an image."""
    parts = [body.rstrip()]
    attached = []
    for item in media or []:
        path = item.get('path', '')
        if path not in existing_paths:
            continue
        parts.append(f"{item.get('label', '')}: {item.get('caption', '')}".strip(': ').rstrip())
        parts.append(f'![]({path})')
        attached.append(path)
    if issue_ref:
        parts.append(f'Closes {issue_ref}')
    return '\n\n'.join(parts) + '\n', attached


def issue_pr_gh(environment=None):
    """Opens a draft PR in the upstream repository (OP=create_draft) or marks it ready (OP=ready)."""
    environment = os.environ if environment is None else environment

    def gh(*args, timeout=300):
        result = subprocess.run(
            ['gh', *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, env={**os.environ, **environment, 'GH_PROMPT_DISABLED': '1'},
        )
        if result.returncode:
            raise RuntimeError(result.stderr[-3000:] or f'gh {args[0]} failed')
        return result.stdout.strip()

    def supports_attach():
        match = re.search(r'gh version (\d+)\.(\d+)', gh('--version'))
        return bool(match) and (int(match.group(1)), int(match.group(2))) >= ATTACH_MIN_VERSION

    try:
        operation = environment['OP']
        upstream = environment['UPSTREAM_REPOSITORY']

        if operation == 'create_draft':
            fork_owner = environment['FORK_REPOSITORY'].split('/')[0]
            title = TITLE_PREFIX + environment['PR_TITLE'].removeprefix(TITLE_PREFIX)
            media = json.loads(environment.get('MEDIA_JSON') or '[]')
            existing = {item.get('path') for item in media if os.path.isfile(item.get('path', ''))}
            can_attach = bool(existing) and supports_attach()
            # #123 for an issue in the PR's own repository, owner/repo#123 for one in another repository.
            issue_ref = environment.get('ISSUE_REF') or (
                f"#{environment['ISSUE_NUMBER']}" if environment.get('ISSUE_NUMBER') else ''
            )
            body, attached = build_body(
                environment['PR_BODY'], media if can_attach else [], issue_ref, existing,
            )
            body_file = environment.get('BODY_FILE') or f"/tmp/issue-pr-body-{environment['ISSUE_NUMBER']}.md"
            with open(body_file, 'w', encoding='utf-8') as handle:
                handle.write(body)

            # A rerun continues the same branch, so its pull request may already exist: reuse it, never create a second.
            open_prs = json.loads(gh(
                'api', f'repos/{upstream}/pulls?state=open&head={fork_owner}:{environment["BRANCH"]}',
            ) or '[]')
            if open_prs:
                pr = open_prs[0]
                return {
                    'status': 'existing' if pr.get('draft') else 'existing_ready', 'url': pr['html_url'],
                    'labels_applied': [], 'labels_missing': [], 'media_attached': [], 'media_skipped': [],
                }

            # Labels are checked in the target repository; only existing ones are applied.
            wanted = json.loads(environment.get('LABELS_JSON') or '[]')
            available = {
                item['name'] for item in json.loads(gh(
                    'label', 'list', '--repo', upstream, '--json', 'name', '--limit', '1000',
                ) or '[]')
            }
            applied = [label for label in wanted if label in available]
            missing = [label for label in wanted if label not in available]

            command = [
                'pr', 'create', '--draft', '--repo', upstream,
                '--head', f"{fork_owner}:{environment['BRANCH']}", '--base', environment['BASE_BRANCH'],
                '--title', title, '--body-file', body_file,
            ]
            for label in applied:
                command += ['--label', label]
            for path in attached:
                command += ['--attach', path]
            url = gh(*command, timeout=900)
            return {
                'status': 'created', 'url': url, 'labels_applied': applied, 'labels_missing': missing,
                'media_attached': attached,
                'media_skipped': [] if can_attach or not existing else sorted(existing),
            }

        if operation == 'ready':
            url = environment['PR_URL']
            gh('pr', 'ready', url, '--repo', upstream)
            return {'status': 'ready', 'url': url}

        raise ValueError(f'Unknown OP: {operation}')
    except Exception as error:
        return {'status': 'failed', 'url': environment.get('PR_URL', ''), 'error': str(error)}

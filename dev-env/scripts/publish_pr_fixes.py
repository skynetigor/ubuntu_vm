import json
import os
import re
import subprocess


def publish_pr_fixes(environment=None):
    environment = os.environ if environment is None else environment

    def run(command, check=True, timeout=120):
        try:
            result = subprocess.run(
                command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(
                f'Command timed out after {timeout} seconds: {command[0]}'
            ) from error
        if check and result.returncode:
            raise RuntimeError(result.stderr[-3000:] or 'command failed')
        return result

    try:
        if not environment.get('GH_TOKEN'):
            raise RuntimeError('GH_TOKEN is required to publish PR fixes')
        pr = json.loads(environment['PR_CONTEXT_JSON'])
        head_repo = pr.get('head_repo')
        head_ref = pr.get('head_ref')
        expected_sha = pr.get('head_sha')
        if not head_repo or not head_ref or not expected_sha:
            raise RuntimeError('PR head repository/ref/SHA is unavailable')
        run(['git', 'check-ref-format', '--branch', head_ref])
        current_sha = run(['git', 'rev-parse', 'HEAD']).stdout.strip()
        if current_sha != expected_sha:
            raise RuntimeError('Checked-out PR head changed before publishing')
        origin = run(['git', 'remote', 'get-url', 'origin']).stdout.strip()
        if not origin.rstrip('/').removesuffix('.git').endswith(head_repo):
            raise RuntimeError('Git origin does not match the PR head repository')
        run(['gh', 'auth', 'setup-git'])
        remote_head = run(
            ['git', 'ls-remote', '--heads', 'origin', f'refs/heads/{head_ref}'],
            timeout=120,
        ).stdout.split()
        if not remote_head or remote_head[0] != expected_sha:
            raise RuntimeError('PR head branch advanced before publishing the fix branch')
        suffix = re.sub(r'[^A-Za-z0-9._-]+', '-', environment['FIX_BRANCH_SUFFIX']).strip('-')
        if not suffix:
            raise RuntimeError('FIX_BRANCH_SUFFIX did not produce a valid branch suffix')
        fix_branch = f'workflow-review-fixes/pr-{pr["number"]}-{suffix[:32]}'
        run(['git', 'check-ref-format', '--branch', fix_branch])

        projects = json.loads(environment['CHANGED_PROJECTS'])
        production_files = set(json.loads(environment['PRODUCTION_FILES_JSON']))
        roots = [project['source_root'].rstrip('/') + '/' for project in projects]
        tracked = run(['git', 'diff', '--name-only', '-z']).stdout.split('\0')
        untracked = run(['git', 'ls-files', '--others', '--exclude-standard', '-z']).stdout.split('\0')
        changed = sorted(set(path for path in tracked + untracked if path))
        allowed = []
        unexpected = []
        ignored_parts = {'node_modules', 'target', 'dist', 'build', '.pnpm-store'}
        for path in changed:
            parts = path.split('/')
            if path in {'.bootstrapcommit', '.clonecommit', '.compilecommit'}:
                continue
            if any(part in ignored_parts for part in parts):
                continue
            test_path = (
                any(part in {'test', 'tests', '__tests__'} for part in parts)
                or any(re.search(r'\.(test|spec)\.[^.]+$', part) for part in parts)
            )
            if path in production_files or (
                test_path and any(path.startswith(root) for root in roots)
            ):
                allowed.append(path)
            else:
                unexpected.append(path)

        if unexpected:
            raise RuntimeError('Refusing to publish out-of-scope changes: ' + ', '.join(unexpected[:20]))
        if not allowed:
            return {'status': 'no_changes', 'published': False, 'changed_files': []}

        user_data = json.loads(run(['gh', 'api', 'user']).stdout)
        login = user_data['login']
        user_id = user_data['id']
        run(['git', 'add', '--', *allowed])
        run(['git', 'diff', '--cached', '--check'])
        run([
            'git', '-c', f'user.name={login}',
            '-c', f'user.email={user_id}+{login}@users.noreply.github.com',
            'commit', '-m', 'Address review comments',
        ])
        commit_sha = run(['git', 'rev-parse', 'HEAD']).stdout.strip()
        pushed = run(
            ['git', 'push', 'origin', f'HEAD:refs/heads/{fix_branch}'],
            check=False, timeout=300,
        )
        if pushed.returncode:
            return {
                'status': 'push_failed', 'published': False,
                'commit_sha': commit_sha, 'changed_files': allowed,
                'fix_branch': fix_branch, 'base_branch': head_ref,
                'error': pushed.stderr[-3000:],
            }
        return {
            'status': 'published', 'published': True,
            'commit_sha': commit_sha, 'changed_files': allowed,
            'fork_repository': head_repo,
            'fix_branch': fix_branch,
            'base_branch': head_ref,
        }
    except Exception as error:
        return {'status': 'failed', 'published': False, 'error': str(error)}
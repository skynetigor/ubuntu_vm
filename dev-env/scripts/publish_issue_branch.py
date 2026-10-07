import json
import os
import re
import subprocess


def publish_issue_branch(environment=None):
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
            raise RuntimeError('GH_TOKEN is required to push the issue branch')
        fork_repository = environment['FORK_REPOSITORY']
        issue_number = int(environment['ISSUE_NUMBER'])
        slug = re.sub(r'[^a-z0-9]+', '-', environment.get('ISSUE_TITLE', '').lower()).strip('-')[:40]
        branch = f'issue-{issue_number}' + (f'-{slug}'.rstrip('-') if slug else '')
        run(['git', 'check-ref-format', '--branch', branch])

        origin = run(['git', 'remote', 'get-url', 'origin']).stdout.strip()
        if not origin.rstrip('/').removesuffix('.git').endswith(fork_repository):
            raise RuntimeError('Git origin does not match the fork repository')
        run(['gh', 'auth', 'setup-git'])

        production_files = set(json.loads(environment['PRODUCTION_FILES_JSON']))
        roots = [
            project['source_root'].rstrip('/') + '/'
            for project in json.loads(environment.get('CHANGED_PROJECTS_JSON') or '[]')
        ]
        tracked = run(['git', 'diff', '--name-only', '-z']).stdout.split('\0')
        untracked = run(['git', 'ls-files', '--others', '--exclude-standard', '-z']).stdout.split('\0')
        changed = sorted(set(path for path in tracked + untracked if path))
        ignored_parts = {'node_modules', 'target', 'dist', 'build', '.pnpm-store'}
        allowed = []
        unexpected = []
        for path in changed:
            if path in {'.bootstrapcommit', '.clonecommit', '.compilecommit'}:
                continue
            if any(part in ignored_parts for part in path.split('/')):
                continue
            parts = path.split('/')
            test_path = (
                any(part in {'test', 'tests', '__tests__'} for part in parts)
                or any(re.search(r'\.(test|spec)\.[^.]+$', part) for part in parts)
            )
            # The loop may change production files and unit tests of the touched projects, nothing else.
            if path in production_files or (test_path and any(path.startswith(root) for root in roots)):
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
        run(['git', 'checkout', '-B', branch])
        run(['git', 'add', '--', *allowed])
        run(['git', 'diff', '--cached', '--check'])
        run([
            'git', '-c', f'user.name={login}',
            '-c', f'user.email={user_id}+{login}@users.noreply.github.com',
            'commit', '-m', environment.get('COMMIT_MESSAGE') or f'Implement issue #{issue_number}',
        ])
        commit_sha = run(['git', 'rev-parse', 'HEAD']).stdout.strip()
        pushed = run(
            ['git', 'push', '--force-with-lease', 'origin', f'HEAD:refs/heads/{branch}'],
            check=False, timeout=300,
        )
        if pushed.returncode:
            return {
                'status': 'push_failed', 'published': False,
                'commit_sha': commit_sha, 'changed_files': allowed,
                'branch': branch, 'error': pushed.stderr[-3000:],
            }
        return {
            'status': 'published', 'published': True,
            'commit_sha': commit_sha, 'changed_files': allowed,
            'fork_repository': fork_repository, 'branch': branch,
        }
    except Exception as error:
        return {'status': 'failed', 'published': False, 'error': str(error)}

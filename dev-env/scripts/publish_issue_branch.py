import json
import os
import re
import subprocess


def _run(command, check=True, timeout=120):
    try:
        result = subprocess.run(
            command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f'Command timed out after {timeout} seconds: {command[0]}') from error
    if check and result.returncode:
        raise RuntimeError(result.stderr[-3000:] or 'command failed')
    return result


def _slug(text, limit=40):
    return re.sub(r'[^a-z0-9]+', '-', (text or '').lower()).strip('-')[:limit].strip('-')


def branch_prefix(environment):
    """The part of the branch name that identifies the issue: issue-<n>, or issue-<repo>-<n> for another repository."""
    number = (environment.get('ISSUE_NUMBER') or '').strip()
    if not number:
        return ''
    repository = (environment.get('ISSUE_REPOSITORY') or '').strip()
    if repository and repository.lower() != (environment.get('UPSTREAM_REPOSITORY') or '').strip().lower():
        return f"issue-{_slug(repository.split('/')[-1], 30)}-{int(number)}"
    return f'issue-{int(number)}'


def new_branch_name(environment):
    """A fixed branch for an issue (the same one on every run); a task has no identity, so its id is the execution."""
    prefix = branch_prefix(environment)
    slug = _slug(environment.get('ISSUE_TITLE'))
    if prefix:
        return '-'.join(part for part in (prefix, slug) if part)
    unique = re.sub(r'[^a-z0-9]', '', environment.get('EXECUTION_ID', '').lower())[:8]
    return '-'.join(part for part in ('task', slug or 'change', unique) if part)


def _remote_branches(pattern):
    """Branches of the fork (origin) matching a ref pattern, name -> commit."""
    output = _run(['git', 'ls-remote', '--heads', 'origin', pattern], check=False, timeout=120).stdout
    branches = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].startswith('refs/heads/'):
            branches[parts[1][len('refs/heads/'):]] = parts[0]
    return branches


def find_existing_branch(environment):
    """The branch an earlier run (or the user) already pushed for this work, if any."""
    requested = (environment.get('BRANCH_OVERRIDE') or '').strip()
    if requested:
        return requested if requested in _remote_branches(f'refs/heads/{requested}') else ''
    prefix = branch_prefix(environment)
    if not prefix:
        return ''
    found = {**_remote_branches(f'refs/heads/{prefix}'), **_remote_branches(f'refs/heads/{prefix}-*')}
    # The title can change, so the issue number decides; with several, the one named like the current title wins.
    wanted = new_branch_name(environment)
    if wanted in found:
        return wanted
    return sorted(found)[0] if found else ''


def start_feature_branch(environment=None):
    """Puts the work on its feature branch, after checking the checkout is the latest upstream main.

    A branch that already exists on the fork is pulled and the work continues from it; otherwise a new
    branch is created from the checkout (the latest main).
    """
    environment = os.environ if environment is None else environment
    try:
        head = _run(['git', 'rev-parse', 'HEAD']).stdout.strip()
        latest = _run(['git', 'rev-parse', environment['UPSTREAM_REF']]).stdout.strip()
        if head != latest:
            return {
                'status': 'not_latest', 'head': head, 'latest_main': latest,
                'error': f'The checkout is at {head[:12]} but the latest main is {latest[:12]}.',
            }
        _run(['gh', 'auth', 'setup-git'], check=False)
        existing = find_existing_branch(environment)
        if existing:
            _run(['git', 'check-ref-format', '--branch', existing])
            _run(['git', 'fetch', '--depth', '256', 'origin', f'refs/heads/{existing}'], timeout=600)
            _run(['git', 'checkout', '-B', existing, 'FETCH_HEAD'])
            branch_head = _run(['git', 'rev-parse', 'HEAD']).stdout.strip()
            return {
                'status': 'started', 'branch': existing, 'resumed': True,
                'base_commit': head, 'branch_head': branch_head,
                'commits_ahead': int(_run(['git', 'rev-list', '--count', f'{head}..HEAD']).stdout.strip() or 0),
            }
        branch = (environment.get('BRANCH_OVERRIDE') or '').strip() or new_branch_name(environment)
        _run(['git', 'check-ref-format', '--branch', branch])
        _run(['git', 'checkout', '-B', branch])
        return {'status': 'started', 'branch': branch, 'resumed': False, 'base_commit': head, 'branch_head': head, 'commits_ahead': 0}
    except Exception as error:
        return {'status': 'failed', 'error': str(error)}


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
        issue_number = (environment.get('ISSUE_NUMBER') or '').strip()
        # The branch was created when the work started; compute it only when it was not passed in.
        branch = (environment.get('BRANCH') or '').strip() or new_branch_name(environment)
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
            # Continuing a branch whose earlier commits already hold the work: nothing new to commit, but the
            # branch still has to be on the fork for the pull request.
            base = (environment.get('BASE_COMMIT') or '').strip()
            if environment.get('RESUMED') == 'true' and base:
                head = run(['git', 'rev-parse', 'HEAD']).stdout.strip()
                if head != base:
                    run(['git', 'checkout', '-B', branch])
                    pushed = run(['git', 'push', 'origin', f'HEAD:refs/heads/{branch}'], check=False, timeout=300)
                    if pushed.returncode:
                        return {
                            'status': 'push_failed', 'published': False, 'commit_sha': head,
                            'changed_files': [], 'branch': branch, 'error': pushed.stderr[-3000:],
                        }
                    return {
                        'status': 'published', 'published': True, 'commit_sha': head, 'changed_files': [],
                        'fork_repository': fork_repository, 'branch': branch,
                    }
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
            'commit', '-m', environment.get('COMMIT_MESSAGE') or (
                f'Implement issue #{issue_number}' if issue_number else 'Implement the requested change'
            ),
        ])
        commit_sha = run(['git', 'rev-parse', 'HEAD']).stdout.strip()
        pushed = run(
            # A plain push: the branch is new for this run, and an existing one must never be overwritten.
            ['git', 'push', 'origin', f'HEAD:refs/heads/{branch}'],
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

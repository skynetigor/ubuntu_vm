import fnmatch
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.request

from snapshot_worktree import create_worktree_snapshot

SHA = re.compile(r'[0-9a-f]{40}')


def github_merge_base(environment, upstream_repo, base_commit, head_commit):
    match = re.fullmatch(r'https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?', upstream_repo)
    if not match:
        return ''
    owner, repo = match.groups()
    token = environment.get('GH_TOKEN', '').strip()
    request = urllib.request.Request(
        f'https://api.github.com/repos/{owner}/{repo}/compare/{base_commit}...{head_commit}?per_page=1',
        headers={
            'Accept': 'application/vnd.github+json',
            **({'Authorization': f'Bearer {token}'} if token else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            sha = (json.load(response).get('merge_base_commit') or {}).get('sha', '')
    except Exception as error:
        print(f'GitHub compare failed, falling back to git history: {str(error)[:200]}', flush=True)
        return ''
    return sha if SHA.fullmatch(sha or '') else ''


def prepare_review(environment=None, cwd=None):
    environment = os.environ if environment is None else environment
    cwd = os.getcwd() if cwd is None else cwd
    started = time.monotonic()

    def log(message):
        print(f'[prepare_review +{time.monotonic() - started:.1f}s] {message}', flush=True)

    def git(*args, check=True):
        command = ['git', *args]
        try:
            completed = subprocess.run(
                command, cwd=cwd, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=300,
                env={**os.environ, **environment, 'GIT_TERMINAL_PROMPT': '0'},
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(f'Git command timed out after 300 seconds: {args[0]}') from error
        if check and completed.returncode:
            raise RuntimeError(completed.stderr[-4000:] or 'git command failed')
        return completed.stdout.strip() if check else completed

    base_branch = environment['BASE_BRANCH']
    if not re.fullmatch(r'[A-Za-z0-9._/-]+', base_branch) or '..' in base_branch:
        raise ValueError('Invalid base_branch')

    base_ref = environment.get('BASE_REF', 'refs/remotes/workflow-review/' + base_branch)
    try:
        git('rev-parse', '--verify', base_ref)
    except RuntimeError:
        git(
            'fetch', '--no-tags', '--depth', environment.get('BASE_DEPTH', '256'),
            environment['UPSTREAM_REPO'], f'+refs/heads/{base_branch}:{base_ref}',
        )
    base_commit = git('rev-parse', base_ref)
    head_commit = git('rev-parse', 'HEAD')
    log(f'base {base_commit[:12]}, head {head_commit[:12]}')

    def has_commit(sha):
        return git('cat-file', '-e', sha + '^{commit}', check=False).returncode == 0

    merge_base = ''
    known_merge_base = environment.get('KNOWN_MERGE_BASE', '').strip()
    if SHA.fullmatch(known_merge_base) and has_commit(known_merge_base):
        merge_base = known_merge_base
        log('reusing known merge base')
    if not merge_base:
        merge_base = github_merge_base(environment, environment['UPSTREAM_REPO'], base_commit, head_commit)
        if merge_base and not has_commit(merge_base):
            fetched = git('fetch', '--no-tags', '--depth', '1', environment['UPSTREAM_REPO'], merge_base, check=False)
            if fetched.returncode or not has_commit(merge_base):
                log('could not fetch merge base reported by GitHub')
                merge_base = ''
        if merge_base:
            log(f'merge base from GitHub compare: {merge_base[:12]}')
    if merge_base:
        merge_base_result = None
    else:
        merge_base_result = git('merge-base', base_commit, head_commit, check=False)
        if merge_base_result.returncode not in {0, 1}:
            raise RuntimeError(merge_base_result.stderr[-4000:] or 'git merge-base failed')

    if merge_base_result is not None and merge_base_result.returncode == 1:
        source_repository = environment['SOURCE_REPOSITORY']
        source_branch = environment.get('SOURCE_BRANCH', '').strip()
        source_ref = source_branch or head_commit
        if not re.fullmatch(r'[A-Za-z0-9._/-]+', source_ref) or '..' in source_ref:
            raise ValueError('Invalid source branch or commit for history deepening')

        max_history_depth = int(environment.get('MAX_HISTORY_DEPTH', '4096'))
        current_depth = int(environment.get('BASE_DEPTH', '256'))
        if max_history_depth < current_depth:
            raise ValueError('MAX_HISTORY_DEPTH must be at least BASE_DEPTH')

        while merge_base_result.returncode == 1 and current_depth < max_history_depth:
            deepen_by = min(current_depth, max_history_depth - current_depth)
            log(f'deepening history by {deepen_by}')
            git('fetch', '--no-tags', '--deepen', str(deepen_by), source_repository, source_ref)
            git(
                'fetch', '--no-tags', '--deepen', str(deepen_by),
                environment['UPSTREAM_REPO'],
                f'+refs/heads/{base_branch}:{base_ref}',
            )
            current_depth += deepen_by
            merge_base_result = git('merge-base', base_commit, head_commit, check=False)
            if merge_base_result.returncode not in {0, 1}:
                raise RuntimeError(merge_base_result.stderr[-4000:] or 'git merge-base failed')

        if merge_base_result.returncode == 1:
            raise RuntimeError(
                f'No merge base found between target {head_commit} and base {base_commit} '
                f'after deepening both histories to {max_history_depth} commits; '
                'the histories may be unrelated or MAX_HISTORY_DEPTH may need to be increased.'
            )

    if not merge_base:
        merge_base = merge_base_result.stdout.strip()
    log(f'merge base resolved: {merge_base[:12]}')
    # Reviews of other people's PRs must ignore local edits left by earlier fix runs in the same checkout.
    committed_only = environment.get('REVIEW_COMMITTED_ONLY', '').lower() == 'true'
    diff_range = [merge_base, head_commit] if committed_only else [merge_base]
    changed = [
        path for path in git(
            'diff', '--name-only', '--diff-filter=ACMRD', *diff_range,
        ).splitlines()
        if path
    ]
    # Keep PR files in scope even after a fix reverts them to the base version.
    changed += [
        path for path in git(
            'diff', '--name-only', '--diff-filter=ACMRD', merge_base, head_commit,
        ).splitlines()
        if path
    ]
    untracked = [
        path for path in git('ls-files', '--others', '--exclude-standard').splitlines()
        if path
    ] if not committed_only else []
    ignored_changed_parts = {
        'node_modules', 'target', 'dist', 'build', 'generated', '.pnpm-store',
    }
    ignored_changed_files = {'.bootstrapcommit', '.clonecommit', '.compilecommit'}
    changed = sorted({
        path for path in changed + untracked
        if path not in ignored_changed_files
        and not any(part in ignored_changed_parts for part in path.split('/'))
    })

    include_globs = json.loads(environment['INCLUDE_GLOBS'])
    exclude_globs = json.loads(environment['EXCLUDE_GLOBS'])
    lint_extensions = ('.js', '.mjs', '.cjs', '.jsx', '.ts', '.tsx')

    # Mirrors publish_pr_fixes test-file allowance so lint fixes stay publishable.
    def is_test_path(path):
        parts = path.split('/')
        return (
            any(part in {'test', 'tests', '__tests__'} for part in parts)
            or any(re.search(r'\.(test|spec)\.[^.]+$', part) for part in parts)
        )

    def is_production_path(path):
        return (
            any(fnmatch.fnmatchcase(path, pattern) for pattern in include_globs)
            and not any(fnmatch.fnmatchcase(path, pattern) for pattern in exclude_globs)
        )

    # Every Kibana package and plugin root has a kibana.jsonc manifest.
    project_by_dir = {}

    def find_project_root(path):
        directory = os.path.dirname(path)
        while directory:
            if directory not in project_by_dir:
                manifest = os.path.join(cwd, directory, 'kibana.jsonc')
                project_by_dir[directory] = os.path.isfile(manifest)
            if project_by_dir[directory]:
                return directory
            directory = os.path.dirname(directory)
        return None

    def read_project_id(root):
        with open(os.path.join(cwd, root, 'kibana.jsonc'), encoding='utf-8') as manifest:
            match = re.search(r'"id"\s*:\s*"([^"]+)"', manifest.read())
        return match.group(1) if match else root

    def group_projects(paths):
        grouped = {}
        for path in paths:
            root = find_project_root(path)
            if root is not None:
                grouped.setdefault(root, []).append(path)
        return [
            {
                'id': read_project_id(root),
                'source_root': root,
                'files': sorted(
                    path for path in project_files
                    if path.endswith(lint_extensions)
                    and os.path.isfile(os.path.join(cwd, path))
                    and (is_production_path(path) or is_test_path(path))
                ),
            }
            for root, project_files in sorted(grouped.items())
        ]

    log(f'{len(changed)} changed files')

    files_by_root = {}
    unscoped_files = []
    for path in changed:
        root = find_project_root(path)
        if root is None:
            unscoped_files.append(path)
        else:
            files_by_root.setdefault(root, []).append(path)

    production_files = [path for path in unscoped_files if is_production_path(path)]
    changed_projects = []
    for root, project_files in sorted(files_by_root.items()):
        project_production_files = {path for path in project_files if is_production_path(path)}
        production_files.extend(project_production_files)
        changed_projects.append({
            'id': read_project_id(root),
            'source_root': root,
            'files': sorted(
                path for path in project_files
                if path.endswith(lint_extensions)
                and os.path.isfile(os.path.join(cwd, path))
                and (path in project_production_files or is_test_path(path))
            ),
        })

    production_files = sorted(set(production_files))
    max_files = int(environment['MAX_FILES'])
    allow_partial = environment.get('ALLOW_PARTIAL_DIFF', '').lower() == 'true'
    if len(production_files) > max_files and not allow_partial:
        raise RuntimeError(
            f'{len(production_files)} production files exceed the configured limit '
            f'of {max_files}; reduce the review scope or raise the limit.'
        )

    tracked_production_files = sorted(set(production_files) - set(untracked))
    diff_stat = (
        git('diff', '--stat', *diff_range, '--', *tracked_production_files)
        if tracked_production_files else ''
    )
    max_diff_chars = int(environment['MAX_DIFF_CHARS'])

    def build_diff(context_lines):
        text = (
            git(
                'diff', '--no-ext-diff', f'--unified={context_lines}',
                *diff_range, '--', *tracked_production_files,
            )
            if tracked_production_files else ''
        )
        for path in sorted(set(production_files) & set(untracked)):
            completed = subprocess.run(
                ['git', 'diff', '--no-index', '--no-ext-diff', f'--unified={context_lines}',
                 '--', '/dev/null', path],
                cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=300,
            )
            if completed.returncode not in {0, 1}:
                raise RuntimeError(completed.stderr[-4000:] or f'Unable to diff untracked file: {path}')
            text += completed.stdout
        return text

    # Large PRs get less surrounding context before any file is left out.
    for context_lines in (60, 20, 10, 3):
        diff_text = build_diff(context_lines)
        if len(diff_text) <= max_diff_chars:
            break
        log(f'diff with {context_lines} context lines is {len(diff_text)} characters, over {max_diff_chars}')

    skipped_diff_files = []
    if len(diff_text) > max_diff_chars or (allow_partial and len(production_files) > max_files):
        if not allow_partial:
            raise RuntimeError(
                f'Production diff is {len(diff_text)} characters even with minimal context, above the '
                f'hard limit of {max_diff_chars}; reduce the review scope or raise the limit.'
            )
        # Keep as many files as fit, smallest first, so the most files get reviewed.
        parts = re.split(r'(?m)^(?=diff --git )', diff_text)
        file_diffs = []
        for part in parts:
            match = re.match(r'diff --git a/(.+?) b/', part)
            if match:
                file_diffs.append((match.group(1), part))
        kept, used = set(), 0
        for path, part in sorted(file_diffs, key=lambda item: len(item[1])):
            if used + len(part) > max_diff_chars or len(kept) >= max_files:
                continue
            kept.add(path)
            used += len(part)
        skipped_diff_files = sorted({path for path, _ in file_diffs} - kept)
        diff_text = ''.join(part for path, part in file_diffs if path in kept)
        log(f'partial diff: {len(kept)} files kept, {len(skipped_diff_files)} skipped, {len(diff_text)} characters')

    production_diff_artifact = tempfile.NamedTemporaryFile(
        mode='w', prefix='kbn-review-production-diff-', suffix='.patch',
        delete=False, encoding='utf-8',
    )
    with production_diff_artifact:
        production_diff_artifact.write(diff_text)

    changed_files_artifact = tempfile.NamedTemporaryFile(
        mode='w', prefix='kbn-review-changed-files-', suffix='.json',
        delete=False, encoding='utf-8',
    )
    with changed_files_artifact:
        json.dump(changed, changed_files_artifact)
    log('full diff prepared')

    # Later fix rounds review and test only what changed since the previous round's snapshot.
    delta = {
        'delta_files': [],
        'delta_production_files': [],
        'delta_diff_path': '',
        'delta_diff_chars': 0,
        'delta_diff_sha256': '',
        'delta_projects': [],
    }
    delta_base = environment.get('DELTA_BASE', '').strip()
    if delta_base:
        if not SHA.fullmatch(delta_base) or not has_commit(delta_base):
            raise ValueError('DELTA_BASE must be an existing snapshot commit')
        current_snapshot = create_worktree_snapshot(cwd, environment)
        delta_files = sorted(
            path for path in git('diff', '--name-only', delta_base, current_snapshot).splitlines()
            if path and path not in ignored_changed_files
            and not any(part in ignored_changed_parts for part in path.split('/'))
        )
        delta_production_files = [path for path in delta_files if is_production_path(path)]
        delta_text = (
            git('diff', '--no-ext-diff', '--unified=40', delta_base, current_snapshot, '--', *delta_production_files)
            if delta_production_files else ''
        )
        delta_artifact = tempfile.NamedTemporaryFile(
            mode='w', prefix='kbn-review-delta-diff-', suffix='.patch',
            delete=False, encoding='utf-8',
        )
        with delta_artifact:
            delta_artifact.write(delta_text)
        delta = {
            'delta_files': delta_files,
            'delta_production_files': delta_production_files,
            'delta_diff_path': delta_artifact.name,
            'delta_diff_chars': len(delta_text),
            'delta_diff_sha256': hashlib.sha256(delta_text.encode('utf-8')).hexdigest(),
            'delta_projects': group_projects(delta_files),
        }
        log(f'delta since {delta_base[:12]}: {len(delta_files)} files')

    if delta_base:
        failed_ids = set(json.loads(environment.get('PREVIOUS_FAILED_PROJECT_IDS') or '[]'))
        test_projects = list(delta['delta_projects'])
        seen_ids = {project['id'] for project in test_projects}
        test_projects += [
            project for project in changed_projects
            if project['id'] in failed_ids and project['id'] not in seen_ids
        ]
        lint_projects = delta['delta_projects']
    else:
        test_projects = changed_projects
        lint_projects = changed_projects
    if environment.get('RUN_TESTS', 'true').lower() == 'false':
        test_projects = []

    return {
        'project': environment['PROJECT'],
        'base_commit': base_commit,
        'head_commit': head_commit,
        'merge_base': merge_base,
        'changed_files': changed,
        'changed_files_path': changed_files_artifact.name,
        'production_diff_path': production_diff_artifact.name,
        'production_diff_chars': len(diff_text),
        'diff_context_lines': context_lines,
        'diff_skipped_files': skipped_diff_files,
        'production_diff_sha256': hashlib.sha256(diff_text.encode('utf-8')).hexdigest(),
        'changed_projects': changed_projects,
        'production_files': production_files,
        'diff_stat': diff_stat,
        'test_projects': test_projects,
        'lint_projects': lint_projects,
        **delta,
    }
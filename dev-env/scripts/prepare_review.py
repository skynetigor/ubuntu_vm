import fnmatch
import json
import os
import re
import subprocess
import tempfile


def prepare_review(environment=None, cwd=None):
    environment = os.environ if environment is None else environment
    cwd = os.getcwd() if cwd is None else cwd

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
    merge_base_result = git('merge-base', base_commit, head_commit, check=False)
    if merge_base_result.returncode not in {0, 1}:
        raise RuntimeError(merge_base_result.stderr[-4000:] or 'git merge-base failed')

    if merge_base_result.returncode == 1:
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

    merge_base = merge_base_result.stdout.strip()
    changed = [
        path for path in git(
            'diff', '--name-only', '--diff-filter=ACMRD', merge_base,
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
    ]
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
    if len(production_files) > max_files:
        raise RuntimeError(
            f'{len(production_files)} production files exceed the configured limit '
            f'of {max_files}; reduce the review scope or raise the limit.'
        )

    tracked_production_files = sorted(set(production_files) - set(untracked))
    diff_stat = (
        git('diff', '--stat', merge_base, '--', *tracked_production_files)
        if tracked_production_files else ''
    )
    diff_text = (
        git(
            'diff', '--no-ext-diff', '--unified=60',
            merge_base, '--', *tracked_production_files,
        )
        if tracked_production_files else ''
    )
    untracked_diffs = []
    for path in sorted(set(production_files) & set(untracked)):
        completed = subprocess.run(
            ['git', 'diff', '--no-index', '--no-ext-diff', '--unified=60', '--', '/dev/null', path],
            cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=300,
        )
        if completed.returncode not in {0, 1}:
            raise RuntimeError(completed.stderr[-4000:] or f'Unable to diff untracked file: {path}')
        untracked_diffs.append(completed.stdout)
    diff_text += ''.join(untracked_diffs)
    max_diff_chars = int(environment['MAX_DIFF_CHARS'])
    if len(diff_text) > max_diff_chars:
        raise RuntimeError(
            f'Production diff is {len(diff_text)} characters, above the hard limit '
            f'of {max_diff_chars}; reduce the review scope or raise the limit.'
        )

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

    return {
        'project': environment['PROJECT'],
        'base_commit': base_commit,
        'head_commit': head_commit,
        'merge_base': merge_base,
        'changed_files': changed,
        'changed_files_path': changed_files_artifact.name,
        'production_diff_path': production_diff_artifact.name,
        'production_diff_chars': len(diff_text),
        'changed_projects': changed_projects,
        'production_files': production_files,
        'diff_stat': diff_stat,
    }
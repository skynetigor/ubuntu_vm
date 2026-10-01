import fnmatch
import json
import os
import re
import subprocess
import tempfile


def prepare_review(environment=None, cwd=None):
    environment = os.environ if environment is None else environment
    cwd = os.getcwd() if cwd is None else cwd

    def git(*args):
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
        if completed.returncode:
            raise RuntimeError(completed.stderr[-4000:] or 'git command failed')
        return completed.stdout.strip()

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
    merge_base = git('merge-base', base_commit, head_commit)
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

    projects = json.loads(environment['WORKFLOW_PROJECTS'])
    include_globs = json.loads(environment['INCLUDE_GLOBS'])
    exclude_globs = json.loads(environment['EXCLUDE_GLOBS'])
    production_files = []
    changed_projects = []
    for project in projects:
        root = project['source_root'].rstrip('/') + '/'
        project_files = [path for path in changed if path.startswith(root)]
        if not project_files:
            continue
        changed_projects.append(project)
        for path in project_files:
            if not any(fnmatch.fnmatchcase(path, pattern) for pattern in include_globs):
                continue
            if any(fnmatch.fnmatchcase(path, pattern) for pattern in exclude_globs):
                continue
            production_files.append(path)

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
        'changed_projects': changed_projects,
        'production_files': production_files,
        'diff_stat': diff_stat,
        'production_diff': diff_text,
    }
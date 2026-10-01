import fnmatch
import json
import os
import re
import subprocess


def prepare_review(environment=None, cwd=None):
    environment = os.environ if environment is None else environment
    cwd = os.getcwd() if cwd is None else cwd

    def git(*args):
        completed = subprocess.run(
            ['git', *args], cwd=cwd, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if completed.returncode:
            raise RuntimeError(completed.stderr[-4000:] or 'git command failed')
        return completed.stdout.strip()

    base_branch = environment['BASE_BRANCH']
    if not re.fullmatch(r'[A-Za-z0-9._/-]+', base_branch) or '..' in base_branch:
        raise ValueError('Invalid base_branch')

    base_ref = 'refs/remotes/workflow-review/' + base_branch
    git(
        'fetch', '--no-tags', environment['UPSTREAM_REPO'],
        f'+refs/heads/{base_branch}:{base_ref}',
    )
    base_commit = git('rev-parse', base_ref)
    head_commit = git('rev-parse', 'HEAD')
    merge_base = git('merge-base', base_commit, head_commit)
    changed = [
        path for path in git(
            'diff', '--name-only', '--diff-filter=ACMR',
            f'{merge_base}...{head_commit}',
        ).splitlines()
        if path
    ]

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

    diff_stat = (
        git('diff', '--stat', f'{merge_base}...{head_commit}', '--', *production_files)
        if production_files else ''
    )
    diff_text = (
        git(
            'diff', '--no-ext-diff', '--unified=60',
            f'{merge_base}...{head_commit}', '--', *production_files,
        )
        if production_files else ''
    )
    max_diff_chars = int(environment['MAX_DIFF_CHARS'])
    if len(diff_text) > max_diff_chars:
        raise RuntimeError(
            f'Production diff is {len(diff_text)} characters, above the hard limit '
            f'of {max_diff_chars}; reduce the review scope or raise the limit.'
        )

    return {
        'project': environment['PROJECT'],
        'base_commit': base_commit,
        'head_commit': head_commit,
        'merge_base': merge_base,
        'changed_files': changed,
        'changed_projects': changed_projects,
        'production_files': production_files,
        'diff_stat': diff_stat,
        'production_diff': diff_text,
    }
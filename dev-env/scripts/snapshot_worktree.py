import os
import shutil
import subprocess
import tempfile


def create_worktree_snapshot(cwd, environment=None):
    environment = os.environ if environment is None else environment

    def git(*args, env=None):
        completed = subprocess.run(
            ['git', *args], cwd=cwd, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600,
            env={**os.environ, **environment, 'GIT_TERMINAL_PROMPT': '0', **(env or {})},
        )
        if completed.returncode:
            raise RuntimeError(completed.stderr[-4000:] or f'git {args[0]} failed')
        return completed.stdout.strip()

    real_index = git('rev-parse', '--git-path', 'index')
    if not os.path.isabs(real_index):
        real_index = os.path.join(cwd, real_index)
    handle, temp_index = tempfile.mkstemp(prefix='kbn-snapshot-index-')
    os.close(handle)
    try:
        # Starting from the real index reuses its stat cache, so only changed files are rehashed.
        if os.path.exists(real_index):
            shutil.copyfile(real_index, temp_index)
        index_env = {'GIT_INDEX_FILE': temp_index}
        git('add', '-A', env=index_env)
        tree = git('write-tree', env=index_env)
    finally:
        os.unlink(temp_index)
    identity = {
        'GIT_AUTHOR_NAME': 'workflow-snapshot', 'GIT_AUTHOR_EMAIL': 'workflow-snapshot@localhost',
        'GIT_COMMITTER_NAME': 'workflow-snapshot', 'GIT_COMMITTER_EMAIL': 'workflow-snapshot@localhost',
    }
    return git('commit-tree', tree, '-p', 'HEAD', '-m', 'workflow worktree snapshot', env=identity)


def snapshot_worktree(environment=None, cwd=None):
    cwd = os.getcwd() if cwd is None else cwd
    snapshot = create_worktree_snapshot(cwd, environment)
    print(f'Worktree snapshot: {snapshot}', flush=True)
    return {'snapshot': snapshot}

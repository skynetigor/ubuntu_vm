import json
import os
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


def checkout_kibana_project(environment=None):
    environment = os.environ if environment is None else environment
    target = environment['KIBANA_TARGET'].strip()
    ubuntu_vm_repo = environment['UBUNTU_VM_REPO']
    ubuntu_vm_branch = environment['UBUNTU_VM_BRANCH']
    additional_branches = json.loads(environment.get('ADDITIONAL_BRANCHES_JSON', '[]'))
    target_depth = int(environment.get('TARGET_DEPTH', '256'))

    if target_depth < 1:
        raise ValueError('TARGET_DEPTH must be positive')

    def run(command, cwd=None, timeout=600, check=True):
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                env={**os.environ, **environment, 'GIT_TERMINAL_PROMPT': '0'},
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(
                f'Command timed out after {timeout} seconds: {command[0]}'
            ) from error
        if check and result.returncode:
            raise RuntimeError(result.stderr[-4000:] or result.stdout[-4000:] or 'command failed')
        return result

    def github_pr(owner, repo, number):
        request = urllib.request.Request(
            f'https://api.github.com/repos/{owner}/{repo}/pulls/{number}',
            headers={
                'Accept': 'application/vnd.github+json',
                **(
                    {'Authorization': f'Bearer {environment["GH_TOKEN"]}'}
                    if environment.get('GH_TOKEN') else {}
                ),
            },
        )
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.load(response)

    parsed = urlparse(target)
    if parsed.scheme != 'https' or parsed.hostname != 'github.com':
        raise ValueError('KIBANA_TARGET must be an https://github.com URL')
    parts = [part for part in parsed.path.split('/') if part]
    if len(parts) < 4:
        raise ValueError('KIBANA_TARGET must identify a PR, branch, or commit')
    owner, repo, target_type = parts[0], parts[1].removesuffix('.git'), parts[2]
    target_value = '/'.join(parts[3:])

    if target_type == 'pull' and re.fullmatch(r'\d+', target_value):
        pr = github_pr(owner, repo, target_value)
        source_repo = pr['head']['repo']['clone_url']
        source_branch = pr['head']['ref']
        commit = pr['head']['sha']
        project_seed = source_branch
    elif target_type == 'tree' and target_value:
        source_repo = f'https://github.com/{owner}/{repo}.git'
        source_branch = target_value
        result = run(['git', 'ls-remote', source_repo, f'refs/heads/{source_branch}'], timeout=90)
        rows = [line.split() for line in result.stdout.splitlines() if line.strip()]
        if len(rows) != 1:
            raise RuntimeError(f'Unable to resolve branch: {source_branch}')
        commit = rows[0][0]
        project_seed = source_branch
    elif target_type == 'commit' and re.fullmatch(r'[0-9a-fA-F]{7,40}', target_value):
        source_repo = f'https://github.com/{owner}/{repo}.git'
        source_branch = ''
        commit = target_value.lower()
        project_seed = f'commit-{commit[:8]}'
    else:
        raise ValueError('KIBANA_TARGET must identify a PR, branch, or hexadecimal commit')

    project = re.sub(r'[^a-z0-9-]', '-', project_seed.lower().replace('/', '-'))[:50]
    if not project:
        raise RuntimeError('Target resolved to an empty project name')
    deploy_dir = Path(environment.get('DEPLOY_ROOT', '/opt')) / project
    source_dir = deploy_dir / 'kibana' / 'src'

    run(['sudo', 'mkdir', '-p', str(deploy_dir)])
    run(['sudo', 'chown', 'kibana:kibana', str(deploy_dir)])
    if (deploy_dir / '.git').exists():
        run(['git', 'fetch', '--depth', '1', 'origin', ubuntu_vm_branch], cwd=deploy_dir)
        run(['git', 'reset', '--hard', 'FETCH_HEAD'], cwd=deploy_dir)
    else:
        if any(deploy_dir.iterdir()):
            raise RuntimeError(f'Deployment directory exists but is not a Git checkout: {deploy_dir}')
        run([
            'git', 'clone', '--depth', '1', '--branch', ubuntu_vm_branch,
            ubuntu_vm_repo, str(deploy_dir),
        ])

    current_commit = ''
    if (source_dir / '.git').exists():
        current = run(['git', 'rev-parse', 'HEAD'], cwd=source_dir, timeout=30, check=False)
        if current.returncode == 0:
            current_commit = current.stdout.strip()
            run(['git', 'remote', 'set-url', 'origin', source_repo], cwd=source_dir)
    commit_matches = (
        current_commit == commit
        or (target_type == 'commit' and current_commit.startswith(commit))
    )
    checkout_changed = not commit_matches

    if checkout_changed:
        if not (source_dir / '.git').exists():
            if source_dir.exists():
                shutil.rmtree(source_dir)
            source_dir.parent.mkdir(parents=True, exist_ok=True)
            run(['git', 'init', str(source_dir)])
            run(['git', 'remote', 'add', 'origin', source_repo], cwd=source_dir)
        else:
            run(['git', 'remote', 'set-url', 'origin', source_repo], cwd=source_dir)

        fetch_target = source_branch or commit
        run(
            ['git', 'fetch', '--depth', str(target_depth), 'origin', fetch_target],
            cwd=source_dir,
        )
        fetched_commit = run(['git', 'rev-parse', 'FETCH_HEAD'], cwd=source_dir, timeout=30).stdout.strip()
        if fetched_commit != commit and not (
            target_type == 'commit' and fetched_commit.startswith(commit)
        ):
            raise RuntimeError(
                f'Resolved target moved during checkout: expected {commit}, fetched {fetched_commit}'
            )
        commit = fetched_commit
        run(['git', 'reset', '--hard', commit], cwd=source_dir)
        run(['git', 'clean', '-fd'], cwd=source_dir)
        current_commit = fetched_commit
    elif source_branch:
        run(
            ['git', 'fetch', '--depth', str(target_depth), 'origin', source_branch],
            cwd=source_dir,
        )

    fetched_branches = []
    for item in additional_branches:
        repository = str(item.get('repository', '')).strip()
        branch = str(item.get('branch', '')).strip()
        ref = str(item.get('ref', '')).strip()
        depth = int(item.get('depth', target_depth))
        if not repository or not branch or not ref:
            raise ValueError('Each additional branch requires repository, branch, and ref')
        if not ref.startswith('refs/remotes/') or '..' in ref or not re.fullmatch(r'[A-Za-z0-9._/-]+', ref):
            raise ValueError(f'Invalid additional branch ref: {ref}')
        if not re.fullmatch(r'[A-Za-z0-9._/-]+', branch) or '..' in branch:
            raise ValueError(f'Invalid additional branch name: {branch}')
        if depth < 1:
            raise ValueError('Additional branch depth must be positive')
        run(
            [
                'git', 'fetch', '--no-tags', '--depth', str(depth), repository,
                f'+refs/heads/{branch}:{ref}',
            ],
            cwd=source_dir,
        )
        fetched_branches.append({
            'repository': repository,
            'branch': branch,
            'ref': ref,
            'commit': run(['git', 'rev-parse', ref], cwd=source_dir, timeout=30).stdout.strip(),
            'depth': depth,
        })

    (source_dir / '.clonecommit').write_text(current_commit + '\n', encoding='utf-8')
    return {
        'project': project,
        'target': target,
        'commit': current_commit,
        'source_repository': source_repo,
        'source_branch': source_branch,
        'deploy_dir': str(deploy_dir),
        'source_dir': str(source_dir),
        'checkout_changed': checkout_changed,
        'clone_skipped': not checkout_changed,
        'fetched_branches': fetched_branches,
    }
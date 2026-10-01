import json
import os
import re
import subprocess
import tempfile
from pathlib import Path


def check_workflow_projects(environment=None, cwd=None):
    environment = os.environ if environment is None else environment
    root = Path.cwd().resolve() if cwd is None else Path(cwd).resolve()
    projects = json.loads(environment['PROJECTS_JSON'])
    changed_files = json.loads(environment['FILES_JSON'])
    max_chars = int(environment['MAX_DIAGNOSTIC_CHARS'])
    log_dir = Path(tempfile.mkdtemp(prefix='kbn-workflow-checks-'))
    check_extensions = ('.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs')
    generated_parts = {'target', 'dist', 'build', 'node_modules', 'generated', '.pnpm-store'}
    current_changes = subprocess.run(
        ['git', 'diff', '--name-only', '--diff-filter=ACMR'], cwd=root,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        timeout=30,
    ).stdout.splitlines()
    untracked_changes = subprocess.run(
        ['git', 'ls-files', '--others', '--exclude-standard'], cwd=root,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        timeout=30,
    ).stdout.splitlines()
    changed_files = sorted(set(changed_files + current_changes + untracked_changes))
    check_mode = environment.get('CHECK_MODE', 'all')
    if check_mode not in {'all', 'lint', 'tests'}:
        raise ValueError('check_mode must be all, lint, or tests')

    def grant_runner_access(path):
        subprocess.run(
            ['setfacl', '-R', '-m', 'u:workflow-runner:rwx', str(path)],
            cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=120,
        )
        subprocess.run(
            ['setfacl', '-R', '-d', '-m', 'u:workflow-runner:rwx', str(path)],
            cwd=root, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=120,
        )

    def execute(command, log_path, timeout):
        subprocess.run(
            [
                'sudo', '-u', 'workflow-runner', 'env', '-i',
                'HOME=/home/workflow-runner',
                'PATH=/usr/local/bin:/usr/bin:/bin',
                'git', 'config', '--global', '--add', 'safe.directory', str(root),
            ],
            cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        isolated_command = [
            'sudo', '-u', 'workflow-runner', 'env', '-i',
            'HOME=/home/workflow-runner',
            'PATH=/usr/local/bin:/usr/bin:/bin',
            'NODE_PATH=/home/kibana/.nvm/versions/node/current/lib/node_modules',
            'CI=true',
            *command,
        ]
        timed_out = False
        try:
            completed = subprocess.run(
                isolated_command,
                cwd=root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
            )
            stdout = completed.stdout
            stderr = completed.stderr
            exit_code = completed.returncode
        except subprocess.TimeoutExpired as error:
            timed_out = True
            stdout = error.stdout or ''
            stderr = error.stderr or ''
            if isinstance(stdout, bytes):
                stdout = stdout.decode(errors='replace')
            if isinstance(stderr, bytes):
                stderr = stderr.decode(errors='replace')
            stderr += f'\nTimed out after {timeout} seconds.'
            exit_code = 124
        full_output = (
            'COMMAND: ' + ' '.join(command) + '\n'
            + 'EXIT_CODE: ' + str(exit_code) + '\n'
            + '--- STDOUT ---\n' + stdout + '\n'
            + '--- STDERR ---\n' + stderr
        )
        log_path.write_text(full_output, encoding='utf-8')
        diagnostics = (stdout + '\n' + stderr).strip()
        return {
            'command': ' '.join(command),
            'exit_code': exit_code,
            'log_path': str(log_path),
            'diagnostic': diagnostics[-max_chars:],
            'timed_out': timed_out,
            'state': 'failed' if exit_code != 0 else 'passed',
        }

    results = []
    source_roots = sorted({
        root / project['source_root']
        for project in projects
        if any(path.startswith(project['source_root'].rstrip('/') + '/') for path in changed_files)
    })
    grant_runner_access(root / 'node_modules')
    for source_root in source_roots:
        if source_root.exists() and source_root.resolve().is_relative_to(root):
            grant_runner_access(source_root)

    for project in projects:
        source_root = project['source_root'].rstrip('/')
        project_changes = [
            name for name in changed_files
            if name.startswith(source_root + '/')
            and '..' not in Path(name).parts
            and (root / name).resolve().is_relative_to(root)
        ]
        if not project_changes:
            continue
        project_files = sorted({
            name for name in project_changes
            if name.endswith(check_extensions)
            and not any(part in generated_parts for part in Path(name).parts)
        })

        safe_id = re.sub(r'[^A-Za-z0-9_.-]+', '_', project['id'])
        lint = (
            execute(
                ['node', 'scripts/eslint.js', '--fix', *project_files],
                log_dir / (safe_id + '-lint.log'),
                timeout=900,
            )
            if project_files and check_mode in {'all', 'lint'}
            else {'command': 'not_run', 'exit_code': 0, 'log_path': '', 'diagnostic': '', 'state': 'not_run'}
        )
        if check_mode in {'all', 'tests'}:
            test = execute(
                ['node_modules/.bin/moon', 'run', project['id'] + ':jest'],
                log_dir / (safe_id + '-jest.log'),
                timeout=7200,
            )
        else:
            test = {'command': 'not_run', 'exit_code': 0, 'log_path': '', 'diagnostic': '', 'state': 'not_run'}
        if test['state'] != 'not_run':
            test_text = test['diagnostic']
            test['state'] = (
                'failed' if test['exit_code'] != 0 else
                'no_tests' if re.search(
                    r'No tests found|No matching tests|No test files found', test_text, re.I
                ) else 'passed'
            )
        if lint['state'] not in {'not_applicable', 'not_run'}:
            lint['state'] = 'failed' if lint['exit_code'] != 0 else 'passed'
        results.append({
            'project': project['id'],
            'files': project_files,
            'lint': lint,
            'tests': test,
        })

    lint_failures = [
        {'project': item['project'], **item['lint']}
        for item in results if item['lint']['state'] == 'failed'
    ]
    test_failures = [
        {'project': item['project'], **item['tests']}
        for item in results if item['tests']['state'] == 'failed'
    ]
    return {
        'results': results,
        'lint_failures': lint_failures,
        'test_failures': test_failures,
        'has_lint_failures': 'true' if lint_failures else 'false',
        'has_test_failures': 'true' if test_failures else 'false',
        'all_passed': 'true' if not lint_failures and not test_failures else 'false',
        'log_dir': str(log_dir),
    }
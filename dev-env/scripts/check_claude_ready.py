"""Cheap check that Claude Code can take a job right now (used by main-kibana-agent before routing)."""

import json
import os
import signal
import subprocess
import threading

from agent_errors import BUDGET, AUTH, classify_event, classify_plain_text, retry_after_epoch

PROBE_TIMEOUT_SECONDS = 90


def check_claude_ready(environment=None):
    environment = os.environ if environment is None else environment
    agent_env = environment.copy()
    for secret_name in ('GH_TOKEN', 'GH_UPSTREAM_TOKEN', 'GH_PUBLIC_REPOS_TOKEN', 'GITHUB_TOKEN',
                        'BUILD_KITE_API_TOKEN', 'COPILOT_GITHUB_TOKEN'):
        agent_env.pop(secret_name, None)
    command = [
        'claude',
        '--disallowedTools', 'Bash', 'Edit', 'Write', 'WebFetch', 'WebSearch', 'Task',
        '--print', '--verbose', '--output-format', 'stream-json',
        '--model', environment.get('CLAUDE_PROBE_MODEL', 'haiku'),
        'Reply with the single word OK.',
    ]
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
            env=agent_env, cwd=environment.get('HOME', '/tmp'), start_new_session=True,
        )
    except FileNotFoundError:
        return _not_ready(AUTH, 'claude CLI is not installed')

    finding = None
    plain_lines = []

    def kill_group(sig=signal.SIGTERM):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass

    # Reading stdout blocks, so a hung CLI is killed by a timer instead of a deadline check.
    timer = threading.Timer(PROBE_TIMEOUT_SECONDS, kill_group)
    timer.start()
    try:
        for line in process.stdout:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                plain_lines.append(line.rstrip())
                continue
            finding = classify_event(event)
            # A bad token is retried ~10 times with backoff; the first signal is enough.
            if finding or event.get('type') == 'result':
                break
    finally:
        timer.cancel()
        kill_group()
        try:
            exit_code = process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            kill_group(signal.SIGKILL)
            exit_code = process.wait()

    finding = finding or (classify_plain_text(plain_lines) if exit_code not in (0, -signal.SIGTERM) else None)
    if finding and finding[0] in (BUDGET, AUTH):
        return _not_ready(*finding)
    # Anything else (network blip, CLI bug) is not a reason to switch agents: the real run reports it.
    return {'ready': True, 'reason': 'ok', 'message': '', 'resets_at': None, 'until_epoch': 0}


def _not_ready(reason, message, resets_at=None):
    print('Claude readiness: not ready (' + reason + '): ' + message, flush=True)
    return {
        'ready': False,
        'reason': reason,
        'message': message,
        'resets_at': resets_at,
        'until_epoch': retry_after_epoch(reason, resets_at),
    }

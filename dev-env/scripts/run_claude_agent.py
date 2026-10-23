import json
import os
import queue
import re
import signal
import subprocess
import threading
import time

from agent_errors import ClaudeUnavailable, classify_event, classify_plain_text


OUTPUT_SCHEMA = {
    'type': 'object',
    'properties': {
        'response': {
            'type': 'string',
            'description': 'Answer for the user, formatted as GitHub-flavored Markdown.',
        },
        'run_summary': {
            'type': 'string',
            'description': 'Handoff summary for the next phase, formatted as GitHub-flavored Markdown.',
        },
        'findings': {'type': 'array'},
        'changes': {'type': 'array'},
        'pull_request': {
            'type': 'object',
            'properties': {
                'title': {'type': 'string'},
                'body': {
                    'type': 'string',
                    'description': 'Pull request description, formatted as GitHub-flavored Markdown.',
                },
            },
            'required': ['title', 'body'],
            'additionalProperties': False,
        },
    },
    'required': ['response', 'run_summary', 'findings', 'changes'],
    'additionalProperties': False,
}


COPILOT_SESSION_PREFIX = 'copilot:'

# Tokens the agents must not see; agents act on GitHub only through the workflow's own steps.
AGENT_SECRET_NAMES = ('GH_TOKEN', 'GH_UPSTREAM_TOKEN', 'GH_PUBLIC_REPOS_TOKEN', 'GITHUB_TOKEN', 'BUILD_KITE_API_TOKEN')


def build_agent_prompt(prompt, run_summary=''):
    run_summary = (run_summary or '').strip()
    if run_summary:
        prompt = 'Previous workflow phase summary:\n' + run_summary + '\n\n' + prompt
    return prompt + (
        '\n\nReturn the requested structured result. '
        'Format `response` and `run_summary` as '
        'GitHub-flavored Markdown: use headings, bullet lists, and inline code '
        'for paths and identifiers; never return a single unstructured paragraph. '
        'Any `pull_request.body` is GitHub-flavored Markdown in the style the request asks for. '
        '`run_summary` must be a concise durable handoff with `### Decisions`, '
        '`### Findings`, `### Files changed`, `### Unresolved`, and '
        '`### Next actions` sections (write "None" for empty ones). '
        'Do not include secrets.'
    )


def validate_phase_result(phase_result, agent_name):
    if not isinstance(phase_result, dict):
        raise RuntimeError(agent_name + ' did not return structured output')
    if not isinstance(phase_result.get('run_summary'), str):
        raise RuntimeError(agent_name + ' structured output is missing run_summary')
    if not isinstance(phase_result.get('findings'), list):
        raise RuntimeError(agent_name + ' structured output is missing findings')
    if not isinstance(phase_result.get('changes'), list):
        raise RuntimeError(agent_name + ' structured output is missing changes')


def run_claude_agent(environment=None):
    environment = os.environ if environment is None else environment
    session_id = environment.get('CLAUDE_SESSION_ID', '').strip()
    # A Copilot fallback session cannot be resumed by Claude; the run summary carries the context.
    if session_id.startswith(COPILOT_SESSION_PREFIX):
        print('Claude: previous session ran on Copilot, starting a new Claude session', flush=True)
        session_id = ''
    prompt = build_agent_prompt(environment['CLAUDE_PROMPT'], environment.get('CLAUDE_RUN_SUMMARY', ''))
    disallowed_tools = [
        'Bash(sudo *)',
        'Bash(docker *)',
        'Bash(gh *)',
        'Bash(git commit *)',
        'Bash(git push *)',
    ]
    if environment.get('CLAUDE_DISALLOW_SHELL', '').lower() in {'true', '1'}:
        disallowed_tools.insert(0, 'Bash')
    command = [
        'claude',
        '--disallowedTools',
        *disallowed_tools,
        '--print',
        '--verbose',
        '--output-format',
        'stream-json',
        '--json-schema',
        json.dumps(OUTPUT_SCHEMA),
        '--permission-mode',
        'auto',
    ]
    if session_id:
        command.extend(['--resume', session_id])
    model = environment.get('CLAUDE_MODEL', '').strip()
    if model:
        if not re.fullmatch(r'[A-Za-z0-9._-]+', model):
            raise ValueError('CLAUDE_MODEL contains invalid characters')
        command.extend(['--model', model])
    command.append(prompt)
    agent_env = environment.copy()
    for secret_name in AGENT_SECRET_NAMES + ('COPILOT_GITHUB_TOKEN',):
        agent_env.pop(secret_name, None)
    timeout_seconds = int(environment.get('CLAUDE_TIMEOUT_SECONDS', '3600'))

    print('Claude: processing request', flush=True)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=agent_env,
        start_new_session=True,
    )
    output_lines = queue.Queue()

    def read_output():
        for output_line in process.stdout:
            output_lines.put(output_line)
        output_lines.put(None)

    threading.Thread(target=read_output, daemon=True).start()
    result = None
    unavailable = None
    plain_lines = []
    deadline = time.monotonic() + timeout_seconds

    def terminate_process_group():
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if process.poll() is None:
            process.wait()

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            terminate_process_group()
            raise RuntimeError(f'Claude CLI timed out after {timeout_seconds} seconds')
        try:
            line = output_lines.get(timeout=min(remaining, 1))
        except queue.Empty:
            if process.poll() is not None:
                continue
            continue
        if line is None:
            break
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            print(line.rstrip(), flush=True)
            plain_lines.append(line.rstrip())
            continue

        unavailable = unavailable or classify_event(event)
        if event.get('type') == 'assistant':
            message = event.get('message', {})
            for block in message.get('content', []):
                if block.get('type') == 'tool_use':
                    print('Claude: using tool ' + block.get('name', 'unknown'), flush=True)
        elif event.get('type') == 'result':
            result = event

    try:
        exit_code = process.wait(timeout=max(0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired as error:
        terminate_process_group()
        raise RuntimeError(f'Claude CLI timed out after {timeout_seconds} seconds') from error
    unavailable = unavailable or (classify_plain_text(plain_lines) if exit_code != 0 else None)
    if unavailable and (exit_code != 0 or result is None or result.get('is_error')):
        reason, message, resets_at = unavailable
        print('Claude: unavailable (' + reason + '): ' + message, flush=True)
        raise ClaudeUnavailable(reason, message, resets_at)
    if exit_code != 0:
        output_tail = '\n'.join(plain_lines)[-1500:]
        # stream-json errors arrive as a result event, not as plain text.
        if not output_tail and result is not None and isinstance(result.get('result'), str):
            output_tail = result['result'][-1500:]
        # Sessions live in the VM's home directory and are lost when it is recreated or when a
        # cached response replays an old id; the run summary already carries the context.
        if session_id and 'No conversation found' in output_tail:
            print('Claude: session ' + session_id + ' not found, starting a new session', flush=True)
            return run_claude_agent({**environment, 'CLAUDE_SESSION_ID': ''})
        raise RuntimeError('Claude CLI exited with status ' + str(exit_code) + (': ' + output_tail if output_tail else ''))
    if result is None:
        raise RuntimeError('Claude CLI did not return a result event')

    phase_result = result.get('structured_output')
    validate_phase_result(phase_result, 'Claude')

    print('Claude: response complete', flush=True)
    return {
        'agent_used': 'claude',
        'response': phase_result.get('response', ''),
        'run_summary': phase_result['run_summary'],
        'findings': phase_result.get('findings', []),
        'changes': phase_result.get('changes', []),
        'pull_request': phase_result.get('pull_request', {}),
        'session_id': result['session_id'],
    }
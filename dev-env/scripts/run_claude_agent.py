import json
import os
import queue
import signal
import subprocess
import threading
import time


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


def run_claude_agent(environment=None):
    environment = os.environ if environment is None else environment
    prompt = environment['CLAUDE_PROMPT']
    session_id = environment.get('CLAUDE_SESSION_ID', '').strip()
    run_summary = environment.get('CLAUDE_RUN_SUMMARY', '').strip()
    if run_summary:
        prompt = 'Previous workflow phase summary:\n' + run_summary + '\n\n' + prompt
    prompt += (
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
    command.append(prompt)
    agent_env = environment.copy()
    for secret_name in ('GH_TOKEN', 'GH_UPSTREAM_TOKEN', 'GH_PUBLIC_REPOS_TOKEN', 'GITHUB_TOKEN', 'BUILD_KITE_API_TOKEN'):
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
            continue

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
    if exit_code != 0:
        raise RuntimeError('Claude CLI exited with status ' + str(exit_code))
    if result is None:
        raise RuntimeError('Claude CLI did not return a result event')

    phase_result = result.get('structured_output')
    if not isinstance(phase_result, dict):
        raise RuntimeError('Claude CLI did not return structured output')
    if not isinstance(phase_result.get('run_summary'), str):
        raise RuntimeError('Claude structured output is missing run_summary')
    if not isinstance(phase_result.get('findings'), list):
        raise RuntimeError('Claude structured output is missing findings')
    if not isinstance(phase_result.get('changes'), list):
        raise RuntimeError('Claude structured output is missing changes')

    print('Claude: response complete', flush=True)
    return {
        'response': phase_result.get('response', ''),
        'run_summary': phase_result['run_summary'],
        'findings': phase_result.get('findings', []),
        'changes': phase_result.get('changes', []),
        'pull_request': phase_result.get('pull_request', {}),
        'session_id': result['session_id'],
    }
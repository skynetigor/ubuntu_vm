"""Runs GitHub Copilot CLI with the same contract as run_claude_agent (fallback when Claude is unavailable)."""

import json
import os
import queue
import re
import signal
import subprocess
import threading
import time

from run_claude_agent import (
    AGENT_SECRET_NAMES,
    COPILOT_SESSION_PREFIX,
    OUTPUT_SCHEMA,
    build_agent_prompt,
    validate_phase_result,
)

DEFAULT_COPILOT_MODEL = 'claude-sonnet-5.5'
# Mirrors the Claude runner's disallowed Bash commands.
DENIED_SHELL_COMMANDS = ('sudo', 'docker', 'gh', 'git commit', 'git push')


def _structured_output_instructions():
    return (
        '\n\nWhen you are done, your final message must be only a JSON object (no prose, no code fences) '
        'that validates against this JSON Schema:\n' + json.dumps(OUTPUT_SCHEMA)
    )


def extract_json_object(text):
    """Parses the final message as JSON, tolerating code fences or surrounding prose."""
    if not isinstance(text, str) or not text.strip():
        return None
    candidates = [text.strip()]
    candidates += re.findall(r'```(?:json)?\s*(\{.*?\})\s*```', text, flags=re.DOTALL)
    start, end = text.find('{'), text.rfind('}')
    if 0 <= start < end:
        candidates.append(text[start:end + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _run_copilot(command, env, cwd, timeout_seconds):
    print('Copilot: processing request', flush=True)
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        env=env, cwd=cwd, start_new_session=True,
    )
    output_lines = queue.Queue()

    def read_output():
        for output_line in process.stdout:
            output_lines.put(output_line)
        output_lines.put(None)

    threading.Thread(target=read_output, daemon=True).start()

    def terminate_process_group():
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                return
            try:
                process.wait(timeout=10)
                return
            except subprocess.TimeoutExpired:
                continue

    final_text = ''
    session_id = ''
    plain_lines = []
    deadline = time.monotonic() + timeout_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            terminate_process_group()
            raise RuntimeError(f'Copilot CLI timed out after {timeout_seconds} seconds')
        try:
            line = output_lines.get(timeout=min(remaining, 1))
        except queue.Empty:
            continue
        if line is None:
            break
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            print(line.rstrip(), flush=True)
            plain_lines.append(line.rstrip())
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get('type')
        data = event.get('data') or {}
        if kind == 'assistant.message':
            for tool_request in data.get('toolRequests') or []:
                print('Copilot: using tool ' + str(tool_request.get('name', 'unknown')), flush=True)
            if isinstance(data.get('content'), str) and data['content'].strip():
                final_text = data['content']
        elif kind == 'result':
            session_id = event.get('sessionId') or session_id
            usage = event.get('usage') or {}
            if 'premiumRequests' in usage:
                print('Copilot: premium requests used: ' + str(usage['premiumRequests']), flush=True)

    try:
        exit_code = process.wait(timeout=max(0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired as error:
        terminate_process_group()
        raise RuntimeError(f'Copilot CLI timed out after {timeout_seconds} seconds') from error
    return exit_code, final_text, session_id, plain_lines


def run_copilot_agent(environment=None):
    environment = os.environ if environment is None else environment
    if not environment.get('COPILOT_GITHUB_TOKEN', '').strip():
        raise RuntimeError(
            'COPILOT_GITHUB_TOKEN is not set on dev-vm; add a fine-grained PAT with the '
            '"Copilot Requests" permission to dev-env/env/copilot.env and recreate dev-vm'
        )
    session_id = environment.get('AGENT_SESSION_ID', '').strip()
    # Claude session ids cannot be resumed by Copilot; the run summary carries the context.
    resume_id = session_id[len(COPILOT_SESSION_PREFIX):] if session_id.startswith(COPILOT_SESSION_PREFIX) else ''
    prompt = build_agent_prompt(environment['AGENT_PROMPT'], environment.get('AGENT_RUN_SUMMARY', ''))
    prompt += _structured_output_instructions()

    model = environment.get('COPILOT_MODEL', '').strip() or DEFAULT_COPILOT_MODEL
    if not re.fullmatch(r'[A-Za-z0-9._-]+', model):
        raise ValueError('COPILOT_MODEL contains invalid characters')
    denied_tools = ['shell(' + name + ')' for name in DENIED_SHELL_COMMANDS]
    if environment.get('AGENT_DISALLOW_SHELL', '').lower() in {'true', '1'}:
        denied_tools.insert(0, 'shell')
    base_command = [
        'copilot',
        '--output-format', 'json',
        '--no-ask-user',
        '--allow-all-tools',
        '--allow-all-paths',
        '--allow-all-urls',
        # The built-in GitHub MCP server would act on GitHub with the token; mirrors Claude's `gh` ban.
        '--disable-builtin-mcps',
        '--secret-env-vars=COPILOT_GITHUB_TOKEN',
        '--model', model,
        *['--deny-tool=' + tool for tool in denied_tools],
    ]

    agent_env = environment.copy()
    # Copilot CLI would otherwise prefer GH_TOKEN/GITHUB_TOKEN; only the Copilot token may be used.
    for secret_name in AGENT_SECRET_NAMES:
        agent_env.pop(secret_name, None)
    timeout_seconds = int(environment.get('AGENT_TIMEOUT_SECONDS', '3600'))
    cwd = environment.get('AGENT_CWD') or os.getcwd()

    command = base_command + (['--resume=' + resume_id] if resume_id else []) + ['-p', prompt]
    exit_code, final_text, new_session_id, plain_lines = _run_copilot(command, agent_env, cwd, timeout_seconds)
    if exit_code != 0 and resume_id and not new_session_id:
        print('Copilot: session ' + resume_id + ' could not be resumed, starting a new session', flush=True)
        command = base_command + ['-p', prompt]
        exit_code, final_text, new_session_id, plain_lines = _run_copilot(command, agent_env, cwd, timeout_seconds)
    if exit_code != 0:
        output_tail = '\n'.join(plain_lines)[-1500:]
        raise RuntimeError('Copilot CLI exited with status ' + str(exit_code) + (': ' + output_tail if output_tail else ''))

    phase_result = extract_json_object(final_text)
    if phase_result is None and new_session_id:
        print('Copilot: final message was not JSON, asking for the structured result again', flush=True)
        repair_prompt = (
            'Your last message was not the required JSON object. Reply now with only that JSON object, '
            'nothing else.' + _structured_output_instructions()
        )
        command = base_command + ['--resume=' + new_session_id, '-p', repair_prompt]
        exit_code, final_text, _, plain_lines = _run_copilot(command, agent_env, cwd, timeout_seconds)
        if exit_code == 0:
            phase_result = extract_json_object(final_text)
    validate_phase_result(phase_result, 'Copilot')

    print('Copilot: response complete', flush=True)
    return {
        'agent_used': 'copilot',
        'response': phase_result.get('response', ''),
        'run_summary': phase_result['run_summary'],
        'findings': phase_result.get('findings', []),
        'changes': phase_result.get('changes', []),
        'pull_request': phase_result.get('pull_request', {}),
        'session_id': COPILOT_SESSION_PREFIX + new_session_id if new_session_id else '',
    }

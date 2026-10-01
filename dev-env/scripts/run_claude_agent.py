import json
import os
import subprocess


def run_claude_agent(environment=None):
    environment = os.environ if environment is None else environment
    prompt = environment['CLAUDE_PROMPT']
    session_id = environment.get('CLAUDE_SESSION_ID', '').strip()
    run_summary = environment.get('CLAUDE_RUN_SUMMARY', '').strip()
    if run_summary:
        prompt = 'Previous workflow phase summary:\n' + run_summary + '\n\n' + prompt
    prompt += (
        '\n\nReturn only a JSON object with keys `response` and `run_summary`. '
        '`run_summary` must be a concise durable handoff: decisions, findings, '
        'files changed, unresolved items, and next actions. Do not include secrets.'
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
        '--permission-mode',
        'auto',
    ]
    if session_id:
        command.extend(['--resume', session_id])
    command.append(prompt)
    agent_env = environment.copy()
    for secret_name in ('GH_TOKEN', 'GITHUB_TOKEN', 'BUILD_KITE_API_TOKEN'):
        agent_env.pop(secret_name, None)

    print('Claude: processing request', flush=True)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=agent_env,
    )
    result = None

    for line in process.stdout:
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

    exit_code = process.wait()
    if exit_code != 0:
        raise RuntimeError('Claude CLI exited with status ' + str(exit_code))
    if result is None:
        raise RuntimeError('Claude CLI did not return a result event')

    try:
        phase_result = json.loads(result['result'])
    except (KeyError, json.JSONDecodeError) as error:
        raise RuntimeError('Claude response was not the required JSON object') from error
    if not isinstance(phase_result, dict) or not isinstance(phase_result.get('run_summary'), str):
        raise RuntimeError('Claude response is missing the required run_summary')

    print('Claude: response complete', flush=True)
    return {
        'response': phase_result.get('response', ''),
        'run_summary': phase_result['run_summary'],
        'findings': phase_result.get('findings', []),
        'changes': phase_result.get('changes', []),
        'session_id': result['session_id'],
    }
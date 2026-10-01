import json
import os


def summarize_fixes(environment=None):
    environment = os.environ if environment is None else environment
    initial_agent_comments = json.loads(environment.get('INITIAL_AGENT_COMMENTS_JSON', '[]'))
    remaining_agent_comments = json.loads(environment.get('REMAINING_AGENT_COMMENTS_JSON', '[]'))
    other_agent_comments = json.loads(environment.get('OTHER_AGENT_COMMENTS_JSON', '[]'))
    initial_tests = json.loads(environment.get('INITIAL_TESTS_JSON', '[]'))
    remaining_tests = json.loads(environment.get('REMAINING_TESTS_JSON', '[]'))

    remaining_agent_keys = {
        (item.get('file'), item.get('line'), item.get('comment'))
        for item in remaining_agent_comments + other_agent_comments
    }
    fixed_agent_comments = [
        item for item in initial_agent_comments
        if (item.get('file'), item.get('line'), item.get('comment')) not in remaining_agent_keys
    ]

    remaining_test_projects = {item.get('project') for item in remaining_tests}
    fixed_tests = [item for item in initial_tests if item.get('project') not in remaining_test_projects]
    return {
        'fixed_agent_comments': fixed_agent_comments,
        'fixed_tests': fixed_tests,
    }
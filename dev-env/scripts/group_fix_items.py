import json
import os


def group_fix_items(environment=None, cwd=None):
    environment = os.environ if environment is None else environment
    cwd = os.getcwd() if cwd is None else cwd

    def load(name):
        return json.loads(environment.get(name) or '[]') or []

    projects = load('PROJECTS_JSON')
    root_by_id = {project['id']: project['source_root'] for project in projects}
    known_roots = sorted({project['source_root'] for project in projects}, key=len, reverse=True)
    manifest_cache = {}

    def project_root(path):
        if not path:
            return 'general'
        for root in known_roots:
            if path == root or path.startswith(root.rstrip('/') + '/'):
                return root
        directory = os.path.dirname(path)
        while directory:
            if directory not in manifest_cache:
                manifest_cache[directory] = os.path.isfile(os.path.join(cwd, directory, 'kibana.jsonc'))
            if manifest_cache[directory]:
                return directory
            directory = os.path.dirname(directory)
        return 'repository'

    groups = {}

    def add(root, item):
        groups.setdefault(root, []).append(item)

    for index, comment in enumerate(load('AGENT_COMMENTS_JSON')):
        add(project_root(comment.get('file')), {
            'item_id': f"review-{comment.get('id') or index}", 'kind': 'review_finding', **comment,
        })
    for failure in load('FAILED_TESTS_JSON'):
        project = failure.get('project')
        details = failure.get('failures') or []
        root = root_by_id.get(project) or next(
            (detail.get('source_root') for detail in details if detail.get('source_root')), None,
        )
        add(root or 'repository', {'item_id': f'test-{project}', 'kind': 'failing_tests', **failure})
    for result in load('LINT_FAILURES_JSON'):
        project = result.get('project')
        root = result.get('source_root') or root_by_id.get(project) or 'repository'
        add(root, {'item_id': f'lint-{project}', 'kind': 'lint_errors', **result})
    for comment in load('PR_COMMENTS_JSON'):
        add(project_root(comment.get('path')), {
            'item_id': f"pr-{comment.get('comment_id')}", 'kind': 'pr_comment', **comment,
        })
    for index, finding in enumerate(load('UI_FINDINGS_JSON')):
        add(project_root(finding.get('file')), {'item_id': f'ui-{index}', 'kind': 'ui_finding', **finding})

    result = [
        {'group': root, 'items': items, 'kinds': sorted({item['kind'] for item in items})}
        for root, items in sorted(groups.items())
    ]
    print(f'{sum(len(group["items"]) for group in result)} fix items in {len(result)} groups', flush=True)
    return {'groups': result, 'group_count': len(result)}

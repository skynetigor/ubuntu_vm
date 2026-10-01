import json
import os
import re
import subprocess


def write_pr_comments(environment=None):
    environment = os.environ if environment is None else environment
    if not environment.get('GH_TOKEN'):
        raise RuntimeError('GH_TOKEN is required for PR comment writes')

    pr = json.loads(environment['PR_CONTEXT_JSON'])
    analysis = json.loads(environment['COMMENT_ANALYSIS_JSON'])
    fixes = json.loads(environment['COMMENT_FIXES_JSON'])
    eligible = set(json.loads(environment['FIXABLE_SEVERITIES']))
    owner, repo, number = pr['owner'], pr['repo'], pr['number']
    commit_sha = environment['COMMIT_SHA']

    def gh_api(*args):
        result = subprocess.run(
            ['gh', 'api', *args], text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if result.returncode:
            raise RuntimeError('GitHub API request failed: ' + result.stderr[-2500:])
        return json.loads(result.stdout) if result.stdout.strip() else {}

    fresh_comments = []
    page = 1
    while True:
        batch = gh_api(f'repos/{owner}/{repo}/pulls/{number}/comments?per_page=100&page={page}')
        fresh_comments.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    comments_by_id = {str(item['id']): item for item in fresh_comments}
    threads_by_comment = {
        str(item['id']): item
        for item in pr.get('comments', [])
        if item.get('thread_id')
    }
    analysis_by_id = {str(item.get('comment_id')): item for item in analysis}
    outcomes = []

    for fix in fixes:
        comment_id = str(fix.get('comment_id', ''))
        decision = analysis_by_id.get(comment_id, {})
        if (not comment_id or decision.get('already_fixed') is not False
                or decision.get('severity') not in eligible
                or fix.get('fixed') is not True):
            continue
        original = comments_by_id.get(comment_id)
        thread = threads_by_comment.get(comment_id)
        thread_id = thread and thread.get('thread_id')
        if not original or not thread_id:
            outcomes.append({'comment_id': comment_id, 'status': 'skipped_missing_thread'})
            continue
        if not re.fullmatch(r'PRRT_[A-Za-z0-9]+', thread_id):
            outcomes.append({'comment_id': comment_id, 'status': 'skipped_invalid_thread_id'})
            continue

        thread_query = (
            'query { node(id: "' + thread_id + '") '
            '{ ... on PullRequestReviewThread { isResolved } } }'
        )
        thread_state = gh_api('graphql', '-f', 'query=' + thread_query)
        node = thread_state.get('data', {}).get('node') or {}
        if node.get('isResolved') is True:
            outcomes.append({'comment_id': comment_id, 'status': 'skipped_already_resolved'})
            continue

        marker = '<!-- workflow-review-comment:' + comment_id + ' -->'
        existing_reply = any(
            str(item.get('in_reply_to_id')) == comment_id and marker in (item.get('body') or '')
            for item in fresh_comments
        )
        if not existing_reply:
            body = (fix.get('reply') or ('Fixed in commit ' + commit_sha + '.')).strip()
            body += '\n\n' + marker
            gh_api(
                '--method', 'POST', f'repos/{owner}/{repo}/pulls/{number}/comments',
                '-f', 'body=' + body, '-F', 'in_reply_to=' + comment_id,
            )

        if node.get('isResolved') is not True:
            mutation = (
                'mutation($threadId:ID!) { resolveReviewThread(input:{threadId:$threadId}) '
                '{ thread { isResolved } } }'
            )
            gh_api('graphql', '-f', 'query=' + mutation, '-F', 'threadId=' + thread_id)
        outcomes.append({
            'comment_id': comment_id,
            'status': 'replied_and_resolved' if not existing_reply else 'reply_exists_resolved',
        })

    return {'outcomes': outcomes, 'commit_sha': commit_sha}
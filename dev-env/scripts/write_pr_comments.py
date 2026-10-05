import json
import os
import re
import subprocess


def write_pr_comments(environment=None):
    environment = os.environ if environment is None else environment
    pr = json.loads(environment['PR_CONTEXT_JSON'])
    analysis = json.loads(environment['COMMENT_ANALYSIS_JSON'])
    fixes = json.loads(environment['COMMENT_FIXES_JSON'])
    eligible = set(json.loads(environment['FIXABLE_SEVERITIES']))
    owner, repo, number = pr['owner'], pr['repo'], pr['number']
    commit_sha = environment['COMMIT_SHA']
    fix_pr_url = environment.get('FIX_PR_URL', '').strip()

    def gh_api(*args):
        try:
            result = subprocess.run(
                ['gh', 'api', *args], text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=90,
                env={**os.environ, **environment},
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError('GitHub API request timed out after 90 seconds') from error
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
    summary_items = []

    for fix in fixes:
        comment_id = str(fix.get('comment_id', ''))
        decision = analysis_by_id.get(comment_id, {})
        status = decision.get('status') or ('fixed_in_pr' if decision.get('already_fixed') is True else 'open')
        # Comments already fixed by the PR author were not fixed by this run.
        if (not comment_id or status not in {'open', 'fixed_locally'}
                or decision.get('severity') not in eligible
                or fix.get('fixed') is not True):
            continue
        original = comments_by_id.get(comment_id)
        thread = threads_by_comment.get(comment_id)
        thread_id = thread and thread.get('thread_id')
        if not original or not thread_id:
            outcomes.append({'comment_id': comment_id, 'status': 'skipped_missing_thread'})
            continue
        if not re.fullmatch(r'PRRT_[A-Za-z0-9_-]+', thread_id):
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
            body = (fix.get('reply') or 'Fixed.').strip()
            body += f'\n\nFix: {fix_pr_url}' if fix_pr_url else f' ({commit_sha[:10]})'
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
        summary_items.append((original, (fix.get('reply') or 'Fixed.').strip()))

    # Replies sit in resolved threads, which GitHub folds away, so also post a visible summary.
    summary_posted = False
    if summary_items:
        summary_marker = '<!-- workflow-fix-summary:' + commit_sha + ' -->'
        issue_comments = gh_api(f'repos/{owner}/{repo}/issues/{number}/comments?per_page=100')
        if not any(summary_marker in (item.get('body') or '') for item in issue_comments):
            lines = ['Fixed review comments' + (f' in {fix_pr_url}' if fix_pr_url else f' ({commit_sha[:10]})') + ':', '']
            for original, reply in summary_items:
                location = original.get('path', '').split('/')[-1]
                line = original.get('original_line') or original.get('line')
                if line:
                    location += f':{line}'
                lines.append(f"- [{location}]({original.get('html_url')}): {reply}")
            lines += ['', summary_marker]
            gh_api(
                '--method', 'POST', f'repos/{owner}/{repo}/issues/{number}/comments',
                '-f', 'body=' + '\n'.join(lines),
            )
            summary_posted = True

    return {'outcomes': outcomes, 'commit_sha': commit_sha, 'summary_posted': summary_posted}
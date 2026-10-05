import json
import os


def build_fixed_pr_comment_actions(environment=None):
    environment = os.environ if environment is None else environment
    to_fix = json.loads(environment.get('PR_COMMENTS_TO_FIX_JSON', '[]'))
    fixed_locally = json.loads(environment.get('PR_COMMENTS_FIXED_LOCALLY_JSON', '[]'))
    fix_results = json.loads(environment.get('PR_FIX_RESULTS_JSON', '[]'))

    reported_fixed_ids = {
        str(result.get('comment_id'))
        for result in fix_results
        if isinstance(result, dict) and result.get('status') in {'fixed', 'already_fixed'}
    }
    replies = {
        str(result.get('comment_id')): str(result.get('reply') or '').strip()
        for result in fix_results
        if isinstance(result, dict) and result.get('comment_id')
    }
    fixed_comments = list(fixed_locally) + [
        comment for comment in to_fix if str(comment.get('comment_id')) in reported_fixed_ids
    ]
    fixed_ids = {str(comment.get('comment_id')) for comment in fixed_comments}
    remaining_comments = [comment for comment in to_fix if str(comment.get('comment_id')) not in fixed_ids]

    actions = []
    seen = set()
    for comment in fixed_comments:
        comment_id = str(comment.get('comment_id') or '')
        if not comment_id or comment_id in seen:
            continue
        seen.add(comment_id)
        actions.append({
            'comment_id': comment_id,
            'fixed': True,
            'reply': replies.get(comment_id) or 'Fixed.',
        })
    return {
        'fixes': actions,
        'fixed_comments': fixed_comments,
        'remaining_comments': remaining_comments,
    }

import json
import os


def build_fixed_pr_comment_actions(environment=None):
    environment = os.environ if environment is None else environment
    to_fix = json.loads(environment.get('PR_COMMENTS_TO_FIX_JSON', '[]'))
    fixed_locally = json.loads(environment.get('PR_COMMENTS_FIXED_LOCALLY_JSON', '[]'))
    fix_results = json.loads(environment.get('PR_FIX_RESULTS_JSON', '[]'))
    other_comments = json.loads(environment.get('OTHER_PR_COMMENTS_JSON', '[]'))
    # Batched fix calls identify PR comments by item_id `pr-<comment_id>`.
    fix_results = [
        {**result, 'comment_id': result.get('comment_id') or str(result.get('item_id', ''))[3:]}
        if isinstance(result, dict) and str(result.get('item_id', '')).startswith('pr-') else result
        for result in fix_results
    ]

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
            'url': comment.get('comment_url') or comment.get('url'),
        })
    excluded = [
        comment for comment in other_comments
        if not comment.get('is_resolved') and comment.get('status') in {'open', 'unclassified', 'fixed_locally'}
    ]
    proposed_replies = list(actions)
    for comment in excluded:
        reply = str(comment.get('reply') or '').strip()
        if comment.get('status') == 'open' and reply:
            proposed_replies.append({
                'comment_id': str(comment['comment_id']),
                'fixed': False,
                'reply': reply,
                'url': comment.get('comment_url') or comment.get('url'),
            })

    review_lines = []
    if proposed_replies:
        review_lines = [
            '## Proposed review replies',
            '',
            'Approval authorizes these exact replies. If there is a fix PR, replies wait for its merge. '
            'Explanations for unchanged code leave the thread open.',
            '',
        ]
        for action in proposed_replies:
            label = 'Fix' if action['fixed'] else 'No code change'
            url = action.get('url')
            reference = f'[{action["comment_id"]}]({url})' if url else action['comment_id']
            review_lines.extend([f'### {reference} - {label}', '', action['reply'], ''])
    if excluded:
        review_lines.extend(['## Excluded from automatic fixes', ''])
        for comment in excluded:
            url = comment.get('comment_url') or comment.get('url')
            reference = f'[{comment["comment_id"]}]({url})' if url else comment['comment_id']
            review_lines.extend([
                f'- {reference} ({comment.get("severity") or "unclassified"}): '
                f'{comment.get("exclusion_reason") or "Manual review required."} '
                f'{comment.get("rationale") or ""}'.rstrip(),
            ])
    return {
        'fixes': actions,
        'replies': proposed_replies,
        'review_details': '\n'.join(review_lines).strip(),
        'excluded_comments': excluded,
        'fixed_comments': fixed_comments,
        'remaining_comments': remaining_comments,
    }


def summarize_pr_comment_followup(environment=None):
    environment = os.environ if environment is None else environment
    initial = json.loads(environment['INITIAL_PR_CONTEXT_JSON'])
    final = json.loads(environment['FINAL_PR_CONTEXT_JSON'])
    excluded = json.loads(environment['EXCLUDED_PR_COMMENTS_JSON'])
    result = json.loads(environment.get('COMMENT_RESOLUTION_RESULT_JSON', '{}'))
    final_by_id = {str(comment['id']): comment for comment in final.get('comments', [])}
    initial_ids = {str(comment['id']) for comment in initial.get('comments', [])}
    excluded = [
        comment for comment in excluded
        if str(comment['comment_id']) in final_by_id
        and not final_by_id[str(comment['comment_id'])].get('is_resolved')
    ]
    outcomes = {str(item['comment_id']): item['status'] for item in result.get('outcomes', [])}
    unposted_replies = [
        item for item in result.get('outcomes', [])
        if item['status'].startswith('skipped_') and item['status'] != 'skipped_already_resolved'
    ]
    for comment in excluded:
        comment['reply_status'] = outcomes.get(str(comment['comment_id']), 'not_posted')
    new_comments = [
        {
            'comment_id': str(comment['id']),
            'comment': comment.get('body', ''),
            'comment_url': comment.get('comment_url') or comment.get('url'),
            'path': comment.get('path'),
            'line': comment.get('line'),
            'author': comment.get('author'),
            'in_reply_to_id': comment.get('in_reply_to_id'),
            'status': 'not_analyzed',
            'rationale': 'Arrived after the comment analysis; another review pass is required.',
        }
        for comment in final.get('comments', [])
        if str(comment['id']) not in initial_ids
        and not comment.get('is_resolved')
        and comment.get('author') != final.get('author')
    ]
    return {
        'excluded_comments': excluded,
        'new_comments': new_comments,
        'unposted_replies': unposted_replies,
        'status': (
            'new_comments_need_review' if new_comments
            else 'replies_need_attention' if unposted_replies
            else 'completed_with_exclusions' if excluded
            else 'completed'
        ),
    }

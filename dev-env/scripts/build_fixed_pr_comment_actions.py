import json
import os


def build_fixed_pr_comment_actions(environment=None):
    environment = os.environ if environment is None else environment
    initial_comments = json.loads(environment.get('INITIAL_PR_COMMENTS_JSON', '[]'))
    final_other_comments = json.loads(environment.get('OTHER_PR_COMMENTS_JSON', '[]'))
    confirmed_fixed_ids = {
        str(comment.get('comment_id'))
        for comment in final_other_comments
        if comment.get('already_fixed') is True
    }
    actions = []
    seen = set()
    for comment in initial_comments:
        comment_id = comment.get('comment_id')
        if (
            comment.get('already_fixed') is True
            or not comment_id
            or str(comment_id) not in confirmed_fixed_ids
            or comment_id in seen
        ):
            continue
        seen.add(comment_id)
        actions.append({
            'comment_id': comment_id,
            'fixed': True,
            'reply': 'Addressed by the validated changes in this workflow run.',
        })
    return {'fixes': actions}
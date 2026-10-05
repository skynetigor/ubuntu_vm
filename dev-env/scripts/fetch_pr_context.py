import json
import os
import subprocess


def fetch_pr_context(environment=None):
    environment = os.environ if environment is None else environment
    owner = environment['PR_OWNER']
    repo = environment['PR_REPO']
    number = environment['PR_NUMBER']

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
            raise RuntimeError('GitHub API request failed: ' + result.stderr[-3000:])
        return json.loads(result.stdout)

    pr = gh_api(f'repos/{owner}/{repo}/pulls/{number}')
    comments = []
    page = 1
    while True:
        batch = gh_api(f'repos/{owner}/{repo}/pulls/{number}/comments?per_page=100&page={page}')
        comments.extend(batch)
        if len(batch) < 100:
            break
        page += 1
        if len(comments) > int(environment['MAX_PR_COMMENTS']):
            raise RuntimeError('PR exceeds MAX_PR_COMMENTS; summarize/review manually')

    query = '''query($owner:String!, $name:String!, $number:Int!, $after:String) {
      repository(owner:$owner, name:$name) {
        pullRequest(number:$number) {
          reviewThreads(first:100, after:$after) {
            nodes {
              id isResolved
              comments(first:100) {
                nodes { databaseId body path line originalLine url author { login } }
              }
            }
            pageInfo { hasNextPage endCursor }
          }
        }
      }
    }'''
    threads = []
    cursor = None
    while True:
        args = [
            'graphql', '-f', 'query=' + query,
            '-F', 'owner=' + owner, '-F', 'name=' + repo,
            '-F', 'number=' + number,
        ]
        if cursor:
            args.extend(['-F', 'after=' + cursor])
        page_data = gh_api(*args)
        pull = page_data.get('data', {}).get('repository', {}).get('pullRequest')
        if pull is None:
            raise RuntimeError('GitHub did not return PR review threads')
        connection = pull['reviewThreads']
        threads.extend(connection['nodes'])
        page_info = connection['pageInfo']
        if len(threads) > int(environment['MAX_PR_COMMENTS']):
            raise RuntimeError('PR exceeds MAX_PR_COMMENTS; summarize/review manually')
        if not page_info['hasNextPage']:
            break
        cursor = page_info['endCursor']

    comment_to_thread = {}
    for thread in threads:
        for comment in thread['comments']['nodes']:
            comment_to_thread[comment['databaseId']] = {
                'thread_id': thread['id'],
                'is_resolved': thread['isResolved'],
            }

    normalized_comments = []
    max_body_chars = int(environment.get('MAX_COMMENT_BODY_CHARS', '0'))
    for comment in comments:
        comment_url = comment.get('html_url') or (
            f'https://github.com/{owner}/{repo}/pull/{number}'
            f'#discussion_r{comment["id"]}'
        )
        normalized_comments.append({
            'id': comment['id'],
            'in_reply_to_id': comment.get('in_reply_to_id'),
            'body': comment.get('body', '')[:max_body_chars or None],
            'path': comment.get('path'),
            'line': comment.get('line') or comment.get('original_line'),
            'url': comment_url,
            'comment_url': comment_url,
            'author': comment.get('user', {}).get('login'),
            **comment_to_thread.get(comment['id'], {}),
        })

    reviews = []
    if environment.get('INCLUDE_REVIEWS', '').lower() == 'true':
        page = 1
        while True:
            batch = gh_api(f'repos/{owner}/{repo}/pulls/{number}/reviews?per_page=100&page={page}')
            reviews.extend(
                {
                    'id': review['id'],
                    'author': (review.get('user') or {}).get('login'),
                    'state': review.get('state'),
                    'body': (review.get('body') or '')[:max_body_chars or None],
                }
                for review in batch
                if (review.get('body') or '').strip()
            )
            if len(batch) < 100:
                break
            page += 1

    return {
        'owner': owner,
        'repo': repo,
        'number': int(number),
        'head_repo': pr['head']['repo']['full_name'] if pr.get('head', {}).get('repo') else None,
        'head_ref': pr['head']['ref'],
        'head_sha': pr['head']['sha'],
        'comments': normalized_comments,
        'reviews': reviews,
    }
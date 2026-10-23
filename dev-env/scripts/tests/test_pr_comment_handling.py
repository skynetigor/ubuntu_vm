import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_fixed_pr_comment_actions import build_fixed_pr_comment_actions, summarize_pr_comment_followup
from create_fix_pull_request import create_fix_pull_request
from format_slack_summary import format_slack_summary
from summarize_review import summarize_review
from write_pr_comments import write_pr_comments


def comment(comment_id, **values):
    return {
        'id': comment_id,
        'body': 'Review request',
        'author': 'reviewer',
        'path': 'client.ts',
        'line': 10,
        'url': f'https://github.com/owner/repo/pull/1#discussion_r{comment_id}',
        'thread_id': f'PRRT_thread{comment_id}',
        'is_resolved': False,
        **values,
    }


def finding(comment_id, **values):
    return {
        'comment_id': str(comment_id),
        'severity': 'low',
        'status': 'open',
        'rationale': 'Narrow impact.',
        'reply': 'Leaving this unchanged here because the fallback already handles it.',
        **values,
    }


class CommentPartitionTests(unittest.TestCase):
    def summarize(self, comments, analysis):
        return summarize_review({
            'FIXABLE_SEVERITIES': '["high", "medium"]',
            'PR_COMMENTS_JSON': json.dumps(comments),
            'PR_ANALYSIS_JSON': json.dumps(analysis),
        })

    def test_only_high_medium_roots_are_fixed_and_replies_remain_context(self):
        comments = [
            comment(1), comment(2), comment(3, in_reply_to_id=2, author='author'),
            comment(4, is_resolved=True), comment(5),
        ]
        result = self.summarize(comments, [
            finding(1, severity='medium'), finding(2),
            finding(3, severity='high'), finding(4, severity='high'),
        ])
        self.assertEqual([c['comment_id'] for c in result['pr_comments_to_fix']], ['1'])
        others = {c['comment_id']: c for c in result['other_pr_comments']}
        self.assertEqual(set(others), {'2', '4', '5'})
        self.assertEqual(others['2']['replies'][0]['id'], 3)
        self.assertIn('high/medium', others['2']['exclusion_reason'])
        self.assertEqual(others['5']['status'], 'unclassified')
        self.assertIn('manual review', others['5']['exclusion_reason'])

    def test_exclusions_do_not_extend_the_automatic_fix_loop(self):
        result = self.summarize([comment(1)], [finding(1)])
        self.assertFalse(result['needs_work'])
        self.assertEqual(len(result['other_pr_comments']), 1)

    def test_invalid_status_is_reported_instead_of_treated_as_fixed(self):
        result = self.summarize([comment(1)], [finding(1, severity='medium', status='unknown')])
        self.assertEqual(result['other_pr_comments'][0]['status'], 'unclassified')
        self.assertIn('Invalid classification', result['other_pr_comments'][0]['exclusion_reason'])


class CommentActionTests(unittest.TestCase):
    def test_explanations_are_separate_from_fixed_counts_and_preview_is_verbatim(self):
        result = build_fixed_pr_comment_actions({
            'PR_COMMENTS_TO_FIX_JSON': json.dumps([{'comment_id': '1'}]),
            'PR_FIX_RESULTS_JSON': json.dumps([
                {'item_id': 'pr-1', 'status': 'fixed', 'reply': 'Moved the check.'},
            ]),
            'OTHER_PR_COMMENTS_JSON': json.dumps([
                {**finding(2), 'exclusion_reason': 'low is excluded.', 'comment_url': 'https://example.test/2'},
                {**finding(3, reply=''), 'exclusion_reason': 'Author already answered.'},
                {**finding(4), 'is_resolved': True},
                {**finding(5, status='unclassified', reply=''), 'exclusion_reason': 'No classification.'},
            ]),
        })
        self.assertEqual(len(result['fixed_comments']), 1)
        self.assertEqual([r['fixed'] for r in result['replies']], [True, False])
        self.assertEqual([c['comment_id'] for c in result['excluded_comments']], ['2', '3', '5'])
        self.assertIn('Moved the check.', result['review_details'])
        self.assertIn(finding(2)['reply'], result['review_details'])
        self.assertIn('Author already answered.', result['review_details'])
        self.assertIn('No classification.', result['review_details'])

    def test_final_refresh_detects_new_reviewer_comments_and_ignores_own_reply(self):
        roots = [comment(1), comment(2)]
        result = summarize_pr_comment_followup({
            'INITIAL_PR_CONTEXT_JSON': json.dumps({'comments': roots}),
            'FINAL_PR_CONTEXT_JSON': json.dumps({
                'author': 'author',
                'comments': [
                    comment(1, is_resolved=True), comment(2),
                    comment(3, author='review-bot'), comment(4, in_reply_to_id=2),
                    comment(5, in_reply_to_id=1, author='author'),
                ],
            }),
            'EXCLUDED_PR_COMMENTS_JSON': json.dumps([finding(1), finding(2)]),
            'COMMENT_RESOLUTION_RESULT_JSON': json.dumps({
                'outcomes': [{'comment_id': '2', 'status': 'replied_only'}],
            }),
        })
        self.assertEqual([c['comment_id'] for c in result['excluded_comments']], ['2'])
        self.assertEqual(result['excluded_comments'][0]['reply_status'], 'replied_only')
        self.assertEqual([c['comment_id'] for c in result['new_comments']], ['3', '4'])
        self.assertEqual(result['status'], 'new_comments_need_review')

    def test_all_exclusions_are_retained_in_the_durable_report(self):
        comments = [
            {**finding(i, reply=''), 'exclusion_reason': f'Excluded request {i}.'}
            for i in range(1, 31)
        ]
        result = build_fixed_pr_comment_actions({'OTHER_PR_COMMENTS_JSON': json.dumps(comments)})
        self.assertEqual(len(result['excluded_comments']), 30)
        for i in range(1, 31):
            self.assertIn(f'Excluded request {i}.', result['review_details'])

    def test_skipped_replies_require_attention_even_without_new_comments(self):
        result = summarize_pr_comment_followup({
            'INITIAL_PR_CONTEXT_JSON': json.dumps({'comments': [comment(1)]}),
            'FINAL_PR_CONTEXT_JSON': json.dumps({'author': 'author', 'comments': [comment(1)]}),
            'EXCLUDED_PR_COMMENTS_JSON': '[]',
            'COMMENT_RESOLUTION_RESULT_JSON': json.dumps({
                'outcomes': [{'comment_id': '1', 'status': 'skipped_missing_thread'}],
            }),
        })
        self.assertEqual(result['status'], 'replies_need_attention')
        self.assertEqual(len(result['unposted_replies']), 1)

    def test_explained_but_unfixed_thread_stays_in_excluded_report(self):
        result = summarize_pr_comment_followup({
            'INITIAL_PR_CONTEXT_JSON': json.dumps({'comments': [comment(1)]}),
            'FINAL_PR_CONTEXT_JSON': json.dumps({'author': 'author', 'comments': [comment(1)]}),
            'EXCLUDED_PR_COMMENTS_JSON': json.dumps([finding(1)]),
            'COMMENT_RESOLUTION_RESULT_JSON': json.dumps({
                'outcomes': [{'comment_id': '1', 'status': 'replied_only'}],
            }),
        })
        self.assertEqual(result['status'], 'completed_with_exclusions')
        self.assertEqual(result['excluded_comments'][0]['reply_status'], 'replied_only')


class CommentWriteTests(unittest.TestCase):
    def run_writer(self, fixed=False, fresh=None, resolved=False, confirm_resolution=True, reply='Approved reply.'):
        root = comment(1)
        calls = []

        def gh_run(args, **kwargs):
            calls.append(args)
            if 'graphql' in args:
                if any('mutation(' in arg for arg in args):
                    data = {'data': {'resolveReviewThread': {'thread': {'isResolved': confirm_resolution}}}}
                else:
                    data = {'data': {'node': {'isResolved': resolved}}}
            elif '--method' in args:
                data = {'id': 99}
            elif any('/issues/' in arg for arg in args):
                data = []
            else:
                data = [root] if fresh is None else fresh
            return SimpleNamespace(returncode=0, stdout=json.dumps(data), stderr='')

        env = {
            'PR_CONTEXT_JSON': json.dumps({
                'owner': 'owner', 'repo': 'repo', 'number': 1, 'comments': [root],
            }),
            'COMMENT_ANALYSIS_JSON': json.dumps([finding(1, severity='medium' if fixed else 'low')]),
            'COMMENT_FIXES_JSON': json.dumps([{'comment_id': '1', 'fixed': fixed, 'reply': reply}]),
            'FIXABLE_SEVERITIES': '["high", "medium"]',
            'COMMIT_SHA': 'a' * 40,
            'FIX_PR_URL': 'https://github.com/owner/repo/pull/2',
        }
        with patch('write_pr_comments.subprocess.run', side_effect=gh_run):
            result = write_pr_comments(env)
        return result, calls

    def test_approved_explanation_posts_without_resolving_or_claiming_a_fix(self):
        result, calls = self.run_writer()
        self.assertEqual(result['outcomes'][0]['status'], 'replied_only')
        self.assertFalse(result['summary_posted'])
        self.assertFalse(any('mutation(' in arg for call in calls for arg in call))
        bodies = [arg for call in calls for arg in call if arg.startswith('body=')]
        self.assertEqual(bodies, ['body=Approved reply.\n\n<!-- workflow-review-comment:1 -->'])

    def test_fixed_medium_comment_is_replied_to_and_resolved(self):
        result, calls = self.run_writer(fixed=True)
        self.assertEqual(result['outcomes'][0]['status'], 'replied_and_resolved')
        self.assertTrue(any('mutation(' in arg for call in calls for arg in call))

    def test_empty_explanation_is_reported_as_ineligible(self):
        result, calls = self.run_writer(reply='')
        self.assertEqual(result['skipped_count'], 1)
        self.assertFalse(any('--method' in call for call in calls))

    def test_exact_existing_explanation_is_not_posted_twice(self):
        reply = comment(2, in_reply_to_id=1, body='Approved reply.\n\n<!-- workflow-review-comment:1 -->')
        result, calls = self.run_writer(fresh=[comment(1), reply])
        self.assertEqual(result['outcomes'][0]['status'], 'reply_exists')
        self.assertFalse(any('--method' in call for call in calls))

    def test_new_thread_reply_blocks_stale_approved_response(self):
        result, calls = self.run_writer(fresh=[comment(1), comment(2, in_reply_to_id=1)])
        self.assertEqual(result['outcomes'][0]['status'], 'skipped_new_thread_reply')
        self.assertEqual(result['skipped_count'], 1)
        self.assertFalse(any('--method' in call for call in calls))

    def test_resolved_thread_does_not_receive_a_reply(self):
        result, calls = self.run_writer(resolved=True)
        self.assertEqual(result['outcomes'][0]['status'], 'skipped_already_resolved')
        self.assertFalse(any('--method' in call for call in calls))

    def test_unconfirmed_resolution_is_an_error(self):
        with self.assertRaisesRegex(RuntimeError, 'did not confirm resolution'):
            self.run_writer(fixed=True, confirm_resolution=False)


class PreviewAndSummaryTests(unittest.TestCase):
    def test_preview_pr_body_contains_exact_proposals(self):
        env = {
            'GH_TOKEN': 'unit-test-token',
            'PUBLISH_RESULT_JSON': json.dumps({
                'fork_repository': 'owner/repo', 'fix_branch': 'fix', 'base_branch': 'pr',
            }),
            'PR_DRAFT_JSON': json.dumps({'title': 'Fix checks', 'body': 'Code changes.'}),
            'COMMENT_REVIEW': 'Excluded comment 2.\nProposed reply: leave unchanged.',
        }
        with patch('create_fix_pull_request.urllib.request.urlopen', side_effect=[
            io.StringIO('[]'),
            io.StringIO(json.dumps({'number': 2, 'html_url': 'https://github.com/owner/repo/pull/2'})),
        ]) as open_url:
            result = create_fix_pull_request(env)
        sent = json.loads(open_url.call_args_list[1].args[0].data)
        self.assertEqual(sent['body'], 'Code changes.\n\n' + env['COMMENT_REVIEW'])
        self.assertEqual(result['body'], sent['body'])

    def test_existing_preview_is_updated_before_approval(self):
        env = {
            'GH_TOKEN': 'unit-test-token',
            'PUBLISH_RESULT_JSON': json.dumps({
                'fork_repository': 'owner/repo', 'fix_branch': 'fix', 'base_branch': 'pr',
            }),
            'PR_DRAFT_JSON': json.dumps({'title': 'Fix checks', 'body': 'Code changes.'}),
            'COMMENT_REVIEW': 'Exact proposed explanation.',
        }
        pr = {'number': 2, 'html_url': 'https://github.com/owner/repo/pull/2', 'body': 'Old preview.'}
        with patch('create_fix_pull_request.urllib.request.urlopen', side_effect=[
            io.StringIO(json.dumps([pr])),
            io.StringIO(json.dumps({**pr, 'body': 'Code changes.\n\nExact proposed explanation.'})),
        ]) as open_url:
            result = create_fix_pull_request(env)
        self.assertEqual(open_url.call_args_list[1].args[0].method, 'PATCH')
        self.assertIn(env['COMMENT_REVIEW'], result['body'])

    def test_proposed_replies_are_not_silently_truncated_to_fit_a_pr(self):
        with patch('create_fix_pull_request.urllib.request.urlopen') as open_url:
            with self.assertRaisesRegex(RuntimeError, 'body limit'):
                create_fix_pull_request({
                    'GH_TOKEN': 'unit-test-token',
                    'PUBLISH_RESULT_JSON': json.dumps({
                        'fork_repository': 'owner/repo', 'fix_branch': 'fix', 'base_branch': 'pr',
                    }),
                    'PR_DRAFT_JSON': json.dumps({'title': 'Fix checks', 'body': 'Code changes.'}),
                    'COMMENT_REVIEW': 'x' * 65536,
                })
        open_url.assert_not_called()

    def summary(self, **values):
        return format_slack_summary({
            'PUBLIC_URL': 'https://example.test',
            'EXECUTION_ID': 'execution',
            'NEEDS_WORK': 'false',
            'PR_CONTEXT_JSON': '{}',
            **values,
        })['message']

    def test_exclusions_never_get_a_clean_headline(self):
        message = self.summary(EXCLUDED_PR_COMMENTS_JSON=json.dumps([
            {**finding(2), 'exclusion_reason': 'low is excluded.'},
        ]))
        self.assertIn('Completed with excluded PR comments', message)
        self.assertIn('1 excluded', message)
        self.assertIn('Narrow impact.', message)
        self.assertNotIn('white_check_mark: Clean', message)
        self.assertIn('execution output', message)

    def test_new_comments_need_another_pass(self):
        message = self.summary(NEW_PR_COMMENTS_JSON=json.dumps([finding(2)]))
        self.assertIn('Needs work', message)
        self.assertIn('1 arrived after analysis', message)
        self.assertIn('New, not analyzed', message)

    def test_clean_run_stays_clean(self):
        self.assertIn('white_check_mark: Clean', self.summary())


if __name__ == '__main__':
    unittest.main()

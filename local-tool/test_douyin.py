"""Read-only Douyin adapter boundaries; no real account or network requests."""
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from research import Research,normalize_item
import research_douyin as dy
from research_dy_worker import public_item,http_error_code


def raw(likes=50000):
    return {'aweme_id':'7546165781764033819','desc':'公开汽车作品','author':{'nickname':'示例作者'},
            'create_time':1757000000,'statistics':{'digg_count':likes,'play_count':0,'comment_count':0,'collect_count':17,'share_count':9},
            'video':{'cover':{'url_list':['https://example.com/cover.jpg']}}}


class DouyinContract(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.state=Path(self.tmp.name);self.r=Research(self.state)
        self.python=self.state/'isolated-python';self.python.touch()
        self.runtime=patch('research_douyin.PYTHON',self.python);self.runtime.start()
    def tearDown(self):self.runtime.stop();self.tmp.cleanup()

    def ready(self):dy.save_state(dy.state_root(self.state),verified=True,status='ready',commit=dy.COMMIT)

    def test_public_fields_preserve_zero_missing_and_actual_integer_likes(self):
        item=normalize_item(public_item(raw()),'douyin','dy-cli-readonly')
        self.assertEqual(item['metrics'],{'plays':None,'likes':50000,'comments':0,'favorites':17,'shares':9})
        self.assertEqual(item['author'],'示例作者')
        self.assertEqual(item['cover'],'https://example.com/cover.jpg')
        for value in (None,False,-1,'5万',1.5,9007199254740992):
            self.assertIsNone(public_item(raw(value))['metrics']['likes'])
        self.assertIsNone(public_item({'aweme_id':'not-a-video'}))

    def test_installed_or_cookie_alone_is_not_a_verified_collector(self):
        root=dy.state_root(self.state);(root/'cookies').mkdir(parents=True)
        (root/'cookies/default.json').write_text('{"cookies":[]}')
        with patch('research_douyin.run_worker') as run:
            result=dy.collect('search','汽车',8,self.state)
        run.assert_not_called();self.assertEqual(result['error']['code'],'NEED_LOGIN')
        self.assertFalse(dy.connection(self.state)['ready'])
        self.assertNotIn('cookie',json.dumps(self.r.view()['platform_statuses']))

    def test_query_invocation_is_bounded_no_shell_no_other_cli_commands(self):
        with patch('research_douyin.subprocess.run',return_value=SimpleNamespace(stdout='{"ok":true,"items":[]}')) as run:
            self.assertTrue(dy.run_worker('search','汽车; echo bad',8,self.state)['ok'])
        argv=run.call_args.args[0]
        self.assertIn('汽车; echo bad',argv)
        self.assertEqual(run.call_args.kwargs['timeout'],75)
        self.assertNotIn('shell',run.call_args.kwargs)
        for command in ('publish','comment','follow','like','logout'):
            with self.assertRaises(ValueError):dy.run_worker(command,'',1,self.state)

    def test_empty_or_missing_metrics_cannot_enable_automatic_collection(self):
        for response in ({'ok':True,'items':[]},{'ok':True,'items':[{'metrics':{'likes':None}}]},
                         {'ok':True,'items':[{'metrics':{'likes':True}}]},
                         {'ok':False,'error':{'code':'PLATFORM_BLOCKED'}}):
            with patch('research_douyin.run_worker',return_value=response):dy.verify(self.state)
            self.assertFalse(dy.connection(self.state)['ready'])

    def test_real_metrics_verification_and_likes_boundary_enable_once(self):
        response={'ok':True,'items':[public_item(raw(n)) for n in (49999,50000,50001)]}
        with patch('research_douyin.run_worker',return_value=response):dy.verify(self.state)
        state=dy.connection(self.state)
        self.assertTrue(state['ready']);self.assertEqual(state['qualified_count'],2)
        self.assertEqual((dy.state_root(self.state)/'connection.json').stat().st_mode&0o777,0o600)

    def test_rate_limit_revokes_readiness_and_does_not_retry(self):
        self.ready();dy.save_state(dy.state_root(self.state),detail_blocked=True)
        with patch('research_douyin.run_worker',return_value={'ok':False,'error':{'code':'RATE_LIMITED'}}) as run:
            dy.collect('search','汽车',8,self.state)
            dy.collect('search','汽车',8,self.state)
        self.assertEqual(run.call_count,1)
        self.assertFalse(dy.connection(self.state)['ready'])
        self.assertTrue(dy.connection(self.state)['detail_blocked'])

    def test_detail_access_denial_does_not_disable_a_verified_search_or_repeat_detail(self):
        self.ready()
        with patch('research_douyin.run_worker',return_value={'ok':False,'error':{'code':'DETAIL_BLOCKED'}}) as run:
            dy.collect('read','https://www.douyin.com/video/7546165781764033819',1,self.state)
            again=dy.collect('read','https://www.douyin.com/video/7546165781764033819',1,self.state)
        self.assertEqual(run.call_count,1);self.assertEqual(again['error']['code'],'DETAIL_BLOCKED')
        self.assertTrue(dy.connection(self.state)['ready']);self.assertTrue(dy.connection(self.state)['detail_blocked'])
        with patch('research_douyin.run_worker',return_value={'ok':True,'items':[public_item(raw())]}) as search:
            self.assertTrue(dy.collect('search','人物故事',8,self.state)['ok'])
        search.assert_called_once_with('search','人物故事',8,self.state)

    def test_http_endpoint_denial_is_separate_from_global_login_or_rate_limit(self):
        self.assertEqual(http_error_code(403,True),'DETAIL_BLOCKED')
        self.assertEqual(http_error_code(412,True),'DETAIL_BLOCKED')
        self.assertEqual(http_error_code(403,False),'PLATFORM_BLOCKED')
        self.assertEqual(http_error_code(401,True),'NEED_LOGIN')
        self.assertEqual(http_error_code(429,True),'RATE_LIMITED')
        self.assertIsNone(http_error_code(200,True))

    def test_read_accepts_only_expected_work_url_and_never_exposes_credentials(self):
        self.ready()
        with patch('research_douyin.run_worker',return_value={'ok':True,'items':[]}) as run:
            dy.collect('read','https://www.douyin.com/video/7546165781764033819',1,self.state)
            self.assertEqual(run.call_args.args[:3],('detail','7546165781764033819',1))
            for url in ('https://example.com/video/7546165781764033819','https://www.douyin.com/user/example'):
                with self.assertRaises(ValueError):dy.collect('read',url,1,self.state)

    def test_timeout_and_invalid_output_return_sanitized_error(self):
        for error,code in ((subprocess.TimeoutExpired(['secret-cookie'],75),'TIMEOUT'),(OSError('secret-cookie'),'UPSTREAM_BROKEN')):
            with patch('research_douyin.subprocess.run',side_effect=error):result=dy.run_worker('search','汽车',8,self.state)
            self.assertEqual(result['error']['code'],code);self.assertNotIn('secret-cookie',str(result))

    def test_douyin_search_keeps_fields_source_and_category_through_library(self):
        with patch('research_douyin.collect',return_value={'ok':True,'backend':'dy-cli-readonly','items':[public_item(raw())]}):
            self.r.run_search('a'*24,{'channel':'douyin','action':'search','query':'汽车','category':'汽车','limit':8})
        item=self.r.items()[0]
        self.assertEqual(item['source'],'dy-cli-readonly');self.assertEqual(item['research_category'],'汽车')
        self.assertEqual(item['metrics']['likes'],50000);self.assertIsNone(item['metrics']['plays'])
        self.assertEqual(self.r.task('a'*24)['status'],'complete')

    def test_checking_status_never_opens_a_browser_or_retries_blocked_requests(self):
        self.ready()
        dy.save_state(dy.state_root(self.state),verified=False,status='needs_attention',error_code='PLATFORM_BLOCKED')
        with patch('research_douyin.run_worker') as run:
            status=dy.login(self.r,{'check':True})
        run.assert_not_called();self.assertFalse(status['ready'])
        with self.assertRaises(ValueError):dy.login(self.r,{},verify_only=True)

    def test_blocked_detail_is_not_success_and_keeps_previous_search_evidence(self):
        self.ready();dy.save_state(dy.state_root(self.state),last_verified_at='2026-10-25T08:03:43+00:00')
        with patch('research_douyin.run_worker',return_value={'ok':False,'error':{'code':'PLATFORM_BLOCKED'}}):
            dy.collect('read','https://www.douyin.com/video/7546165781764033819',1,self.state)
        status=dy.connection(self.state)
        self.assertFalse(status['ready']);self.assertTrue(status['search_verified']);self.assertTrue(status['detail_blocked'])


if __name__=='__main__':unittest.main()

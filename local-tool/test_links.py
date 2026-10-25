"""Link workflow contracts, with isolated data and no live account requests."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error

from research import Research,normalize_item
from research_links import canonical,parse_links,resolve_short,start_links

YT='https://www.youtube.com/watch?v=xpyrefzvTpI'
BILI='https://www.bilibili.com/video/BV1xx411c7mD'
DY='https://www.douyin.com/video/7546165781764033819'
XHS='https://www.xiaohongshu.com/explore/1234567890abcdef12345678?xsec_token=public-note-token'


class LinksContract(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.r=Research(self.root)
        self.skill=self.root/'SKILL.md';self.skill.write_text('本测试使用的分析方法')
        self.skill_patch=patch('research.skill_path',return_value=self.skill);self.skill_patch.start()
        self.reach_patch=patch('research.reach_binary',return_value='/safe/agent-reach');self.reach_patch.start()
    def tearDown(self):self.skill_patch.stop();self.reach_patch.stop();self.tmp.cleanup()

    def run_batch(self,text=YT,intent='library'):
        result=start_links(self.r,{'text':text,'intent':intent},background=False)
        return self.r.task(result['task_id'])

    def response(self,likes=0):
        return {'ok':True,'backend':'yt-dlp-public-metadata','items':[{'url':YT,'title':'公开作品','author':'作者','cover':'https://example.com/cover.jpg','text':'真实简介','raw':{'like_count':likes,'view_count':200,'comment_count':0}}]}

    def test_share_text_extracts_links_without_running_words_as_commands(self):
        rows=parse_links('4.12 / 用户文案 `rm -rf` '+DY+' 复制此链接，打开抖音。\n'+YT)
        self.assertEqual([r['platform'] for r in rows],['douyin','youtube'])
        self.assertEqual(rows[0]['url'],DY)
        self.assertEqual(len(parse_links(YT+'\nhttps://youtu.be/xpyrefzvTpI?t=2\nhttps://www.youtube.com/shorts/xpyrefzvTpI')),1)

    def test_normalization_keeps_work_identity_and_required_public_xhs_access_parameter(self):
        self.assertEqual(canonical(BILI+'?spm_id_from=abc')['url'],BILI)
        self.assertEqual(canonical('http://youtu.be/xpyrefzvTpI?t=22')['url'],YT)
        self.assertEqual(canonical('https://www.iesdouyin.com/share/video/7546165781764033819/')['url'],DY)
        self.assertIn('xsec_token=public-note-token',canonical(XHS)['url'])
        self.assertEqual(canonical('https://xhslink.com/a/abcd')['platform'],'xiaohongshu')

    def test_unsupported_link_in_a_mixed_batch_does_not_persist_private_url_parts(self):
        rows=parse_links(YT+'\nhttps://user:secret@example.com/path?api_key=secret#secret')
        self.assertEqual(rows[1]['url'],'https://example.com/path')
        self.assertNotIn('secret',str(rows))

    def test_private_unsupported_profile_and_bad_input_never_start_any_task(self):
        bad=['file:///etc/passwd','http://127.0.0.1/','https://evil.example/a','https://www.youtube.com/@creator','https://www.douyin.com/user/123','https://www.bilibili.com:444/video/BV1xx411c7mD','https://user:password@www.youtube.com/watch?v=xpyrefzvTpI']
        with patch('research.POOL.submit') as submit:
            for value in bad+[None,True,'','x'*20001]:
                with self.assertRaises(ValueError):start_links(self.r,{'text':value})
        submit.assert_not_called();self.assertEqual(self.r.view()['tasks'],[])
        with self.assertRaises(ValueError):parse_links('\n'.join(YT for _ in range(13)))
        self.assertEqual(len(parse_links('\n'.join('https://youtu.be/'+f'{i:011d}' for i in range(12)))),12)

    def test_short_link_rejects_private_redirect_before_second_request(self):
        row=canonical('https://b23.tv/abc')
        failure=urllib.error.HTTPError(row['url'],302,'redirect',{'Location':'https://127.0.0.1/'},None)
        opener=SimpleNamespace(open=unittest.mock.Mock(side_effect=failure))
        with patch('research_preview.checked_url',side_effect=lambda u:u),patch('research_links.urllib.request.build_opener',return_value=opener):
            with self.assertRaises(ValueError):resolve_short(row)
        self.assertEqual(opener.open.call_count,1)

    def test_short_link_resolves_to_canonical_work_without_fetching_final_page(self):
        row=canonical('https://b23.tv/abc')
        redirect=urllib.error.HTTPError(row['url'],302,'redirect',{'Location':BILI+'?tracking=1'},None)
        opener=SimpleNamespace(open=unittest.mock.Mock(side_effect=redirect))
        with patch('research_preview.checked_url',side_effect=lambda u:u),patch('research_links.urllib.request.build_opener',return_value=opener):
            result=resolve_short(row)
        self.assertEqual(result['url'],BILI);self.assertEqual(opener.open.call_count,1)

    def test_real_metadata_path_saves_zero_counts_cover_and_source(self):
        with patch('research_youtube.read_youtube',return_value=self.response()):task=self.run_batch()
        item=self.r.items()[0]
        self.assertTrue(item['saved']);self.assertEqual(item['title'],'公开作品')
        self.assertEqual(item['metrics'],{'plays':200,'likes':0,'comments':0,'favorites':None,'shares':None})
        self.assertEqual(item['cover'],'https://example.com/cover.jpg');self.assertEqual(item['transcript'],'')
        self.assertEqual(task['status'],'complete');self.assertEqual(task['count'],1)
        self.assertEqual(self.r.preferences()['tracks'],[])  # no automatic track subscriptions
        self.assertFalse(self.r.view()['items'][0]['is_hit'])  # manual reference can have low likes

    def test_blocked_douyin_does_not_retry_or_even_resolve_short_link(self):
        with patch('research_douyin.connection',return_value={'ready':False,'authenticated':True,'detail_blocked':True}),patch('research_douyin.run_worker') as worker,patch('research_links.resolve_short') as resolve:
            task=self.run_batch('分享文案 https://v.douyin.com/abc/','creative')
        worker.assert_not_called();resolve.assert_not_called()
        self.assertEqual(task['status'],'partial');self.assertEqual(task['count'],0)
        self.assertNotIn('analysis_task_id',task)
        self.assertEqual(self.r.items()[0]['source'],'link-only')
        self.assertTrue(all(v is None for v in self.r.items()[0]['metrics'].values()))

    def test_xhs_read_checks_login_without_opening_qr_or_requesting_note_detail(self):
        from research_xhs import collect
        with patch('research_xhs.request',return_value={'is_logged_in':False}) as request:
            response=collect('read',XHS,1)
        self.assertEqual(response['error']['code'],'NEED_LOGIN')
        request.assert_called_once_with('/api/v1/login/status')

    def test_failed_platform_stops_remaining_network_reads_and_keeps_good_other_platform(self):
        with patch('research_xhs.request',return_value={'is_logged_in':False}) as xhs,patch('research_youtube.read_youtube',return_value=self.response(50000)):
            task=self.run_batch(YT+'\n'+XHS+'\n'+XHS.replace('1234567890abcdef12345678','2234567890abcdef12345678'),'strategy')
        xhs.assert_called_once()
        self.assertEqual(task['status'],'partial');self.assertEqual(task['count'],1)
        analysis=self.r.task(task['analysis_task_id'])
        self.assertEqual(analysis['status'],'awaiting_codex');self.assertEqual(analysis['mode'],'strategy')
        self.assertEqual(analysis['item_count'],1)
        self.assertEqual(len(self.r.items()),3)

    def test_repeated_link_updates_one_saved_work_and_preserves_user_notes(self):
        with patch('research_youtube.read_youtube',return_value=self.response()):self.run_batch()
        item=self.r.items()[0];self.r.update({'id':item['id'],'notes':'我的备注','transcript':'已核对字幕'})
        with patch('research_youtube.read_youtube',return_value=self.response(5)):self.run_batch('https://youtu.be/xpyrefzvTpI?t=10')
        row=self.r.items()[0]
        self.assertEqual(len(self.r.items()),1);self.assertEqual(row['notes'],'我的备注');self.assertEqual(row['transcript'],'已核对字幕')
        self.assertEqual(row['metrics']['likes'],5)

    def test_read_failure_keeps_old_capture_time_metrics_and_does_not_claim_fresh_data(self):
        item=normalize_item({'url':YT,'title':'原始标题','likes':123456},source='agent-reach')
        item['captured_at']='2025-01-01T00:00:00+00:00';self.r.put(item,True)
        with patch('research_youtube.read_youtube',return_value={'ok':False,'error':{'code':'RATE_LIMITED'}}):task=self.run_batch()
        kept=self.r.items()[0]
        self.assertEqual(kept['captured_at'],item['captured_at']);self.assertEqual(kept['metrics']['likes'],123456)
        self.assertEqual(task['rows'][0]['status'],'kept');self.assertEqual(task['count'],0)

    def test_verified_short_link_record_is_reused_for_its_exact_canonical_url(self):
        item=normalize_item({'url':'https://v.douyin.com/abc/','title':'已核对的原作品','metrics':{'likes':185000},'metric_approximate':['likes']},'douyin','douyin-public-page')
        item['canonical_url']=DY;item['captured_at']='2026-10-25T09:00:00+00:00';self.r.put(item,True)
        with patch('research_douyin.connection',return_value={'ready':True,'detail_blocked':True}),patch('research_douyin.run_worker') as worker:
            task=self.run_batch(DY)
        worker.assert_not_called();self.assertEqual(len(self.r.items()),1)
        self.assertEqual(task['rows'][0]['item_id'],item['id']);self.assertEqual(task['rows'][0]['status'],'kept')
        self.assertEqual(self.r.items()[0]['captured_at'],item['captured_at'])

    def test_successful_new_read_with_hidden_likes_does_not_present_old_likes_as_fresh(self):
        item=normalize_item({'url':YT,'title':'原始标题','likes':123456},source='agent-reach');self.r.put(item,True)
        with patch('research_youtube.read_youtube',return_value=self.response(None)):task=self.run_batch()
        self.assertEqual(task['status'],'complete');self.assertEqual(task['count'],1)
        self.assertIsNone(self.r.items()[0]['metrics']['likes'])
        self.assertEqual(self.r.items()[0]['metrics']['comments'],0)

    def test_only_url_placeholders_never_get_an_automatic_analysis_task(self):
        with patch('research_youtube.read_youtube',return_value={'ok':False,'error':{'code':'UPSTREAM_BROKEN'}}):task=self.run_batch(intent='creative')
        self.assertNotIn('analysis_task_id',task);self.assertEqual(task['status'],'partial')
        self.assertEqual(self.r.items()[0]['collection_status'],'link_only')

    def test_opaque_collector_exception_finishes_parent_and_owned_child(self):
        with patch.object(self.r,'run_search',side_effect=RuntimeError('sensitive upstream exception')):task=self.run_batch()
        self.assertEqual(task['status'],'failed')
        self.assertFalse(any(t['status']=='running' for t in self.r.view()['tasks']))
        self.assertNotIn('sensitive',str(self.r.view()))

    def test_concurrent_submission_does_not_create_a_second_batch(self):
        with patch('research.POOL.submit'):
            self.assertTrue(start_links(self.r,{'text':YT})['ok'])
            with self.assertRaises(ValueError):start_links(self.r,{'text':BILI})


if __name__=='__main__':unittest.main()

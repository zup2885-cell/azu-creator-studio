"""Research contracts, isolated from live data and real accounts."""
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research import Research, count, normalize_item, public_url


def work(n=1, **changes):
    row={'aweme_id':str(900000+n),'title':'真实字段测试','digg_count':0,'comment_count':None,'desc':'已取得的来源文字'}
    row.update(changes)
    return row


class ResearchContract(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.r=Research(self.root)
        self.skill=self.root/'SKILL.md'; self.skill.write_text('测试专用 Skill 说明')
        self.skills=patch('research.skill_path',return_value=self.skill);self.skills.start()
        self.bili_io=patch('research_bilibili.read_video',return_value=None);self.bili_io.start()

    def tearDown(self):
        self.skills.stop();self.bili_io.stop();self.temp.cleanup()

    def insert(self, **changes):
        item=normalize_item(work(**changes),'douyin','mediacrawler-import');self.r.put(item,True);return item

    def test_zero_missing_and_large_integer(self):
        row=normalize_item(work())
        self.assertEqual(row['metrics']['likes'],0);self.assertIsNone(row['metrics']['comments'])
        for v in (-1,1.5,'NaN','2万',9007199254740992):
            with self.assertRaises(ValueError):count(v)

    def test_agent_reach_youtube_raw_metrics_are_not_dropped(self):
        item=normalize_item({'url':'https://www.youtube.com/watch?v=xpyrefzvTpI','title':'test','raw':{'view_count':1234,'like_count':0}})
        self.assertEqual(item['metrics']['plays'],1234)
        self.assertEqual(item['metrics']['likes'],0)
        self.assertIsNone(item['metrics']['comments'])
        self.assertIsNone(item['metrics']['shares'])

    def test_research_view_only_has_requested_platforms_without_deleting_archive(self):
        self.insert()
        self.r.put(normalize_item({'url':'https://example.com/','title':'旧网页资料'}),True)
        view=self.r.view()
        self.assertEqual(view['total'],1)
        self.assertEqual([i['platform'] for i in view['items']],['douyin'])
        with self.r.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM items').fetchone()[0],2)
        with self.assertRaises(ValueError):self.r.start_search({'channel':'web','query':'汽车'})
        with self.assertRaises(ValueError):self.r.add({'item':{'url':'https://github.com/example/project'}})
        with self.assertRaises(ValueError):normalize_item({'url':'https://example.com/'},'douyin')

    def test_category_is_user_selected_and_can_be_cleared(self):
        item=self.insert()
        self.r.update({'id':item['id'],'research_category':'汽车'})
        self.assertEqual(self.r.items()[0]['research_category'],'汽车')
        self.r.update({'id':item['id'],'research_category':'全部'})
        self.assertEqual(self.r.items()[0]['research_category'],'全部')
        with self.assertRaises(ValueError):self.r.update({'id':item['id'],'research_category':'随便伪造'})

    def test_native_youtube_retains_comment_count_without_downloads_or_credentials(self):
        from research_youtube import read_youtube
        from types import SimpleNamespace
        with patch('research_youtube.Path.is_file',return_value=True),patch('research_youtube.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps({'title':'public video','webpage_url':'https://www.youtube.com/watch?v=xpyrefzvTpI','comment_count':0,'view_count':321,'like_count':50}),stderr='')) as run:
            response=read_youtube('https://www.youtube.com/watch?v=xpyrefzvTpI','/safe/agent-reach')
        item=normalize_item(response['items'][0])
        self.assertEqual(item['metrics']['comments'],0)
        self.assertIn('--skip-download',run.call_args.args[0])
        self.assertIn('--ignore-config',run.call_args.args[0])
        self.assertNotIn('--write-comments',run.call_args.args[0])

    def test_popular_youtube_search_uses_verified_sort_and_discards_non_video_entries(self):
        from research_youtube import search_popular
        from types import SimpleNamespace
        entries=[{'id':'xpyrefzvTpI','title':'public video','view_count':3000000},
                 {'id':'UC-channel','title':'channel result'}]
        with patch('research_youtube.Path.is_file',return_value=True),patch('research_youtube.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps({'entries':entries}),stderr='')) as run:
            result=search_popular('人物故事',8,'/safe/agent-reach')
        argv=run.call_args.args[0]
        self.assertIn('sp=CAM%253D',argv[-1])
        self.assertIn('--skip-download',argv)
        self.assertIn('--flat-playlist',argv)
        self.assertEqual(len(result['items']),1)
        self.assertIsNone(result['items'][0]['raw']['like_count'])

    def test_one_broken_youtube_metadata_record_does_not_discard_the_batch(self):
        urls=['https://www.youtube.com/watch?v='+ident for ident in ('aaaaaaaaaaa','bbbbbbbbbbb','ccccccccccc')]
        summary=[{'url':url,'title':'候选'} for url in urls]
        def full(index):return {'ok':True,'items':[dict(summary[index],raw={'like_count':60000,'comment_count':0})]}
        with patch('research_youtube.search_popular',return_value={'ok':True,'items':summary}),patch('research_youtube.read_youtube',side_effect=[full(0),ValueError('one oversized metadata record'),full(2)]):
            self.r.run_search('a'*24,{'channel':'youtube','action':'search','popular':True,'query':'biography documentary','category':'人物故事','limit':3})
        rows=self.r.view()['items']
        self.assertEqual(len(rows),3)
        self.assertEqual(sum(i['is_hit'] for i in rows),2)
        self.assertIsNone(next(i for i in rows if i['url']==urls[1])['metrics']['likes'])
        self.assertEqual(self.r.task('a'*24)['status'],'partial')

    def test_bilibili_popular_sdk_is_bounded_and_uses_no_shell(self):
        from research_bilibili import search_popular
        from types import SimpleNamespace
        with patch('research_bilibili.Path.is_file',return_value=True),patch('research_bilibili.subprocess.run',return_value=SimpleNamespace(stdout=json.dumps({'ok':True,'items':[]}))) as run:
            self.assertTrue(search_popular('人物故事',8)['ok'])
        self.assertIsInstance(run.call_args.args[0],list)
        self.assertNotIn('shell',run.call_args.kwargs)
        self.assertEqual(run.call_args.kwargs['timeout'],75)

    def test_xhs_counts_cover_and_rounded_values_keep_their_meaning(self):
        from research_xhs import to_item,request
        row={'id':'1234567890abcdef12345678','xsecToken':'public-note-token','noteCard':{'displayTitle':'汽车作品','cover':{'urlDefault':'https://example.com/cover.jpg'},'interactInfo':{'likedCount':'1.2万','commentCount':'0','collectedCount':'125','sharedCount':'9'}}}
        item=normalize_item(to_item(row))
        self.assertEqual(item['metrics'],{'plays':None,'likes':12000,'comments':0,'favorites':125,'shares':9})
        self.assertEqual(item['metric_approximate'],['likes'])
        self.assertTrue(item['cover'])
        second=normalize_item(to_item(dict(row,xsecToken='changed-public-note-token')))
        self.assertEqual(item['id'],second['id'])
        with self.assertRaises(ValueError):request('/api/v1/publish',{})

    def test_search_category_is_applied_to_collected_results(self):
        doc={'channel':'bilibili','action':'search','query':'汽车 SF90','limit':1,'category':'汽车'}
        with patch('research.subprocess.run') as run:
            run.return_value.stdout=json.dumps({'ok':True,'items':[{'url':'https://www.bilibili.com/video/BV1xx411c7mD','title':'汽车作品'}]})
            self.r.run_search('f'*24,doc)
        self.assertEqual(self.r.items()[0]['research_category'],'汽车')

    def test_bilibili_search_enriches_likes_and_cover(self):
        url='https://www.bilibili.com/video/BV1xx411c7mD'
        summary={'url':url,'title':'搜索摘要','raw':{'play':100}}
        full={'url':url,'title':'完整作品','cover':'https://example.com/cover.jpg','raw':{'stat':{'view':100,'like':25,'reply':3,'favorite':2,'share':0}}}
        with patch('research.subprocess.run') as run,patch('research_bilibili.read_video',return_value=full):
            run.return_value.stdout=json.dumps({'ok':True,'items':[summary]})
            self.r.run_search('a'*24,{'channel':'bilibili','action':'search','query':'汽车','limit':1})
        item=self.r.items()[0]
        self.assertEqual(item['metrics']['likes'],25)
        self.assertEqual(item['metrics']['shares'],0)
        self.assertEqual(item['cover'],full['cover'])

    def test_bilibili_enrichment_stops_at_verification_without_retry(self):
        rows=[{'url':'https://www.bilibili.com/video/BV1xx411c7mD','title':'摘要'}]*3
        with patch('research.subprocess.run') as run,patch('research_bilibili.read_video',side_effect=PermissionError('verification')) as read:
            run.return_value.stdout=json.dumps({'ok':True,'items':rows})
            self.r.run_search('a'*24,{'channel':'bilibili','action':'search','query':'汽车','limit':3})
        self.assertEqual(read.call_count,1)
        self.assertIsNone(self.r.items()[0]['metrics']['likes'])
        self.assertEqual(self.r.task('a'*24)['enrichment_error'],'PLATFORM_BLOCKED')

    def test_agent_reach_bilibili_stat_is_mapped_without_danmaku_or_coins(self):
        item=normalize_item({'url':'https://www.bilibili.com/video/BV1xx411c7mD','title':'test','raw':{'stat':{'view':500,'like':30,'reply':7,'favorite':9,'share':2,'danmaku':25,'coin':14}}})
        self.assertEqual(item['metrics'],{'plays':500,'likes':30,'comments':7,'favorites':9,'shares':2})

    def test_bilibili_cli_search_and_stats_shapes(self):
        item=normalize_item({'url':'https://www.bilibili.com/video/BV1xx411c7mD','raw':{'play':12345}})
        self.assertEqual(item['metrics']['plays'],12345)
        self.assertIsNone(item['metrics']['likes'])
        item=normalize_item({'url':item['url'],'raw':{'stats':{'view':100,'like':0,'favorite':5,'share':2}}})
        self.assertEqual(item['metrics'],{'plays':100,'likes':0,'comments':None,'favorites':5,'shares':2})

    def test_nonvideo_counts_are_not_invented(self):
        item=normalize_item({'url':'https://www.autohome.com.cn/','title':'普通网页'})
        self.assertTrue(all(v is None for v in item['metrics'].values()))
        github=normalize_item({'url':'https://github.com/example/project','raw':{'stargazers_count':1200,'forks_count':20}})
        self.assertTrue(all(v is None for v in github['metrics'].values()))

    def test_explicit_zero_beats_nested_fallback(self):
        item=normalize_item({'url':'https://www.youtube.com/watch?v=xpyrefzvTpI','metrics':{'likes':0},'raw':{'like_count':50}})
        self.assertEqual(item['metrics']['likes'],0)

    def test_explicit_clear_does_not_resurrect_saved_fields(self):
        item=self.insert()
        self.r.update({'id':item['id'],'notes':'旧备注','tags':['旧标签'],'transcript':'旧字幕'})
        self.r.update({'id':item['id'],'notes':'','tags':[],'transcript':''})
        row=self.r.items()[0]
        self.assertEqual((row['notes'],row['tags'],row['transcript']),('',[],''))

    def test_refresh_reads_the_work_platform_not_generic_web_search(self):
        item=normalize_item({'url':'https://www.youtube.com/watch?v=xpyrefzvTpI','title':'video'})
        self.r.put(item)
        with patch.object(self.r,'start_search',return_value={'ok':True}) as start:
            self.r.refresh_metrics({'id':item['id']})
        self.assertEqual(start.call_args.args[0],{'channel':'youtube','action':'read','query':item['url'],'limit':1,'category':'全部'})

    def test_preview_metadata_preserves_actual_urls_and_ignores_scripts(self):
        from research_preview import PreviewHead
        parser=PreviewHead()
        parser.feed('<head><link rel="icon" href="/assets/site.png"><meta property="og:image" content="https://cdn.example.com/real.jpg"><script>window.cover="fake.jpg"</script></head><meta property="og:image" content="bad.jpg">')
        result=parser.result('https://example.com/article')
        self.assertEqual(result,{'cover':'https://cdn.example.com/real.jpg','favicon':'https://example.com/assets/site.png'})

    def test_preview_blocks_private_hosts_and_redirects(self):
        from research_preview import checked_url,SafeRedirect
        import urllib.request
        with patch('research_preview.socket.getaddrinfo',return_value=[(2,1,6,'',('10.0.0.5',443))]):
            with self.assertRaises(ValueError):checked_url('https://example.com/')
        with self.assertRaises(ValueError):SafeRedirect().redirect_request(urllib.request.Request('https://example.com/'),None,302,'',{},'https://127.0.0.1/')

    def test_preview_supports_existing_local_proxy_fake_dns_only(self):
        from research_preview import checked_url
        fake=[(2,1,6,'',('198.18.0.140',443))]
        with patch('research_preview.socket.getaddrinfo',return_value=fake),patch('research_preview.urllib.request.getproxies',return_value={}):
            with self.assertRaises(ValueError):checked_url('https://example.com/')
        with patch('research_preview.socket.getaddrinfo',return_value=fake),patch('research_preview.urllib.request.getproxies',return_value={'https':'http://127.0.0.1:7890'}):
            self.assertEqual(checked_url('https://example.com/'),'https://example.com/')
            with self.assertRaises(ValueError):checked_url('https://198.18.0.140/')
        with patch('research_preview.socket.getaddrinfo',return_value=[(2,1,6,'',('10.0.0.1',443))]),patch('research_preview.urllib.request.getproxies',return_value={'https':'http://127.0.0.1:7890'}):
            with self.assertRaises(ValueError):checked_url('https://example.com/')

    def test_preview_failure_finishes_task_and_preserves_user_notes(self):
        item=self.insert()
        self.r.update({'id':item['id'],'notes':'不能覆盖我的研究备注'})
        task_id='e'*24
        doc={'item_ids':[item['id']]}
        with patch('research_preview.fetch_preview',side_effect=LookupError('unknown charset')):
            self.r.run_previews(task_id,doc)
        self.assertEqual(self.r.task(task_id)['status'],'complete')
        result=self.r.items()[0]
        self.assertEqual(result['preview_status'],'unavailable')
        self.assertEqual(result['notes'],'不能覆盖我的研究备注')

    def test_urls_and_credentials_rejected(self):
        for url in ['http://example.com','https://localhost/','https://127.0.0.1/a','https://[::1]/','https://user:secret@example.com/a','javascript:alert(1)','https://x.local/','https://example.com:8766/']:
            with self.assertRaises(ValueError):public_url(url)

    def test_external_flags_cannot_claim_visual_verification(self):
        row=normalize_item(dict(work(),visual_verified=True))
        self.assertFalse(row['visual_verified'])

    def test_roundtrip_preserves_metrics_tags_and_sources(self):
        item=self.insert();self.r.update({'id':item['id'],'tags':['人物','赛车'],'notes':'核对来源'})
        blob,_,_=self.r.export('json')
        other=Research(self.root/'other')
        other.import_data({'content':blob.decode(),'format':'json'})
        row=other.items()[0]
        self.assertEqual(row['metrics']['likes'],0);self.assertIsNone(row['metrics']['plays'])
        self.assertEqual(row['tags'],['人物','赛车']);self.assertEqual(row['notes'],'核对来源')

    def test_invalid_batch_writes_nothing(self):
        rows=[work(),dict(work(2),digg_count=-1)]
        with self.assertRaises(ValueError):self.r.import_data({'content':json.dumps(rows),'format':'json'})
        self.assertEqual(self.r.items(),[])

    def test_duplicate_link_does_not_duplicate_row(self):
        data={'content':json.dumps([work(),work()]),'format':'json'}
        self.assertEqual(self.r.import_data(data)['duplicates'],1)
        self.assertEqual(self.r.import_data(data)['new'],0)
        self.assertEqual(len(self.r.items()),1)

    def test_comment_import_does_not_overwrite_work_identity_or_metrics(self):
        item=self.insert(title='原始作品',digg_count=100)
        comments=[{'comment_id':'c1','aweme_id':'900001','content':'观众实际问题','nickname':'评论人','digg_count':9}]
        self.r.import_data({'content':json.dumps(comments),'format':'json','platform':'douyin'})
        row=self.r.items()[0]
        self.assertEqual(row['title'],'原始作品');self.assertEqual(row['metrics']['likes'],100)
        self.assertEqual(row['comment_texts'],['观众实际问题'])
        self.r.import_data({'content':json.dumps(comments),'format':'json','platform':'douyin'})
        self.assertEqual(len(self.r.items()[0]['comment_texts']),1)

    def test_unmatched_comment_batch_is_rejected_without_partial_write(self):
        self.insert()
        comments=[{'comment_id':'c1','aweme_id':'900001','content':'问题一'},{'comment_id':'c2','aweme_id':'900999','content':'问题二'}]
        with self.assertRaises(ValueError):self.r.import_data({'content':json.dumps(comments),'format':'json','platform':'douyin'})
        self.assertEqual(self.r.items()[0]['comment_texts'],[])

    def test_refresh_does_not_erase_notes_or_known_counts(self):
        item=self.insert(digg_count=0)
        self.r.update({'id':item['id'],'notes':'已核实','transcript':'真实字幕'})
        self.r.put(normalize_item({'url':item['url'],'title':'重新读取','likes':None},'douyin'))
        row=self.r.items()[0]
        self.assertEqual((row['notes'],row['transcript'],row['metrics']['likes']),('已核实','真实字幕',0))
        self.assertTrue(row['saved'])

    def test_csv_and_jsonl_import(self):
        for fmt,content in [('csv','aweme_id,title,digg_count\n999,test,0\n'),('jsonl',json.dumps(work(4))+'\n')]:
            self.assertEqual(self.r.import_data({'format':fmt,'content':content,'platform':'douyin'})['new'],1)
        self.assertEqual(len(self.r.items()),2)

    def test_csv_export_escapes_formulas_and_keeps_blanks(self):
        self.insert(title='=HYPERLINK("https://example.com")')
        content,_,_=self.r.export('csv')
        rows=list(csv.reader(io.StringIO(content.decode('utf-8-sig'))))
        self.assertTrue(rows[1][0].startswith("'="))
        self.assertEqual(rows[1][5],'');self.assertEqual(rows[1][6],'0')

    def test_frozen_task_and_citation_checked(self):
        item=self.insert()
        result=self.r.prepare_analysis({'ids':[item['id']],'mode':'strategy'})
        task=self.r.task(result['task_id'])
        bundle=self.r.export('bundle',task['id'])[0].decode()
        self.assertIn('ad-creative',bundle);self.assertIn('content-strategy',bundle);self.assertIn('不写稿',bundle)
        self.r.update({'id':item['id'],'notes':'任务后更改'})
        report={'summary':'观察样本','findings':[{'title':'字段边界','evidence':'点赞为 0，播放未提供','interpretation':'无法由此判断播放表现','item_ids':[item['id']]}],'limitations':['只有一条样本'],'experiments':[]}
        self.r.finish(task['id'],report)
        saved=self.r.view()['reports'][0]
        self.assertEqual(saved['input_snapshot'][0]['notes'],'')
        self.assertEqual(saved['input_sha256'],task['input_sha256'])
        with self.assertRaises(ValueError):self.r.finish(task['id'],report)

    def test_unknown_reference_in_report_rejected(self):
        item=self.insert();task=self.r.prepare_analysis({'ids':[item['id']]})
        bad={'summary':'观察','findings':[{'title':'t','evidence':'e','interpretation':'i','item_ids':['wrong']}],'limitations':['l']}
        with self.assertRaises(ValueError):self.r.finish(task['task_id'],bad)
        self.assertEqual(self.r.view()['reports'],[])

    def test_tampered_input_is_not_accepted(self):
        item=self.insert();task=self.r.prepare_analysis({'ids':[item['id']]})
        path=self.r.root/'analysis-inputs'/f'{task["task_id"]}.json'
        doc=json.loads(path.read_text());doc['items'][0]['title']='改过的输入';path.write_text(json.dumps(doc))
        report={'summary':'s','findings':[{'title':'t','evidence':'e','interpretation':'i','item_ids':[item['id']]}],'limitations':['l']}
        with self.assertRaises(ValueError):self.r.finish(task['task_id'],report)

    def test_xhs_uses_existing_read_only_service_without_browser_cookie_fallback(self):
        task_id='a'*24; doc={'channel':'xiaohongshu','action':'search','query':'人物故事','limit':5}
        with patch('research_xhs.collect',return_value={'ok':False,'error':{'code':'NEED_LOGIN','hint':'secret upstream hint'}}) as collect,patch('research.subprocess.run') as run:
            self.r.run_search(task_id,doc)
            collect.assert_called_once_with('search','人物故事',5,popular=False)
            run.assert_not_called()
        task=self.r.task(task_id)
        self.assertEqual(task['status'],'failed');self.assertNotIn('secret',task['message'])

    def test_restart_marks_only_running_tasks(self):
        self.r.set_task('a'*24,'search','running',{})
        self.r.set_task('b'*24,'analysis','awaiting_codex',{})
        self.r.recover()
        self.assertEqual(self.r.task('a'*24)['status'],'interrupted')
        self.assertEqual(self.r.task('b'*24)['status'],'awaiting_codex')

    def test_file_permissions_and_saved_counts(self):
        self.insert()
        self.assertEqual(self.r.db_path.stat().st_mode&0o777,0o600)
        self.assertEqual(self.r.view()['observation']['saved_count'],1)
        self.assertEqual(self.r.view()['observation']['with_transcript'],0)

if __name__=='__main__':unittest.main()

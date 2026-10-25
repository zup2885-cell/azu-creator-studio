import io
import json
from pathlib import Path
import tempfile
import unittest
import threading
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from research import Research,normalize_item
import research_media as media
from research_study import schema,validate_study


SRT='1\n00:00:00,000 --> 00:00:02,000\n真实开头。\n\n2\n00:00:02,000 --> 00:00:04,000\n接着说明原因。\n'


class MediaContracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.state=Path(self.tmp.name);self.r=Research(self.state)
        self.item=normalize_item({'url':'https://www.youtube.com/watch?v=abcde123456','title':'原始参考','transcript':'','metrics':{'likes':100000}})
        self.r.put(self.item,True)
    def tearDown(self):self.tmp.cleanup()
    def receive(self,content=SRT.encode(),name='字幕.srt'):
        with patch.object(media.POOL,'submit'):
            result=media.receive_upload(self.r,io.BytesIO(content),len(content),name,self.item['id'])
        return result['task_id']
    def test_srt_vtt_plaintext_and_time_bounds(self):
        segments,text=media.parse_subtitles(SRT.encode(),'.srt');self.assertEqual(len(segments),2);self.assertEqual(segments[1]['start'],2)
        self.assertEqual(media.parse_subtitles(('WEBVTT\n\n'+SRT).replace(',','.').encode(),'.vtt')[0],segments)
        self.assertEqual(media.parse_subtitles('只有正文'.encode(),'.txt'),([], '只有正文'))
        for content in ['无时间轴','1\n00:00:04,000 --> 00:00:02,000\n错误\n','1\n00:20:00,000 --> 00:20:05,000\n超时\n']:
            with self.assertRaises(ValueError):media.parse_subtitles(content.encode(),'.srt')
    def test_upload_updates_only_intended_evidence_and_keeps_bookmark(self):
        ident=self.receive();media.run(self.r,ident,self.r.task(ident))
        item=self.r.items()[0];self.assertTrue(item['saved']);self.assertEqual(item['metrics']['likes'],100000)
        self.assertEqual(item['transcript'],'真实开头。\n接着说明原因。');self.assertFalse(item['transcript_verified'])
        self.assertEqual(self.r.task(ident)['status'],'complete')
        self.r.update({'id':item['id'],'transcript':'人工核对后的原句'})
        changed=dict(self.item,title='上游简短结果');self.r.put(changed)
        self.assertIn('media_evidence',self.r.items()[0]);self.assertEqual(self.r.items()[0]['transcript_source'],'human-reviewed')
        self.assertEqual(self.r.items()[0]['transcript'],'人工核对后的原句')
    def test_inflight_human_transcript_and_notes_are_not_overwritten(self):
        ident=self.receive();self.r.update({'id':self.item['id'],'notes':'刚写的备注','transcript':'人工保留文字'})
        media.run(self.r,ident,self.r.task(ident));item=self.r.items()[0]
        self.assertEqual(item['transcript'],'人工保留文字');self.assertEqual(item['notes'],'刚写的备注')
    def test_bad_upload_never_starts_task_and_single_worker_is_enforced(self):
        for content,name in [(b'bad','a.exe'),(b'bad','a.srt')]:
            with self.assertRaises(ValueError):self.receive(content,name)
        self.assertFalse(self.r.view()['tasks']);self.receive()
        with self.assertRaisesRegex(ValueError,'已有视频'):self.receive()
        with self.assertRaises(ValueError):media.receive_upload(self.r,io.BytesIO(b'a'),media.MAX_UPLOAD+1,'a.mp4',self.item['id'])
    def test_asset_path_and_platform_restrictions(self):
        for ident,name in [('../secret','frame-00.jpg'),('a'*24,'../cookies.json'),('a'*24,'source.mp4')]:
            with self.assertRaises(ValueError):media.asset(self.r,ident,name)
        self.assertEqual(media.platform_url(self.item),'https://www.youtube.com/watch?v=abcde123456')
        for url,p in [('http://127.0.0.1/','youtube'),('https://www.douyin.com/video/123','douyin')]:
            with self.assertRaises(ValueError):media.platform_url({'url':url,'platform':p})
    def test_steps_require_distinct_contracts_and_reject_invented_timestamps(self):
        self.assertIn('breakdown',schema('creative')['required']);self.assertNotIn('decision',schema('creative')['properties'])
        self.assertIn('decision',schema('strategy')['required'])
        skill=self.state/'SKILL.md';skill.write_text('研究方法')
        with patch('research.skill_path',return_value=skill):task=self.r.prepare_analysis({'ids':[self.item['id']],'mode':'creative'})
        doc=self.r.task(task['task_id']);doc['study_format']='video-v1'
        section={'opening':'待补','beats':[{'item_id':self.item['id'],'start':0,'end':2,'detail':'假设开场'}],'pacing':'待补','borrow':'待补','avoid':'待补'}
        with self.assertRaisesRegex(ValueError,'时间证据'):validate_study({'breakdown':section},doc)
        section['beats']=[];self.assertIn('breakdown',validate_study({'breakdown':section},doc))
        with self.assertRaises(ValueError):validate_study({'decision':{}},doc)

    def test_frame_attachments_and_completed_breakdown_are_frozen_into_decision(self):
        # Use a legitimate uploaded subtitle timeline, then exercise the report hand-off.
        ident=self.receive();media.run(self.r,ident,self.r.task(ident))
        skill=self.state/'SKILL.md';skill.write_text('研究方法')
        with patch('research.skill_path',return_value=skill):prepared=self.r.prepare_analysis({'ids':[self.item['id']],'mode':'creative'})
        report={'summary':'先分析开头反常现象。','findings':[{'title':'真实开头','evidence':'真实开头。','interpretation':'先给现象。','item_ids':[self.item['id']]}],'experiments':[],'limitations':['这是字幕线索。']}
        self.r.finish(prepared['task_id'],report)
        with patch('research.skill_path',return_value=skill):task=self.r.prepare_analysis({'ids':[self.item['id']],'mode':'strategy'})
        frozen=json.loads(Path(self.r.task(task['task_id'])['bundle_path']).with_suffix('.json').read_text())
        self.assertEqual(len(frozen['observations']['benchmark_context']),1)
        self.assertEqual(frozen['observations']['benchmark_context'][0]['summary'],report['summary'])


class MediaHTTP(unittest.TestCase):
    def setUp(self):
        import server
        self.tmp=tempfile.TemporaryDirectory();self.state=Path(self.tmp.name)
        self.patch=patch('server.STATE',self.state);self.patch.start()
        self.r=Research(self.state);self.item=normalize_item({'url':'https://www.youtube.com/watch?v=abcde123456','title':'样本'});self.r.put(self.item,True)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.patch.stop();self.tmp.cleanup()
    def test_upload_origin_file_limit_and_asset_allowlist(self):
        headers={'Content-Type':'application/octet-stream','X-Filename':'test.srt','X-Item-ID':self.item['id']}
        req=urllib.request.Request(self.base+'/api/research/media-upload',data=SRT.encode(),headers=headers)
        with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(req)
        self.assertEqual(error.exception.code,403)
        headers['Origin']='http://127.0.0.1:8766'
        with patch.object(media.POOL,'submit'):
            with urllib.request.urlopen(urllib.request.Request(self.base+'/api/research/media-upload',data=SRT.encode(),headers=headers)) as response:doc=json.load(response)
        self.assertTrue(doc['ok']);self.assertEqual(self.r.task(doc['task_id'])['kind'],'media')
        folder=media.folder_for(self.r,doc['task_id']);(folder/'frame-00.jpg').write_bytes(b'test-frame')
        with urllib.request.urlopen(self.base+'/api/research/media/'+doc['task_id']+'/frame-00.jpg') as response:self.assertEqual(response.read(),b'test-frame')
        for name in ['source.srt','unknown.json']:
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(self.base+'/api/research/media/'+doc['task_id']+'/'+name)
            self.assertEqual(error.exception.code,404)


if __name__=='__main__':unittest.main()

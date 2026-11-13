import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import server
import work_covers as covers
import work_review as review
from operations import atomic_json
from test_server import fixture

class ReviewFixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.state=Path(self.temp.name)
        self.patch=patch.multiple(server,STATE=self.state,IMPORTS=self.state/'dashboard-imports');self.patch.start()
        self.source=self.state/'exports/抖音数据_test.json';atomic_json(self.source,fixture())
        self.snap=server.snapshots()[0][0];self.row=self.snap['rows'][0]
    def tearDown(self):self.patch.stop();self.temp.cleanup()
    def frozen(self,**extra):return review.context(self.state,{'snapshot_id':self.snap['id'],'work_id':self.row['id'],**extra})
    def report(self,frozen):
        return {**{k:frozen[k] for k in ['snapshot_id','source_sha256','work_id','input_hash']},'summary':'先检查开头留人，再用下一条验证。','diagnostics':[{'metric':m,'observation':'数据现象','hypothesis':'待验证的解释','action':'核对对应画面并修改一处','check':'同发布时间比较'} for m in ['bounce','finish','follower_per_1000']],'experiment':{'change':'只改开头','keep':'同题材同长度','judge':'发布后24小时记录数据'},'limitations':['没有观看原片。']}

class WorkReviewContract(ReviewFixture):
    def test_measured_rates_and_zero_missing_are_distinct(self):
        metrics=review.measured(self.row)
        self.assertEqual(metrics['interaction_rate'],8)
        self.assertEqual(metrics['follower_per_1000'],20)
        zero=copy.deepcopy(self.row);zero['plays']=0
        self.assertIsNone(review.measured(zero)['interaction_rate'])
        zero['plays']=100;zero['follower_gain']=0;zero['likes']=None
        self.assertEqual(review.measured(zero)['follower_per_1000'],0)
        self.assertIsNone(review.measured(zero)['interaction_rate'])
    def test_private_video_and_unknown_snapshot_rejected(self):
        with self.assertRaisesRegex(ValueError,'公开作品'):review.context(self.state,{'snapshot_id':self.snap['id'],'work_id':self.snap['rows'][1]['id']})
        with self.assertRaisesRegex(ValueError,'有效'):review.context(self.state,{'snapshot_id':'wrong','work_id':self.row['id']})
    def test_peer_evidence_excludes_private_and_freezes_notes(self):
        frozen=self.frozen(notes='  原稿  ')
        self.assertEqual(frozen['peer_count'],1)
        self.assertEqual(frozen['evidence']['finish']['median'],12.5)
        self.assertEqual(frozen['evidence']['bounce']['rank'],1)
        self.assertEqual(frozen['notes'],'原稿')
        self.assertNotEqual(frozen['input_hash'],self.frozen()['input_hash'])
        with self.assertRaisesRegex(ValueError,'6000'):self.frozen(notes='字'*6001)
    def test_wrong_work_or_hash_never_saved(self):
        frozen=self.frozen();doc=self.report(frozen);doc['work_id']='another'
        with self.assertRaisesRegex(ValueError,'不一致'):review.save(self.state,doc,frozen)
        self.assertEqual(review.reports(self.state,[self.snap]),[])
        doc=self.report(frozen);doc['input_hash']='wrong'
        with self.assertRaisesRegex(ValueError,'不一致'):review.validate(doc,frozen)
    def test_duplicate_or_missing_metric_and_empty_actions_rejected(self):
        frozen=self.frozen();doc=self.report(frozen);doc['diagnostics'][1]['metric']='bounce'
        with self.assertRaisesRegex(ValueError,'重复'):review.validate(doc,frozen)
        doc=self.report(frozen);doc['diagnostics'][0]['action']=''
        with self.assertRaisesRegex(ValueError,'为空'):review.validate(doc,frozen)
    def test_report_bound_to_snapshot_hash_and_corrupt_files_isolated(self):
        frozen=self.frozen();result=review.save(self.state,self.report(frozen),frozen)
        self.assertEqual(result['work_id'],self.row['id'])
        self.assertEqual(len(review.reports(self.state,[self.snap])),1)
        changed=copy.deepcopy(self.snap);changed['sha256']='new'
        self.assertEqual(review.reports(self.state,[changed]),[])
        atomic_json(self.state/'work-reviews/broken.json',{'snapshot_id':self.snap['id'],'source_sha256':self.snap['sha256'],'work_id':self.row['id']})
        self.assertEqual(len(review.reports(self.state,[self.snap])),1)
        self.assertEqual((self.state/'work-reviews'/f"{result['report_id']}.json").stat().st_mode&0o777,0o600)
    def test_insufficient_metrics_rejected_before_launch(self):
        doc=fixture()
        for k in ['bounce','ctr5s','finish','likes','follower_gain']:doc['parsed_rows'][0][k]=None
        atomic_json(self.source,doc)
        with self.assertRaisesRegex(ValueError,'不足三项'):self.frozen()

class WorkCoverContract(ReviewFixture):
    def item(self,**extra):return {'title':self.row['title'],'pub_date':self.row['pub_date'],'cover':'https://p1.douyinpic.com/image.webp','video_id':'7700817859341012259',**extra}
    def fetch(self,url):return b'RIFF0000WEBPpayload','image/webp'
    def test_cache_real_cover_without_changing_snapshot(self):
        before=self.source.read_bytes();result=covers.ingest(self.state,[self.row],[self.item()],self.fetch)
        self.assertEqual(result['covers'],1)
        payload=server.payload();row=payload['snapshots'][0]['rows'][0]
        self.assertTrue(row['cover'].startswith('/api/work-covers/'))
        self.assertEqual(row['url'],'https://www.douyin.com/video/7700817859341012259')
        self.assertEqual(self.source.read_bytes(),before)
        self.assertEqual(payload['snapshots'][0]['sha256'],self.snap['sha256'])
        path,mime=covers.asset(self.state,self.row['id']);self.assertEqual(mime,'image/webp');self.assertEqual(path.stat().st_mode&0o777,0o600)
    def test_no_guessing_by_partial_title_date_or_ambiguous_video(self):
        for item in [self.item(title='相似标题'),self.item(pub_date='2025-01-01 12:00:00')]:
            self.assertEqual(covers.ingest(self.state,[self.row],[item],self.fetch)['covers'],0)
        result=covers.ingest(self.state,[self.row],[self.item(),self.item(video_id='1234567890000')],self.fetch)
        self.assertEqual((result['covers'],result['failed']),(0,1))
    def test_bad_sources_and_fake_image_payload_rejected(self):
        for url in ['http://p1.douyinpic.com/x','https://douyinpic.com.evil.test/x','https://127.0.0.1/x','https://p1.douyinpic.com:bad/x','https://u:p@p1.douyinpic.com/x']:
            self.assertFalse(covers.allowed(url))
        result=covers.ingest(self.state,[self.row],[self.item()],lambda u:(b'<html>bad</html>','image/webp'))
        self.assertEqual((result['covers'],result['failed']),(0,1))
        with self.assertRaises(ValueError):covers.asset(self.state,'../other')
    def test_failed_refresh_keeps_existing_cover(self):
        covers.ingest(self.state,[self.row],[self.item()],self.fetch)
        path,_=covers.asset(self.state,self.row['id']);before=path.read_bytes()
        result=covers.ingest(self.state,[self.row],[self.item()],lambda u:(_ for _ in ()).throw(OSError()))
        self.assertEqual(result['failed'],1);self.assertEqual(path.read_bytes(),before)
    def test_corrupt_index_does_not_break_data_page(self):
        atomic_json(self.state/'work-covers/index.json',[])
        self.assertEqual(server.payload()['snapshots'][0]['totals']['plays'],100)
    def test_missing_cached_file_does_not_create_broken_image_reference(self):
        covers.ingest(self.state,[self.row],[self.item()],self.fetch)
        path,_=covers.asset(self.state,self.row['id']);path.unlink()
        self.assertNotIn('cover',server.payload()['snapshots'][0]['rows'][0])

if __name__=='__main__':unittest.main()

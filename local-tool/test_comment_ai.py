import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import comment_ai
from comments import Console,PROCESSES,dispatch
from test_comments import WORK,EXPORT

class ImmediateDrafts(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.state=Path(self.temp.name);self.console=Console(self.state)
        with self.console.transaction() as doc:self.console.merge(doc,WORK,EXPORT)
        self.status=patch('comment_ai.research_ai.status',return_value={'ready':True});self.status.start()
    def tearDown(self):self.status.stop();PROCESSES.clear();self.temp.cleanup()
    def prepare(self):
        with patch.object(threading.Thread,'start'):
            result=comment_ai.start(self.state,WORK)
        with self.console.transaction() as doc:
            job=next(j for j in doc['jobs'] if j['id']==result['job_id'])
            records=[{k:r[k] for k in ['id','revision','queue','work_title','username','text']} for r in doc['records'] if r['status']=='queued']
        return job,records
    def model(self,job,records,mutate=None):
        console=self.console
        class Process:
            returncode=0;pid=999999
            def communicate(self,*args,**kwargs):
                draft={'drafts':[{'id':r['id'],'revision':r['revision'],'queue':r['queue'],'reply':'谢谢你认真看完！','skip_reason':''} for r in records]}
                if mutate:mutate(draft)
                (console.root/'ai-runs'/job['id']/'report.json').write_text(json.dumps(draft))
            def poll(self):return 0
        return Process()
    def test_generate_now_saves_drafts_and_never_calls_browser_or_send(self):
        job,records=self.prepare()
        with patch('comment_ai.subprocess.Popen',return_value=self.model(job,records)),patch.object(Console,'start',side_effect=AssertionError('must not send')):
            comment_ai.run(self.console,job,records)
        view=self.console.view();self.assertTrue(all(r['status']=='draft' for r in view['records']))
        self.assertEqual(view['jobs'][-1]['status'],'done');self.assertEqual(view['jobs'][-1]['result']['sentCount'],0)
        self.assertFalse(any(j['kind']=='send' for j in view['jobs']))
    def test_skipped_replies_are_counted_separately(self):
        job,records=self.prepare()
        def skip(result):result['drafts'][0].update(reply='',skip_reason='含义不明')
        with patch('comment_ai.subprocess.Popen',return_value=self.model(job,records,skip)):comment_ai.run(self.console,job,records)
        view=self.console.view();result=view['jobs'][-1]['result']
        self.assertEqual(result['skippedCount'],1);self.assertEqual(result['draftCount'],len(records)-1)
        self.assertEqual(result['sentCount'],0);self.assertEqual(view['records'][0]['status'],'skip')
    def test_foreign_comment_rejected_without_partial_draft_writes(self):
        job,records=self.prepare()
        def wrong(result):result['drafts'][0]['id']='another-comment'
        with patch('comment_ai.subprocess.Popen',return_value=self.model(job,records,wrong)):comment_ai.run(self.console,job,records)
        view=self.console.view();self.assertEqual(view['jobs'][-1]['status'],'failed')
        self.assertTrue(all(r['status']=='queued' and not r['reply'] for r in view['records']))
    def test_user_edit_during_model_run_is_not_overwritten(self):
        job,records=self.prepare()
        def edit(_):self.console.edit({'id':records[0]['id'],'revision':records[0]['revision'],'reply':'这是我本人写的回复'})
        with patch('comment_ai.subprocess.Popen',return_value=self.model(job,records,edit)):comment_ai.run(self.console,job,records)
        view=self.console.view();self.assertEqual(view['records'][0]['reply'],'这是我本人写的回复')
        self.assertEqual(view['jobs'][-1]['status'],'failed');self.assertEqual(view['records'][1]['status'],'queued')
    def test_repeated_click_does_not_start_two_models(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError,'已有'):comment_ai.start(self.state,WORK)
    def test_not_ready_leaves_pending_comments_untouched(self):
        with patch('comment_ai.research_ai.status',return_value={'ready':False}):
            with self.assertRaises(ValueError):comment_ai.start(self.state,WORK)
        self.assertEqual(self.console.view()['jobs'],[])
        self.assertTrue(all(r['status']=='pending' for r in self.console.view()['records']))
    def test_saved_drafts_are_never_regenerated(self):
        rows=self.console.view()['records']
        for r in rows:self.console.edit({'id':r['id'],'revision':r['revision'],'reply':'已保存的回复'})
        with patch('comment_ai.research_ai.status',side_effect=AssertionError('existing drafts need no model')),patch.object(threading.Thread,'start') as launch:
            result=comment_ai.start(self.state,WORK)
        self.assertEqual(result['status'],'drafts_ready');self.assertEqual(result['draft_count'],len(rows))
        launch.assert_not_called();self.assertEqual(self.console.view()['jobs'],[])
        self.assertTrue(all(r['reply']=='已保存的回复' for r in self.console.view()['records']))
    def test_repeated_generation_of_ready_drafts_is_idempotent(self):
        for r in self.console.view()['records']:self.console.edit({'id':r['id'],'revision':r['revision'],'reply':'请先审核我'})
        before=self.console.view()
        for _ in range(2):self.assertEqual(dispatch(self.state,'generate',{'work_id':WORK['id']},[WORK])['status'],'drafts_ready')
        self.assertEqual(self.console.view(),before)
    def test_empty_work_points_to_read_comments(self):
        with self.assertRaisesRegex(ValueError,'先读取'):comment_ai.start(self.state,dict(WORK,id='empty-work'))
        self.assertEqual(self.console.view()['jobs'],[])
    def test_skipped_comments_do_not_silently_regenerate(self):
        for r in self.console.view()['records']:self.console.edit({'id':r['id'],'revision':r['revision'],'reply':'','skip':True})
        with patch.object(threading.Thread,'start') as launch:result=comment_ai.start(self.state,WORK)
        self.assertEqual(result['status'],'nothing_pending');launch.assert_not_called()
    def test_pending_generation_preserves_other_saved_drafts(self):
        first=self.console.view()['records'][0];self.console.edit({'id':first['id'],'revision':first['revision'],'reply':'已审核的文字'})
        job,records=self.prepare();self.assertEqual(len(records),1)
        with patch('comment_ai.subprocess.Popen',return_value=self.model(job,records)):comment_ai.run(self.console,job,records)
        saved=next(r for r in self.console.view()['records'] if r['id']==first['id'])
        self.assertEqual(saved['reply'],'已审核的文字');self.assertEqual(saved['revision'],first['revision']+1)
    def test_request_must_target_current_public_work(self):
        with self.assertRaises(ValueError):dispatch(self.state,'generate',{'work_id':'missing'},[WORK])

if __name__=='__main__':unittest.main()

import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from comments import Console,dispatch,MODULE,PROCESSES
from comment_runtime import prepare,replace_once

WORK={'id':'work1','title':'完整 作品 #赛车','pub_date':'2026-10-01 12:00:00','status':'公开'}
EXPORT={'selectedWork':{'title':'完整作品#赛车','publishText':'发布于 2026-10-01 12:00'},'comments':[{'username':'观众甲','commentText':'很棒的一次比赛'},{'username':'观众乙','commentText':'这是什么车型？'}]}

class CommentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.c=Console(Path(self.temp.name))
        with self.c.transaction() as d:self.c.merge(d,WORK,EXPORT)
    def tearDown(self):self.temp.cleanup();PROCESSES.clear()
    def rows(self):return self.c.view()['records']
    def draft(self):
        r=self.rows()[0];self.c.edit({'id':r['id'],'revision':r['revision'],'reply':'谢谢关注这场比赛！'})
        return self.rows()[0]
    def batch(self):
        r=self.draft();return self.c.preview([r['id']],[WORK])
    def test_dedupe(self):
        with self.c.transaction() as d:self.assertEqual(self.c.merge(d,WORK,EXPORT),0)
        self.assertEqual(len(self.rows()),2)
    def test_export_validates_all_before_merge(self):
        invalid=copy.deepcopy(EXPORT);invalid['comments'].append({'username':'','commentText':'bad'})
        with self.c.transaction() as d:
            with self.assertRaises(ValueError):self.c.merge(d,WORK,invalid)
        self.assertEqual(len(self.rows()),2)
    def test_stale_edit_cannot_overwrite(self):
        r=self.draft()
        with self.assertRaises(ValueError):self.c.edit({'id':r['id'],'revision':1,'reply':'旧内容'})
        self.assertEqual(self.rows()[0]['reply'],'谢谢关注这场比赛！')
    def test_long_reply_rejected(self):
        r=self.rows()[0]
        with self.assertRaises(ValueError):self.c.edit({'id':r['id'],'revision':1,'reply':'字'*201})
    def test_queue_revisions_and_user_override(self):
        self.c.queue('work1');r=self.c.pending()['records'][0]
        self.c.edit({'id':r['id'],'revision':r['revision'],'reply':'本人修改'})
        with self.assertRaises(ValueError):self.c.apply_drafts({'drafts':[dict(r,reply='AI旧稿')]})
        self.assertEqual(self.rows()[0]['reply'],'本人修改')
    def test_drafts_save_skip_and_no_send(self):
        self.c.queue('work1');rs=self.c.pending()['records']
        result=self.c.apply_drafts({'drafts':[dict(rs[0],reply='谢谢关注！'),dict(rs[1],reply='',skip_reason='车型需要核实')]})
        self.assertEqual(result['applied'],2);self.assertEqual([r['status'] for r in self.rows()],['draft','skip']);self.assertEqual(self.c.view()['jobs'],[])
    def test_preview_requires_saved_draft(self):
        with self.assertRaises(ValueError):self.c.preview([self.rows()[0]['id']],[WORK])
        r=self.draft()
        with self.assertRaises(ValueError):self.c.preview([r['id']]*2,[WORK])
        with self.assertRaises(ValueError):self.c.preview([r['id']],[WORK,dict(WORK,id='other')])
    def test_changed_draft_invalidates_batch(self):
        b=self.batch();r=self.rows()[0];self.c.edit({'id':r['id'],'revision':r['revision'],'reply':'更新内容'})
        with self.assertRaises(ValueError):self.c.start('send',batch_id=b['id'],token=b['digest'])
    def test_expired_batch_and_no_confirmation(self):
        b=self.batch()
        with self.c.transaction() as d:d['batches'][0]['epoch']=0
        with self.assertRaises(ValueError):self.c.start('send',batch_id=b['id'],token=b['digest'])
        with self.assertRaises(ValueError):dispatch(Path(self.temp.name),'send',{'batch_id':b['id'],'digest':b['digest']},[WORK])
    def test_batch_immutable_single_use_without_running_browser(self):
        b=self.batch()
        with patch.object(threading.Thread,'start') as start:
            result=self.c.start('send',batch_id=b['id'],token=b['digest'])
            self.assertEqual(start.call_count,1)
        self.assertEqual(self.rows()[0]['status'],'sending')
        with self.assertRaises(ValueError):self.c.start('send',batch_id=b['id'],token=b['digest'])
        job=next(j for j in self.c.view()['jobs'] if j['id']==result['job_id'])
        with self.c.transaction() as d:self.c.sent_result(d,job,{'repliedCount':1},None);d['jobs'][0]['status']='done'
        self.assertEqual(self.rows()[0]['status'],'uncertain')
        with self.assertRaises(ValueError):self.c.preview([b['items'][0]['id']],[WORK])
    def test_restart_locks_sending(self):
        b=self.batch()
        with patch.object(threading.Thread,'start'):self.c.start('send',batch_id=b['id'],token=b['digest'])
        PROCESSES.clear();view=self.c.view()
        self.assertEqual(view['jobs'][0]['status'],'interrupted');self.assertEqual(view['records'][0]['status'],'uncertain')
    def test_export_argv_does_not_use_shell(self):
        cmd=self.c.command('export',dict(WORK,title='$(touch /tmp/never) `whoami`'),out=Path('/tmp/test-output'))
        self.assertIn('$(touch /tmp/never) `whoami`',cmd);self.assertIn('--no-history',cmd)
    def test_json_permissions(self):
        self.assertEqual(self.c.path.stat().st_mode&0o777,0o600)
    def test_runtime_guards_match_installed_source(self):
        runtime=prepare(MODULE,self.c.root)
        text=(runtime/'src/comment-workflow.mjs').read_text()
        self.assertLess(text.index('if (actualTitle !== expectedTitle)'),text.index('const replySummary = await replyToComments'))
        flow=(runtime/'src/lib/reply-flow.mjs').read_text()
        self.assertIn('const requireCommentMatch = true;',flow)
        self.assertNotIn('normalizedLeft.includes(normalizedRight)',flow)
        self.assertIn('Never retry a possibly submitted comment',flow)
        self.assertIn('remainingPlanCount > 1 || visibleCommentCount > 1',(MODULE/'src/lib/reply-flow.mjs').read_text())
    def test_wrong_publication_or_full_title_is_rejected(self):
        for wrong in [{'title':'完整作品#赛车','publishText':'发布于 2026-10-02 12:00'}, {'title':'另一条作品','publishText':'发布于 2026-10-01 12:00'}]:
            invalid=copy.deepcopy(EXPORT);invalid['selectedWork']=wrong
            with self.c.transaction() as d:
                with self.assertRaises(ValueError):self.c.merge(d,WORK,invalid)
        self.assertEqual(len(self.rows()),2)
    def test_removed_work_cannot_send_old_preview(self):
        b=self.batch()
        with self.assertRaises(ValueError):dispatch(Path(self.temp.name),'send',{'confirmed':True,'batch_id':b['id'],'digest':b['digest']},[])
    def test_private_duplicate_title_blocks_preview(self):
        r=self.draft()
        with self.assertRaises(ValueError):self.c.preview([r['id']],[WORK,dict(WORK,id='private-copy',status='自见')])
    def test_unknown_runtime_version_aborts(self):
        with self.assertRaises(ValueError):replace_once('new version','old code','patch')



class HttpBoundaryTests(unittest.TestCase):
    def setUp(self):
        import server
        from http.server import ThreadingHTTPServer
        self.temp=tempfile.TemporaryDirectory()
        self.state=patch.object(server,'STATE',Path(self.temp.name));self.state.start()
        self.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.state.stop();self.temp.cleanup()
    def call(self,path,headers):
        import http.client
        c=http.client.HTTPConnection('127.0.0.1',self.http.server_port)
        c.request('POST',path,json.dumps({'confirmed':False}),headers)
        response=c.getresponse();result=(response.status,json.loads(response.read()));c.close();return result
    def test_comment_mutations_require_same_origin(self):
        self.assertEqual(self.call('/api/comments/send',{'Content-Type':'application/json'})[0],403)
        self.assertEqual(self.call('/api/comments/auth',{'Content-Type':'application/json','Origin':'https://other.example'})[0],403)
    def test_send_without_batch_confirmation_is_rejected(self):
        status,data=self.call('/api/comments/send',{'Content-Type':'application/json','Origin':'http://127.0.0.1:8766'})
        self.assertEqual(status,400);self.assertIn('确认',data['error'])
    def test_wrong_media_type_rejected(self):
        self.assertEqual(self.call('/api/comments/send',{'Content-Type':'text/plain','Origin':'http://127.0.0.1:8766'})[0],403)

if __name__=="__main__":unittest.main()

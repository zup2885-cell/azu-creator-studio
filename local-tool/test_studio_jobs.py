import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from openpyxl import Workbook
import server
import studio_jobs as jobs
from operations import atomic_json,read_state
from test_server import fixture

class CreatorCollection(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.state=Path(self.temp.name)
        self.patch=patch.multiple(server,STATE=self.state,IMPORTS=self.state/'dashboard-imports');self.patch.start()
        self.original=fixture();atomic_json(self.state/'exports/抖音数据_before.json',self.original)
    def tearDown(self):jobs.ACTIVE.clear();self.patch.stop();self.temp.cleanup()
    def excel(self,title='公开示例'):
        path=self.state/'creator-sync/downloads/new.xlsx';path.parent.mkdir(parents=True,exist_ok=True)
        book=Workbook();sheet=book.active
        sheet.append(['作品名称','发布时间','审核状态','播放量','完播率'])
        sheet.append([title,'2026-01-01 12:00:00','公开',123,.125]);book.save(path)
        return path
    def worker(self,event,code=0):
        class Process:
            pid=999999;returncode=code
            stdout=io.StringIO(json.dumps(event)+'\n')
            def wait(self,timeout=None):return self.returncode
            def poll(self):return self.returncode
        return Process()
    def test_real_excel_validated_then_imported_and_old_snapshot_retained(self):
        source=self.excel()
        with patch('studio_jobs.subprocess.Popen',return_value=self.worker({'phase':'complete','file':str(source)})):
            result=jobs.start(self.state,'sync',False)
        self.assertEqual(result['status'],'complete')
        rows=server.snapshots()[0];self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['totals']['plays'],123)
        self.assertEqual(rows[0]['rows'][0]['finish'],12.5)
        self.assertEqual(read_state(self.state)['phase'],'analysis_pending')
    def test_failed_download_preserves_old_data_and_success_time(self):
        atomic_json(self.state/'automation-status.json',{'last_success_at':'2026-01-01 12:00:00'})
        with patch('studio_jobs.subprocess.Popen',return_value=self.worker({'phase':'failed','message':'登录需要更新'},1)):
            result=jobs.start(self.state,'sync',False)
        self.assertEqual(result['status'],'failed');self.assertEqual(len(server.snapshots()[0]),1)
        self.assertEqual(read_state(self.state)['last_success_at'],'2026-01-01 12:00:00')
    def test_cover_failure_does_not_discard_successful_metrics(self):
        source=self.excel()
        with patch('studio_jobs.subprocess.Popen',return_value=self.worker({'phase':'complete','file':str(source),'metadata_file':str(self.state/'creator-sync/work-metadata.json')})):
            result=jobs.start(self.state,'sync',False)
        self.assertEqual(result['status'],'complete')
        self.assertIn('cover_warning',result['result']);self.assertEqual(server.snapshots()[0][0]['totals']['plays'],123)
    def test_foreign_account_export_never_replaces_data(self):
        source=self.excel('不属于原账号的作品')
        with patch('studio_jobs.subprocess.Popen',return_value=self.worker({'phase':'complete','file':str(source)})):
            result=jobs.start(self.state,'sync',False)
        self.assertEqual(result['status'],'failed');self.assertIn('交集',result['message'])
        self.assertEqual(len(server.snapshots()[0]),1)
    def test_unexpected_download_path_is_rejected(self):
        with patch('studio_jobs.subprocess.Popen',return_value=self.worker({'phase':'complete','file':'/tmp/untrusted.xlsx'})):
            result=jobs.start(self.state,'sync',False)
        self.assertEqual(result['status'],'failed');self.assertIn('导出路径',result['message'])
    def test_duplicate_click_does_not_launch_second_job(self):
        with patch.object(threading.Thread,'start') as started:
            first=jobs.start(self.state,'sync')
            with self.assertRaisesRegex(ValueError,'已有'):jobs.start(self.state,'sync')
        self.assertEqual(started.call_count,1);self.assertEqual(jobs.view(self.state)['id'],first['id'])
    def test_single_review_freezes_selected_video_and_rejects_second_click(self):
        snap=server.snapshots()[0][0];row=snap['rows'][0]
        with patch('research_ai.status',return_value={'ready':True}),patch.object(threading.Thread,'start') as started:
            first=jobs.start(self.state,'review',request={'snapshot_id':snap['id'],'work_id':row['id'],'notes':'用户观察'})
            with self.assertRaisesRegex(ValueError,'已有'):jobs.start(self.state,'review',request={})
        self.assertEqual(first['review_input']['work_id'],row['id'])
        self.assertEqual(first['review_input']['source_sha256'],snap['sha256'])
        self.assertEqual(first['review_input']['notes'],'用户观察');self.assertEqual(started.call_count,1)
    def test_restart_marks_dead_owner_interrupted_without_retry(self):
        atomic_json(self.state/'creator-sync/job.json',{'id':'old','status':'running','owner_pid':99999999})
        with patch('studio_jobs.subprocess.Popen') as run:result=jobs.view(self.state)
        self.assertEqual(result['status'],'interrupted');run.assert_not_called()
    def test_other_live_process_job_is_not_marked_interrupted(self):
        atomic_json(self.state/'creator-sync/job.json',{'id':'external','status':'running','owner_pid':os.getppid()})
        self.assertEqual(jobs.view(self.state)['status'],'running')
    def test_comment_task_blocks_creator_collection(self):
        atomic_json(self.state/'comment-console/console.json',{'records':[],'jobs':[{'id':'j','status':'running'}],'batches':[],'connection':'verified'})
        with self.assertRaisesRegex(ValueError,'评论浏览器'):jobs.start(self.state,'sync')
    def test_freshness_exposes_stale_data_instead_of_green_loading_timestamp(self):
        payload=server.payload()
        self.assertTrue(payload['freshness']['is_stale']);self.assertTrue(payload['freshness']['time_verified'])
    def test_real_http_import_uses_excel_limit_without_media_local_shadow(self):
        http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        try:
            request=urllib.request.Request(f'http://127.0.0.1:{http.server_port}/api/import',data=json.dumps(self.original).encode(),headers={'Content-Type':'application/octet-stream','Origin':'http://127.0.0.1:8766','X-Filename':'repeated.json'})
            with urllib.request.urlopen(request,timeout=3) as response:result=json.load(response)
            self.assertTrue(result['duplicate']);self.assertEqual(len(server.snapshots()[0]),1)
        finally:http.shutdown();http.server_close();thread.join()

if __name__=='__main__':unittest.main()

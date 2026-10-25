import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import operations
import server
from test_server import fixture

class DailyWorkflow(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.state=Path(self.temp.name)
        self.patch=patch.multiple(server,STATE=self.state,IMPORTS=self.state/'dashboard-imports');self.patch.start()
        exports=self.state/'exports';exports.mkdir()
        self.source=exports/'抖音数据_test.json';self.source.write_text(json.dumps(fixture(),ensure_ascii=False))
    def tearDown(self):self.patch.stop();self.temp.cleanup()
    def report(self):
        context=operations.analysis_context()
        return {'snapshot_id':context['snapshot_id'],'source_sha256':context['source_sha256'],'summary':'仅依据公开作品的测试报告。','findings':[{'title':'观察','evidence':'公开示例播放100次。','interpretation':'样本不足，不能推断稳定趋势。'}],'actions':['补充同条件样本。'],'limitations':['没有观看原片。']}
    def test_default_and_configured_state(self):
        self.assertFalse(operations.read_state(self.state)['enabled'])
        operations.update_state(self.state,enabled=True,automation_id='test',phase='capture_pending')
        result=operations.read_state(self.state)
        self.assertTrue(result['enabled']);self.assertFalse(result['api_connected'])
        self.assertEqual(result['schedule_label'],'每天 21:00（北京时间）')
    def test_context_excludes_private_works(self):
        result=operations.analysis_context()
        self.assertEqual(len(result['public_works']),1)
        self.assertIsNone(result['baseline_capture_time'])
    def test_report_binds_exact_snapshot(self):
        doc=self.report();path=self.state/'report.json';path.write_text(json.dumps(doc))
        operations.save_analysis(path)
        reports=operations.read_analyses(self.state,server.snapshots()[0])
        self.assertEqual(len(reports),1);self.assertEqual(reports[0]['provider'],'Codex 自动化')
        self.assertEqual((self.state/'analyses/抖音数据_test.json').stat().st_mode&0o777,0o600)
    def test_stale_report_rejected(self):
        doc=self.report();doc['source_sha256']='wrong'
        path=self.state/'report.json';path.write_text(json.dumps(doc))
        with self.assertRaises(ValueError):operations.save_analysis(path)
        self.assertFalse((self.state/'analyses').exists())
    def test_missing_evidence_rejected(self):
        doc=self.report();del doc['findings'][0]['evidence']
        path=self.state/'report.json';path.write_text(json.dumps(doc))
        with self.assertRaises(ValueError):operations.save_analysis(path)
    def test_changed_snapshot_hides_old_report(self):
        doc=self.report();path=self.state/'report.json';path.write_text(json.dumps(doc));operations.save_analysis(path)
        changed=fixture();changed['parsed_rows'][0]['plays']=120
        self.source.write_text(json.dumps(changed))
        self.assertEqual(operations.read_analyses(self.state,server.snapshots()[0]),[])
    def test_old_excel_rejected(self):
        from openpyxl import Workbook
        import os
        path=self.state/'old.xlsx';book=Workbook();sheet=book.active
        sheet.append(['作品名称','发布时间','审核状态','播放量']);sheet.append(['公开示例','2026-01-01 12:00:00','公开',100]);book.save(path)
        os.utime(path,(0,0))
        with self.assertRaisesRegex(ValueError,'旧文件'):operations.ingest_excel(path,operations.timestamp())
    def test_fresh_excel_creates_verified_capture(self):
        from openpyxl import Workbook
        path=self.state/'fresh.xlsx';book=Workbook();sheet=book.active
        sheet.append(['作品名称','发布时间','审核状态','播放量','完播率']);sheet.append(['公开示例','2026-01-01 12:00:00','公开',120,.125]);book.save(path)
        result=operations.ingest_excel(path,operations.timestamp())
        self.assertEqual(result['totals']['plays'],120)
        context=operations.analysis_context()
        self.assertEqual(context['matched_work_changes'][0]['plays_change'],20)
        self.assertEqual(context['public_works'][0]['finish'],12.5)
        self.assertTrue(operations.read_state(self.state)['last_success_at'])

if __name__=='__main__':unittest.main()

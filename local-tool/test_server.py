"""Data/import contract tests, isolated from the user's live snapshots and database."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from openpyxl import Workbook
import server

def fixture():
    rows=[]
    for title,status,plays in [('公开示例','公开',100),('私密示例','自见',0)]:
        r={'title':title,'status':status,'pub_date':'2026-01-01 12:00:00','format':'1-3min视频'}
        r.update({k:2 for k in server.FIELDS})
        r.update(plays=plays,finish=12.5,ctr5s=55.0,ctrcov=None,bounce=20,duration=15.3)
        rows.append(r)
    return {'capture_time':'2026-01-02 12:00:00','parsed_rows':rows}

class DataContract(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.state=Path(self.temp.name)
        self.patch=patch.multiple(server,STATE=self.state,IMPORTS=self.state/'dashboard-imports')
        self.patch.start()
    def tearDown(self):
        self.patch.stop();self.temp.cleanup()
    def store(self,doc,name='抖音数据_test.json'):
        path=self.state/'exports'/name;path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(doc,ensure_ascii=False));return path
    def test_private_metrics_excluded(self):
        snap=server.capture(self.store(fixture()))
        self.assertEqual(snap['totals']['plays'],100)
        self.assertEqual(snap['totals']['likes'],2)
        self.assertEqual((snap['public_count'],snap['private_count']),(1,1))
    def test_missing_and_zero_are_distinct(self):
        doc=fixture();doc['parsed_rows'][1]['ctrcov']=0
        snap=server.capture(self.store(doc))
        self.assertIsNone(snap['rows'][0]['ctrcov'])
        self.assertEqual(snap['rows'][1]['ctrcov'],0)
        self.assertEqual(snap['missing_counts']['ctrcov'],1)
    def test_missing_total_does_not_become_zero(self):
        doc=fixture();doc['parsed_rows'][0]['plays']=None
        snap=server.capture(self.store(doc));self.assertIsNone(snap['totals']['plays'])
    def test_rate_boundaries(self):
        self.assertEqual(server.number('0.142212','ctrcov',True),14.2212)
        self.assertEqual(server.number('14.22%','ctrcov',True),14.22)
        self.assertEqual(server.number(100,'finish'),100)
        for value in [101,-1,'NaN','Infinity']:
            with self.assertRaises(ValueError):server.number(value,'finish')
    def test_integer_validation(self):
        for value in [1.5,-1,'NaN',9007199254740992]:
            with self.assertRaises(ValueError):server.number(value,'plays')
    def test_invalid_dates_and_duplicates(self):
        doc=fixture();doc['parsed_rows'][0]['pub_date']='2026-02-31 12:00:00'
        with self.assertRaises(ValueError):server.normalize(doc)
        doc=fixture();doc['parsed_rows'].append(copy.deepcopy(doc['parsed_rows'][0]))
        with self.assertRaises(ValueError):server.normalize(doc)
    def test_json_import_and_repeat(self):
        content=json.dumps(fixture()).encode()
        result=server.import_file(content,'sample.json')
        self.assertFalse(result['duplicate'])
        self.assertTrue(server.import_file(content,'again.json')['duplicate'])
        files=list(server.IMPORTS.glob('*.json'));self.assertEqual(len(files),1)
        self.assertEqual(files[0].stat().st_mode&0o777,0o600)
    def test_xlsx_import_marks_time(self):
        book=Workbook();s=book.active
        s.append(['作品名称','发布时间','审核状态','播放量','完播率','封面点击率'])
        s.append(['Excel示例','2026-01-01 12:00:00','公开',200,.125,'-'])
        buf=io.BytesIO();book.save(buf)
        result=server.import_file(buf.getvalue(),'作品列表.xlsx')
        self.assertEqual(result['time_kind'],'import')
        snap=server.snapshots()[0][0]
        self.assertEqual(snap['rows'][0]['finish'],12.5)
        self.assertIsNone(snap['rows'][0]['ctrcov'])
        self.assertIsNone(snap['totals']['likes'])
    def test_corrupt_snapshot_is_isolated(self):
        self.store(fixture());self.store([],name='抖音数据_invalid.json')
        valid,errors=server.snapshots()
        self.assertEqual((len(valid),len(errors)),(1,1))
    def test_export_csv_preserves_blanks_and_filters(self):
        path=self.store(fixture())
        content,_=server.export_csv(path.stem,'公开','示例','plays')
        import csv
        rows=list(csv.reader(io.StringIO(content.decode('utf-8-sig'))))
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[1][0],'公开示例')
        self.assertEqual(rows[1][3],'100')
        self.assertEqual(rows[1][6],'')
    def test_export_formula_escaping(self):
        doc=fixture();doc['parsed_rows'][0]['title']=' =SUM(A1:A2)'
        path=self.store(doc);content,_=server.export_csv(path.stem)
        self.assertIn("'=SUM(A1:A2)",content.decode('utf-8-sig'))
    def test_invalid_imports_do_not_write(self):
        for content,name in [(b'[]','a.json'),(b'not json','a.json'),(b'not excel','a.xlsx'),(b'text','a.txt')]:
            with self.assertRaises((ValueError,Exception)):server.import_file(content,name)
        self.assertFalse(server.IMPORTS.exists())

if __name__=='__main__':unittest.main()

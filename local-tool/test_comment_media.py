import copy
from pathlib import Path
import subprocess
import tempfile
import unittest

from comments import Console,MODULE,NODE,dispatch
from comment_export_runtime import prepare
from test_comments import WORK,EXPORT


class MediaComments(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.state=Path(self.temp.name);self.console=Console(self.state)
    def tearDown(self):self.temp.cleanup()
    def media_export(self):
        result=copy.deepcopy(EXPORT)
        result['comments'] += [dict(username='同一用户',commentText='[图片/表情评论]',mediaOnly=True,mediaKeys=[key]) for key in ['/obj/image-a','/obj/image-b']]
        return result
    def test_text_and_two_distinct_images_from_same_user_are_all_preserved(self):
        with self.console.transaction() as doc:self.assertEqual(self.console.merge(doc,WORK,self.media_export()),4)
        rows=self.console.view()['records'];self.assertEqual(len(rows),4)
        self.assertEqual([r['status'] for r in rows],['pending','pending','media','media'])
        self.assertNotEqual(rows[2]['id'],rows[3]['id'])
    def test_repeated_media_export_does_not_create_duplicates_or_erase_drafts(self):
        with self.console.transaction() as doc:self.console.merge(doc,WORK,self.media_export())
        row=self.console.view()['records'][0];self.console.edit({'id':row['id'],'revision':1,'reply':'保留这份回复'})
        with self.console.transaction() as doc:self.assertEqual(self.console.merge(doc,WORK,self.media_export()),0)
        self.assertEqual(self.console.view()['records'][0]['reply'],'保留这份回复')
    def test_media_is_excluded_from_ai_queue_and_cannot_be_sent_as_placeholder(self):
        with self.console.transaction() as doc:self.console.merge(doc,WORK,self.media_export())
        self.console.queue(WORK['id']);self.assertEqual(len(self.console.pending()['records']),2)
        media=self.console.view()['records'][2]
        with self.assertRaisesRegex(ValueError,'图片'):self.console.edit({'id':media['id'],'revision':1,'reply':'猜测图片内容'})
        with self.console.transaction() as doc:doc['records'][2].update(status='draft',reply='不能据此发送')
        with self.assertRaisesRegex(ValueError,'图片'):self.console.preview([media['id']],[WORK])
    def test_invalid_media_identity_is_rejected_before_any_merge(self):
        result=self.media_export();result['comments'][-1]['mediaKeys']=[]
        with self.console.transaction() as doc:
            with self.assertRaises(ValueError):self.console.merge(doc,WORK,result)
        self.assertEqual(self.console.view()['records'],[])
    def test_export_runtime_has_media_adapter_without_altering_upstream(self):
        original=(MODULE/'src/lib/comment-snapshot.mjs').read_text()
        runtime=prepare(MODULE,self.console.root)
        snapshot=(runtime/'src/lib/comment-snapshot.mjs').read_text()
        self.assertIn('CDN signatures expire',snapshot)
        self.assertIn('mediaOnly: currentMainComment.mediaOnly',snapshot)
        workflow=(runtime/'src/comment-workflow.mjs').read_text()
        self.assertNotIn('await downloadCommentImages(exportComments, outputPath)',workflow)
        self.assertIn('replyThreadsExpanded:false',workflow)
        self.assertEqual(original,(MODULE/'src/lib/comment-snapshot.mjs').read_text())
        subprocess.run([str(NODE),'--check',str(runtime/'src/lib/comment-snapshot.mjs')],check=True,capture_output=True)
        subprocess.run([str(NODE),'--check',str(runtime/'src/comment-workflow.mjs')],check=True,capture_output=True)
    def test_final_export_keeps_distinct_images_and_reports_actual_count(self):
        runtime=prepare(MODULE,self.console.root)
        script='''import assert from "node:assert/strict";
import {prepareResultForOutput} from "MODULE_URL";
const a={username:"same-user",commentText:"[image]",mediaOnly:true,mediaKeys:["/image-a"]};
const b={...a,mediaKeys:["/image-b"]};
const result=prepareResultForOutput({count:3,collection:{exported:3,mediaOnly:3},comments:[a,b,a]});
assert.equal(result.comments.length,2);assert.equal(result.count,2);
assert.equal(result.collection.exported,2);assert.equal(result.collection.mediaOnly,2);
'''.replace('MODULE_URL',(runtime/'src/lib/result-store.mjs').as_uri())
        subprocess.run([str(NODE),'--input-type=module','-e',script],check=True,capture_output=True)


if __name__=='__main__':unittest.main()

"""Discovery settings and scheduling contracts; no platform or account requests."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from research import Research,normalize_item
from research_discovery import preferences,save_preferences,qualifies,start_discovery,choose_tracks


class DiscoveryContract(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.r=Research(Path(self.tmp.name))

    def tearDown(self):self.tmp.cleanup()

    def setup_tracks(self,names=('汽车',),auto=True):
        body=preferences(self.r)
        body.update(tracks=[{'id':f'{i+1:016x}','name':n,'enabled':True} for i,n in enumerate(names)],auto_update=auto)
        return save_preferences(self.r,body)['preferences']

    def test_initial_state_has_no_invented_subscriptions(self):
        prefs=preferences(self.r)
        self.assertEqual(prefs['tracks'],[])
        self.assertTrue(all(v==50000 for v in prefs['thresholds'].values()))
        with patch.object(self.r,'run_search') as run:
            self.assertTrue(start_discovery(self.r,{'scheduled':True},False)['skipped'])
            run.assert_not_called()

    def test_checked_options_save_and_trigger_collection_without_typed_query(self):
        prefs=self.setup_tracks()
        ident=prefs['tracks'][0]['id']
        with patch('research_discovery.start_discovery',return_value={'ok':True,'task_id':'a'*24}) as start:
            result=choose_tracks(self.r,{'revision':prefs['revision'],'names':['汽车','美食']})
        start.assert_called_once_with(self.r,{})
        self.assertEqual([t['name'] for t in result['preferences']['tracks']],['汽车','美食'])
        self.assertEqual(result['preferences']['tracks'][0]['id'],ident)
        self.assertTrue(all(t['enabled'] for t in result['preferences']['tracks']))
        self.assertTrue(all(n==50000 for n in result['preferences']['thresholds'].values()))

    def test_cancelled_or_invalid_options_do_not_start_collection(self):
        prefs=self.setup_tracks()
        with patch('research_discovery.start_discovery') as start:
            for names in (['全部'],['not-a-choice'],['汽车','汽车'],[None]):
                with self.assertRaises(ValueError):choose_tracks(self.r,{'revision':prefs['revision'],'names':names})
            result=choose_tracks(self.r,{'revision':prefs['revision'],'names':[]})
        start.assert_not_called()
        self.assertEqual(result['preferences']['tracks'],[])

    def test_active_collection_preserves_new_option_selection_for_daily_update(self):
        with patch('research_discovery.start_discovery',side_effect=ValueError('already running')):
            result=choose_tracks(self.r,{'revision':0,'names':['人物故事']})
        self.assertEqual(result['preferences']['tracks'][0]['name'],'人物故事')
        self.assertNotIn('discovery',result)

    def test_stale_option_dialog_does_not_restore_removed_tracks_or_start_collection(self):
        self.setup_tracks()
        with patch('research_discovery.start_discovery') as start:
            with self.assertRaises(ValueError):choose_tracks(self.r,{'revision':0,'names':['美食']})
        start.assert_not_called()

    def test_add_custom_pause_delete_and_persist_without_deleting_material(self):
        prefs=self.setup_tracks(('老车修复',))
        self.assertEqual(Research(Path(self.tmp.name)).preferences()['tracks'][0]['name'],'老车修复')
        item=normalize_item({'aweme_id':'123','title':'保存的作品','digg_count':15000});self.r.put(item,True)
        prefs['tracks'][0]['enabled']=False
        prefs=save_preferences(self.r,prefs)['preferences']
        self.assertFalse(prefs['tracks'][0]['enabled'])
        prefs['tracks']=[];save_preferences(self.r,prefs)
        self.assertEqual(preferences(self.r)['tracks'],[])
        self.assertTrue(self.r.items()[0]['saved'])

    def test_stale_revision_does_not_restore_deleted_tracks(self):
        initial=preferences(self.r);self.setup_tracks()
        with self.assertRaises(ValueError):save_preferences(self.r,initial)
        self.assertEqual(len(preferences(self.r)['tracks']),1)

    def test_invalid_names_duplicates_and_thresholds(self):
        for name in ('','全部','-bad','bad\nname','字'*31):
            body=preferences(self.r);body['tracks']=[{'name':name}]
            with self.assertRaises(ValueError):save_preferences(self.r,body)
        body=preferences(self.r);body['tracks']=[{'name':'AI'},{'name':'ai'}]
        with self.assertRaises(ValueError):save_preferences(self.r,body)
        for value in (0,-1,True,1.5,1000000001):
            body=preferences(self.r);body['thresholds']['youtube']=value
            with self.assertRaises(ValueError):save_preferences(self.r,body)

    def test_hit_boundary_missing_zero_and_per_platform_thresholds(self):
        prefs=preferences(self.r)
        for likes,expected in ((None,False),(0,False),(49999,False),(50000,True),(50001,True)):
            self.assertEqual(qualifies({'platform':'bilibili','metrics':{'likes':likes}},prefs),expected)
        prefs['thresholds']['bilibili']=100000
        self.assertFalse(qualifies({'platform':'bilibili','metrics':{'likes':75000}},prefs))
        self.assertTrue(qualifies({'platform':'youtube','metrics':{'likes':75000}},prefs))

    def test_only_enabled_user_tracks_are_collected_and_daily_attempt_is_deduped(self):
        prefs=self.setup_tracks(('汽车','美食'))
        prefs['tracks'][1]['enabled']=False;save_preferences(self.r,prefs)
        calls=[]
        def fake(task_id,doc):
            calls.append((doc['category'],doc['channel'],doc['query']))
            self.r.set_task(task_id,'search','complete',dict(doc,item_ids=[]))
        with patch.object(self.r,'run_search',side_effect=fake):
            first=start_discovery(self.r,{'scheduled':True},False)
            second=start_discovery(self.r,{'scheduled':True},False)
        self.assertEqual({q for q,p,query in calls},{'汽车'})
        self.assertEqual({p for q,p,query in calls},{'douyin','bilibili','youtube','xiaohongshu'})
        self.assertEqual(len(calls),4)
        self.assertEqual(next(query for q,p,query in calls if p=='youtube'),'car review')
        self.assertTrue(second['skipped'])
        self.assertEqual(self.r.task(first['task_id'])['status'],'complete')

    def test_disabled_auto_update_makes_no_scheduled_requests(self):
        self.setup_tracks(auto=False)
        with patch.object(self.r,'run_search') as run:
            self.assertTrue(start_discovery(self.r,{'scheduled':True},False)['skipped'])
            run.assert_not_called()

    def test_scheduled_flag_rejects_non_boolean_values(self):
        self.setup_tracks()
        for flag in ('false',1,None):
            with self.assertRaises(ValueError):start_discovery(self.r,{'scheduled':flag},False)

    def test_view_uses_real_likes_to_mark_hits(self):
        self.setup_tracks()
        for i,likes in enumerate((None,0,49999,50000,50001)):
            item=normalize_item({'aweme_id':str(100+i),'title':'候选','digg_count':likes,'research_category':'汽车'})
            self.r.put(item)
        rows=self.r.view()['items']
        self.assertEqual(sum(i['is_hit'] for i in rows),2)
        self.assertEqual({i['metrics']['likes'] for i in rows if i['is_hit']},{50000,50001})

    def test_only_one_batch_can_be_active(self):
        self.setup_tracks()
        with patch('research.POOL.submit'):
            start_discovery(self.r,{})
            with self.assertRaises(ValueError):start_discovery(self.r,{})
            self.assertTrue(start_discovery(self.r,{'scheduled':True},False)['skipped'])

    def test_deletion_while_request_in_flight_does_not_re_add_or_store_result(self):
        prefs=self.setup_tracks();track_id=prefs['tracks'][0]['id']
        prefs['tracks']=[];save_preferences(self.r,prefs)
        doc={'channel':'youtube','action':'search','query':'汽车','category':'汽车','track_id':track_id,'limit':1}
        with patch('research.subprocess.run') as run:
            run.return_value.stdout=json.dumps({'ok':True,'items':[{'url':'https://www.youtube.com/watch?v=xpyrefzvTpI','title':'候选','raw':{'like_count':20000}}]})
            self.r.run_search('a'*24,doc)
        self.assertEqual(self.r.items(),[])
        self.assertEqual(preferences(self.r)['tracks'],[])

    def test_verification_blocks_remaining_queries_for_that_platform(self):
        self.setup_tracks(('汽车','美食'));calls=[]
        def fake(task_id,doc):
            calls.append(doc['channel'])
            self.r.set_task(task_id,'search','complete',dict(doc,item_ids=[],enrichment_error='PLATFORM_BLOCKED' if doc['channel']=='youtube' else None))
        with patch.object(self.r,'run_search',side_effect=fake):start_discovery(self.r,{},False)
        self.assertEqual(calls.count('youtube'),1)
        self.assertEqual(calls.count('bilibili'),2)

    def test_all_platforms_failing_is_not_reported_as_success(self):
        self.setup_tracks()
        def unavailable(task_id,doc):
            self.r.set_task(task_id,'search','failed',dict(doc,error_code='NEED_LOGIN',message='需要本人登录'))
        with patch.object(self.r,'run_search',side_effect=unavailable):
            result=start_discovery(self.r,{},False)
        task=self.r.task(result['task_id'])
        self.assertEqual(task['status'],'failed')
        self.assertEqual(task['count'],0)
        self.assertIn('需要本人登录',task['message'])


if __name__=='__main__':unittest.main()

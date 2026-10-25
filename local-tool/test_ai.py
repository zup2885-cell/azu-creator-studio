"""AI bridge contracts without model requests or personal credentials."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research import Research,normalize_item
import research_ai as ai


class AIContract(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.state=Path(self.tmp.name);self.r=Research(self.state)
        self.skill=self.state/'SKILL.md';self.skill.write_text('只分析，不写稿。')
        self.skills=patch('research.skill_path',return_value=self.skill);self.skills.start()
        self.connection=patch('research_ai.status',return_value={'ready':True});self.connection.start()
        item=normalize_item({'url':'https://www.douyin.com/video/7606295532193577659','title':'真实样本','metrics':{'likes':185000},'metric_approximate':['likes']},'douyin','douyin-public-page')
        self.item=item;self.r.put(item,True)
    def tearDown(self):self.skills.stop();self.connection.stop();self.tmp.cleanup()
    def report(self,ident=None):
        return {'summary':'样本提供的线索有限，应继续核对原片。','findings':[{'title':'标题同时提出两个身份','evidence':'素材标题：真实样本','interpretation':'可用来提出后续研究问题。','item_ids':[ident or self.item['id']]}],'experiments':['核对原片前三秒'],'limitations':['未取得逐字稿，不能分析正文镜头。'],'brief':{'conclusion':'先核对原片，再判断是否借鉴。','points':[{'title':'标题线索','detail':'当前只有标题，不能直接判断镜头。','item_ids':[ident or self.item['id']]}],'actions':['核对原片前三秒与字幕。'],'caveat':'缺少已核对的字幕和画面。'},'breakdown':{'opening':'仅标题线索，开场待补原片。','beats':[],'pacing':'未取得时间证据。','borrow':'明确研究问题。','avoid':'不虚构正文。'},'decision':{'topic':'人物求学经历','angle':'竞技与学习安排','audience':'关心运动员经历的人','reason':'目前是标题线索，尚需原片验证。','sources':['核对原片字幕。']}}
    def fake_process(self,report=None,returncode=0,log=b''):
        owner=self
        class Process:
            pid=987654321
            def __init__(self,args,**kwargs):
                self.returncode=returncode;self.args=args;self.kwargs=kwargs
                kwargs['stderr'].write(log)
                Path(args[args.index('--output-last-message')+1]).write_text(json.dumps(report or owner.report(),ensure_ascii=False))
            def communicate(self,data,timeout):
                owner.last_prompt=data.decode();owner.last_command=self.args
                owner.last_env=self.kwargs['env'];return (None,None)
            def poll(self):return self.returncode
        return Process
    def run_local(self,report=None,returncode=0,log=b'',mode='strategy'):
        with patch('research_ai.binary',return_value='/official/codex'),patch('research_ai.model_options',return_value=[]),patch('research_ai.subprocess.Popen',side_effect=self.fake_process(report,returncode,log)):
            result=ai.start(self.r,{'ids':[self.item['id']],'mode':mode},background=False)
        return self.r.task(result['task_id'])
    def test_success_writes_valid_report_for_each_mode_with_frozen_evidence(self):
        for mode in ('strategy','creative'):
            task=self.run_local(mode=mode)
            self.assertEqual(task['status'],'complete')
            report=next(r for r in self.r.view()['reports'] if r['task_id']==task['id'])
            self.assertEqual(report['mode'],mode);self.assertEqual(report['input_snapshot'][0]['metrics']['likes'],185000)
            self.assertEqual(report['provider'],'本机 Codex · 自动分析')
            self.assertIn('brief',report)
            self.assertEqual(self.r.preferences()['tracks'],[])
        self.assertIn('不要调用工具',self.last_prompt)
        self.assertNotIn('由当前 Codex 用 research_cli.py finish',self.last_prompt)
        self.assertIn('绝不超过420字',self.last_prompt)

    def test_new_automatic_report_requires_reading_summary(self):
        report=self.report();report.pop('brief')
        task=self.run_local(report=report)
        self.assertEqual(task['status'],'failed');self.assertFalse(self.r.view()['reports'])
        self.assertIn('缺少简读内容',task['message'])
    def test_command_uses_official_login_no_shell_and_disables_other_agents_and_tools(self):
        with patch('research_ai.model_options',return_value=[]):args=ai.command('/official/codex',self.state)
        self.assertIn('read-only',args);self.assertIn('--ignore-user-config',args);self.assertIn('--ephemeral',args)
        for name in ('shell_tool','multi_agent','apps','plugins','hooks','browser_use','computer_use'):
            self.assertIn(['--disable',name], [args[i:i+2] for i in range(len(args)-1)])
        self.assertNotIn('--dangerously-bypass-approvals-and-sandbox',args)
        with patch.dict('research_ai.os.environ',{'OPENAI_API_KEY':'never-copy-this','CODEX_API_KEY':'never-copy-this'}):self.run_local()
        self.assertNotIn('OPENAI_API_KEY',self.last_env);self.assertNotIn('CODEX_API_KEY',self.last_env)
    def test_invalid_foreign_reference_never_saves_a_report(self):
        task=self.run_local(report=self.report('foreign-item'))
        self.assertEqual(task['status'],'failed');self.assertFalse(self.r.view()['reports'])
        self.assertIn('引用本次输入',task['message'])
    def test_model_failure_is_sanitized_not_reported_complete_or_retried(self):
        with patch('research_ai.subprocess.Popen',side_effect=self.fake_process(returncode=1,log=b'usage limit secret-cookie')) as process:
            result=ai.start(self.r,{'ids':[self.item['id']],'mode':'creative'},background=False)
        self.assertEqual(process.call_count,1)
        task=self.r.task(result['task_id']);self.assertEqual(task['status'],'failed')
        self.assertIn('额度',task['message']);self.assertNotIn('secret-cookie',str(task));self.assertFalse(self.r.view()['reports'])
    def test_only_link_is_rejected_before_any_model_or_task(self):
        item=normalize_item({'url':'https://www.douyin.com/video/7546165781764033819','title':'仅链接'},'douyin','link-only');self.r.put(item,True)
        with patch('research_ai.subprocess.Popen') as process:
            with self.assertRaisesRegex(ValueError,'只有链接'):ai.start(self.r,{'ids':[item['id']]})
        process.assert_not_called();self.assertFalse(self.r.view()['tasks'])
    def test_not_ready_rejects_before_freezing_and_concurrent_clicks_dont_duplicate(self):
        with patch('research_ai.status',return_value={'ready':False}):
            with self.assertRaises(ValueError):ai.start(self.r,{'ids':[self.item['id']]})
        self.assertFalse(self.r.view()['tasks'])
        with patch('research.POOL.submit') as submit:
            ai.start(self.r,{'ids':[self.item['id']]})
            with self.assertRaisesRegex(ValueError,'已有 AI 分析'):ai.start(self.r,{'ids':[self.item['id']]})
        self.assertEqual(submit.call_count,1)
    def test_restart_does_not_resubmit_analysis(self):
        with patch('research.POOL.submit') as submit:
            result=ai.start(self.r,{'ids':[self.item['id']]});self.r.recover()
        self.assertEqual(submit.call_count,1);self.assertEqual(self.r.task(result['task_id'])['status'],'interrupted')
    def test_bridge_is_opt_in_and_configuration_has_no_authentication_secret(self):
        self.assertFalse(ai.enabled(self.state))
        (self.state/'ai-analysis.json').write_text('{"enabled":true}')
        self.assertTrue(ai.enabled(self.state))


if __name__=='__main__':unittest.main()

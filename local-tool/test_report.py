"""Reading summaries preserve evidence scope and reject bloated/unknown claims."""
import copy
import unittest
from research_report import validate_brief


class ReadingSummaryContract(unittest.TestCase):
    def brief(self):
        return {'conclusion':'先核对运动员的身份与经历，再决定选题。','points':[{'title':'标题线索','detail':'标题提到冠军与学业身份，暂未独立核实。','item_ids':['known']}],'actions':['补齐核对字幕和赛事资料。'],'caveat':'只有1条样本，没有已核对画面。'}
    def test_preserves_qualifiers_numbers_and_valid_evidence_ids(self):
        brief=self.brief();brief['points'][0]['detail']='点赞约18.5万；标题里的身份暂未独立核实。'
        self.assertEqual(validate_brief(brief,['known']),brief)
        self.assertIn('约18.5万',brief['points'][0]['detail'])
    def test_unknown_or_missing_references_are_rejected(self):
        for refs in ([],['foreign'],[False],'known'):
            brief=self.brief();brief['points'][0]['item_ids']=refs
            with self.assertRaises(ValueError):validate_brief(brief,['known'])
    def test_oversized_or_empty_reading_sections_are_rejected_not_cut_mid_sentence(self):
        for field,size in (('conclusion',61),('caveat',71)):
            brief=self.brief();brief[field]='字'*size
            with self.assertRaises(ValueError):validate_brief(brief,['known'])
        for title,detail in (('字'*15,'说明'),('标题','字'*55),('','说明')):
            brief=self.brief();brief['points'][0].update(title=title,detail=detail)
            with self.assertRaises(ValueError):validate_brief(brief,['known'])
        brief=self.brief();brief['actions']=['字'*49]
        with self.assertRaises(ValueError):validate_brief(brief,['known'])
    def test_report_cannot_turn_into_another_long_list(self):
        brief=self.brief();brief['points']*=4
        with self.assertRaises(ValueError):validate_brief(brief,['known'])
        brief=self.brief();brief['actions']*=4
        with self.assertRaises(ValueError):validate_brief(brief,['known'])
        brief=self.brief();brief.update(conclusion='字'*60,caveat='字'*70,points=[{'title':'字'*14,'detail':'字'*54,'item_ids':['known']} for _ in range(3)],actions=['字'*48]*3)
        with self.assertRaisesRegex(ValueError,'420'):validate_brief(brief,['known'])


if __name__=='__main__':unittest.main()

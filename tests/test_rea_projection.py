"""IPC handler evidence must reach focus, explanation packets and source paging."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime/node-host'))
from jarvis_core import rea, rea_focus, rea_evidence, rea_explanation


class ProjectionTests(unittest.TestCase):
    def test_inferred_relations_cannot_be_promoted_by_model(self):
        raw={'findings':[{'kind':'observation','text':'注册映射','refs':['E1']}],'unknowns':['未运行']}
        result=rea_explanation.normalize_classification(raw,[{'ref':'E1','evidence_state':'inferred'}])
        self.assertEqual(result['findings'][0]['kind'],'inference')
        self.assertEqual(raw['findings'][0]['kind'],'observation')
        self.assertEqual(result['classification_adjustments'][0]['finding_index'],0)
        observed=rea_explanation.normalize_classification(raw,[{'ref':'E1','evidence_state':'observed'}])
        self.assertEqual(observed['findings'][0]['kind'],'observation')

    def test_handler_registration_is_not_lost_behind_imports(self):
        imports=[{'edge_id':'import-'+str(i),'relation':'imports','properties':{'specifier':'pkg'+str(i)}} for i in range(60)]
        handler={'edge_id':'handler','relation':'handles','properties':{'channel':'get-app-config'},
                 'evidence':{'state':'inferred','confidence':'high','location':{'available':True,'value':{'source':'Application.js','start':{'line':1012}}},
                             'limitations':['Static syntax does not prove execution.']}}
        evidence={'evidence_id':'ev_test','operation':'analyze_javascript_application','confidence':'derived','authority':'shipped-artifact',
                  'normalized_result':{'summary':{},'graph':{'nodes':[],'edges':imports+[handler]}}}
        view=rea.projection(evidence)
        self.assertEqual(view['key_links'][0]['edge_id'],'handler')
        view['focus']=rea_focus.inspect(evidence,{'focus':'get-app-config'})
        self.assertEqual(view['focus']['link_count'],1)
        packet,_=rea_explanation.packet({'analysis':view,'input_manifest':{'files':[],'omitted':[]}}, {'prompt':'解释注册位置'})
        self.assertEqual(packet['sources'][0]['evidence_state'],'inferred')
        self.assertEqual(packet['sources'][0]['ref'],'E1')
        page=rea_evidence.page(evidence,{},'links',query='get-app-config')
        self.assertEqual(page['total'],1);self.assertEqual(page['items'][0]['value']['edge_id'],'handler')

    def test_handler_body_and_runtime_behavior_are_never_added_by_projection(self):
        edge={'edge_id':'x','relation':'handles','properties':{'channel':'sum'}}
        row=rea_focus.project_link(edge)
        self.assertNotIn('body',row);self.assertIsNone(row['evidence_state'])
        self.assertFalse(rea_focus.matches(row,'sumExtra'))
        result=rea_focus.inspect({'normalized_result':{'graph':{'nodes':[],'edges':[edge]}}},{'focus':'missing'})
        self.assertFalse(result['matched']);self.assertEqual(result['link_count'],0)


if __name__=='__main__':unittest.main()

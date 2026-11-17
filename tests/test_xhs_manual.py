import unittest,tempfile
from pathlib import Path
from unittest.mock import patch
from studio.service import Service
from studio.adapters import execute
class ManualXhsTests(unittest.TestCase):
 def test_every_xhs_remote_action_rejected_before_launch(self):
  with tempfile.TemporaryDirectory() as d,patch('studio.adapters.account_paths',side_effect=AssertionError('must not touch account')):
   for action in ('login','check','draft','publish','open_drafts','query_publications','update_publication'):
    r=execute({'platform':'xiaohongshu','action':action,'payload':{}},{'state_root':d},lambda x:None)
    self.assertEqual(r['status'],'failed');self.assertTrue(r['evidence']['manual_only'])
 def test_service_rejects_xhs_but_keeps_local_copy(self):
  with tempfile.TemporaryDirectory() as d:
   s=Service(d,Path(d)/'data',start_worker=False)
   try:
    for action in ('login','check','query_publications','open_drafts'):
     with self.assertRaisesRegex(ValueError,'人工'):s.create_job({'platform':'xiaohongshu','action':action})
    self.assertNotIn('xiaohongshu',[a['platform'] for a in s.accounts()])
   finally:s.close()
 def test_legacy_queued_xhs_cancelled_on_start(self):
  with tempfile.TemporaryDirectory() as d:
   s=Service(d,Path(d)/'data',start_worker=False)
   s.store.put('jobs',{'id':'old','platform':'xiaohongshu','action':'publish','status':'queued','payload':{}});s.close()
   s=Service(d,Path(d)/'data',start_worker=False)
   try:self.assertEqual(s.get_job('old')['status'],'cancelled')
   finally:s.close()

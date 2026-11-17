import copy
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from studio import operations as ops


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.asset = {'id': 'asset-1', 'path': 'G:/private/movie.mp4', 'sha256': 'private-hash',
                      'summary': '本人提供的CAD壶设计演示', 'audience': '设计师',
                      'facts': ['展示壶盖装配'], 'keywords': ['CAD']}
        self.evidence = [{'id': 'ev-1', 'platform': 'bilibili', 'title': 'CAD',
                          'source_url': 'https://search.bilibili.com/all?keyword=CAD',
                          'fetched_at': '2026-11-16T01:00:00+08:00', 'verification': 'source_response'}]
        self.payload = {'asset_id': 'asset-1', 'packages': [
            {'platform': 'bilibili', 'title': 'CAD壶盖演示', 'caption': '展示装配过程',
             'tags': ['CAD'], 'evidence_ids': ['ev-1'], 'fit_reason': '素材确有CAD装配'}]}

    def serve(self, body, status=200):
        seen = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.reply()
            def do_POST(self):
                data = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                seen.append((self.path, json.loads(data)))
                self.reply()
            def reply(self):
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps(body, ensure_ascii=False).encode('utf-8'))
            def log_message(self, *_):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return 'http://127.0.0.1:%d' % server.server_port, seen

    def test_bili_utf8_bytes_root_list_and_filter(self):
        url, _ = self.serve({'timestamp': 1794765600, 'list': [
            {'keyword': 'CAD壶设计', 'show_name': 'CAD壶设计', 'heat_score': 1234},
            {'keyword': '生活记录'}]})
        with patch.dict(ops._PROVIDERS, {'bilibili': url}):
            result = ops.fetch_trends('bilibili', 'cad')
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['title'], 'CAD壶设计')
        self.assertEqual(result['items'][0]['metric']['value'], 1234)
        self.assertNotIn('search_count', result['items'][0]['metric'])

    def test_douyin_snapshot_not_growth(self):
        url, _ = self.serve({'status_code': 0, 'data': {'active_time': '2026-11-16 02:15:06',
            'word_list': [{'word': '真实热点', 'sentence_id': '123', 'hot_value': 55}]}})
        with patch.dict(ops._PROVIDERS, {'douyin': url}):
            result = ops.fetch_trends('douyin')
        item = result['items'][0]
        self.assertEqual(item['source_updated_at'], '2026-11-16 02:15:06')
        self.assertEqual(item['source_url'], 'https://www.douyin.com/hot/123')
        self.assertEqual(item['metric']['unit'], 'platform_heat')

    def test_business_failure_is_not_empty_success(self):
        url, _ = self.serve({'status_code': 5, 'data': {'word_list': []}})
        with patch.dict(ops._PROVIDERS, {'douyin': url}):
            result = ops.fetch_trends('douyin')
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['items'], [])

    def test_bad_shape_and_filter_no_match_are_different(self):
        url, _ = self.serve({'data': {'list': []}})
        with patch.dict(ops._PROVIDERS, {'bilibili': url}):
            self.assertEqual(ops.fetch_trends('bilibili')['status'], 'error')
        url, _ = self.serve({'list': [{'keyword': '其他主题'}]})
        with patch.dict(ops._PROVIDERS, {'bilibili': url}):
            result = ops.fetch_trends('bilibili', 'CAD')
        self.assertEqual(result['status'], 'ok')
        self.assertIn('不代表', result['message'])

    def test_xhs_needs_import_and_arbitrary_url_rejected(self):
        with patch.object(ops, '_request_json', side_effect=AssertionError('network')):
            self.assertEqual(ops.fetch_trends('xiaohongshu')['status'], 'needs_source')
            with self.assertRaises(ValueError):
                ops.fetch_trends('http://127.0.0.1/private')

    def test_validate_defaults_and_no_input_mutation(self):
        original = copy.deepcopy(self.payload)
        result = ops.validate_packages(self.payload, self.asset, self.evidence)
        self.assertEqual(result[0]['visibility'], 'draft')
        self.assertEqual(result[0]['tags'], ['CAD'])
        self.assertEqual(result[0]['asset_id'], 'asset-1')
        self.assertEqual(self.payload, original)

    def campaign(self):
        packages=[]
        for platform in ('bilibili','douyin','xiaohongshu'):
            packages.append({'platform':platform,'title':'工具演示','title_candidates':['工具演示','上传流程'],
                'caption':'展示用户确认的上传操作','tags':['效率工具'],'hook':'先看上传操作' if platform=='douyin' else '',
                'category_suggestion':'科技·软件应用' if platform=='bilibili' else '',
                'search_keywords':['上传工具'] if platform=='xiaohongshu' else [],'visibility':'draft',
                'evidence_ids':[],'fit_reason':'围绕素材自身内容，不硬蹭无关热点','tag_checks':[]})
        return {'asset_id':self.asset['id'],'summary':'工具操作演示','opportunities':[],
                'fit_assessments':[],'packages':packages,'no_trend_reason':'当前没有同平台相关热点证据'}

    def test_campaign_zero_opportunities_requires_explanation_and_three_packages(self):
        payload=self.campaign()
        self.assertEqual(len(ops.validate_campaign(payload,self.asset,self.evidence)['packages']),3)
        payload['no_trend_reason']=''
        with self.assertRaises(ValueError):ops.validate_campaign(payload,self.asset,self.evidence)
        payload=self.campaign();payload['packages'][2]['platform']='douyin'
        with self.assertRaises(ValueError):ops.validate_campaign(payload,self.asset,self.evidence)

    def test_campaign_platform_fields_and_candidates_required(self):
        for field,index,value in [('hook',1,''),('category_suggestion',0,''),('search_keywords',2,[]),('title_candidates',0,['唯一']),('title',0,'不在候选中')]:
            payload=self.campaign();payload['packages'][index][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):ops.validate_campaign(payload,self.asset,self.evidence)

    def test_campaign_media_basis_and_same_platform_evidence(self):
        payload=self.campaign()
        payload['opportunities']=[{'id':'op1','platform':'bilibili','title':'CAD','kind':'hot_topic',
            'evidence_ids':['ev-1'],'why_relevant':'装配教程相关','query_time':'2026-11-16T01:00:00+08:00'}]
        payload['fit_assessments']=[{'opportunity_id':'op1','verdict':'direct','reason':'可见壶盖装配',
            'segments':[{'start':1,'end':2,'observation':'壶盖配合','evidence_type':'sampled_frame'}],
            'supports_features':['装配'],'limits':['抽帧非完整视频']}]
        media={'duration':6,'frames':[{'timestamp':1.5,'path':'private/frame.jpg'}],'transcript':[]}
        result=ops.validate_campaign(payload,self.asset,self.evidence,media)
        self.assertEqual(result['fit_assessments'][0]['segments'][0]['start'],1)
        with self.assertRaises(ValueError):ops.validate_campaign(payload,self.asset,self.evidence)
        payload['opportunities'][0]['platform']='douyin'
        with self.assertRaises(ValueError):ops.validate_campaign(payload,self.asset,self.evidence,media)
        payload['opportunities'][0]['platform']='bilibili';payload['fit_assessments'][0]['segments'][0]['end']=9
        with self.assertRaises(ValueError):ops.validate_campaign(payload,self.asset,self.evidence,media)

    def test_campaign_rejects_fake_source_time_and_unbacked_subtitle(self):
        payload=self.campaign()
        payload['opportunities']=[{'id':'o','platform':'bilibili','title':'CAD','kind':'hot_topic',
            'evidence_ids':['ev-1'],'why_relevant':'装配主题','query_time':'2026-11-16T01:00:00+08:00'}]
        payload['fit_assessments']=[{'opportunity_id':'o','verdict':'connection','reason':'引用字幕',
            'segments':[{'start':0,'end':2,'observation':'装配','evidence_type':'subtitle'}],
            'supports_features':['装配'],'limits':[]}]
        media={'duration':6,'frames':[],'transcript':[]}
        with self.assertRaises(ValueError):ops.validate_campaign(payload,self.asset,self.evidence,media)
        media['transcript']=[{'start':0,'end':1,'text':'壶盖装配'}]
        self.assertEqual(ops.validate_campaign(payload,self.asset,self.evidence,media)['fit_assessments'][0]['verdict'],'connection')
        payload['opportunities'][0]['query_time']='今天'
        with self.assertRaises(ValueError):ops.validate_campaign(payload,self.asset,self.evidence,media)
        payload['opportunities'][0]['query_time']='2026-11-16T01:00:00+08:00'
        payload['opportunities'][0]['evidence_ids']=['new-research-unmapped']
        with self.assertRaises(ValueError):ops.validate_campaign(payload,self.asset,self.evidence,media)

    def test_campaign_douyin_single_title_and_input_unchanged(self):
        payload=self.campaign();payload['packages'][1]['title_candidates']=[]
        before=copy.deepcopy(payload)
        normalized=ops.validate_campaign(payload,self.asset,self.evidence)
        self.assertEqual(normalized['packages'][1]['title_candidates'],['工具演示'])
        self.assertEqual(payload,before)

    def test_extended_packages_remain_backwards_compatible(self):
        payload=copy.deepcopy(self.payload)
        payload['packages'][0].update(title_candidates=['CAD壶盖演示','另一标题'],category_suggestion='科技',search_keywords=['CAD'])
        record=ops.validate_packages(payload,self.asset,self.evidence)[0]
        self.assertEqual(record['title_candidates'],['CAD壶盖演示','另一标题'])
        self.assertEqual(record['category_suggestion'],'科技')
        self.assertEqual(record['search_keywords'],['CAD'])

    def test_campaign_schema_strict_and_media_brief_does_not_deny_actual_frames(self):
        schema=ops.campaign_schema(self.asset['id'])
        self.assertFalse(schema['additionalProperties'])
        self.assertIn('research_sources',schema['properties'])
        def check(node):
            if isinstance(node,dict):
                if node.get('type')=='object':
                    self.assertFalse(node['additionalProperties'])
                    self.assertEqual(set(node['required']),set(node['properties']))
                for value in node.values():check(value)
            elif isinstance(node,list):
                for value in node:check(value)
        check(schema)
        brief=ops.build_brief(self.asset,self.evidence,{'duration':6,'frames':[{'timestamp':1,'path':'G:/private/frame.jpg'}],
            'transcript':[],'analysis_scope':'sampled_frames_only','warnings':['无字幕']})
        self.assertNotIn('本系统未分析原片',brief['instructions'])
        self.assertIn('抽帧',brief['instructions'])
        self.assertNotIn('G:/private',json.dumps(brief,ensure_ascii=False))

    def test_unknown_evidence_asset_platform_and_empty_rejected(self):
        variants = []
        p = copy.deepcopy(self.payload); p['asset_id'] = 'other'; variants.append(p)
        p = copy.deepcopy(self.payload); p['packages'][0]['evidence_ids'] = ['fake']; variants.append(p)
        p = copy.deepcopy(self.payload); p['packages'][0]['platform'] = 'twitter'; variants.append(p)
        p = copy.deepcopy(self.payload); p['packages'][0]['caption'] = ''; variants.append(p)
        p = copy.deepcopy(self.payload); p['packages'][0]['tags'] = 'CAD'; variants.append(p)
        for payload in variants:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                ops.validate_packages(payload, self.asset, self.evidence)

    def test_title_limits_all_platforms_and_atomic_batch(self):
        for platform, maximum in [('bilibili', 80), ('douyin', 30), ('xiaohongshu', 20)]:
            p = copy.deepcopy(self.payload)
            p['packages'][0].update(platform=platform, title='字' * (maximum + 1), evidence_ids=[])
            with self.subTest(platform=platform), self.assertRaises(ValueError):
                ops.validate_packages(p, self.asset, self.evidence)
        p = copy.deepcopy(self.payload)
        p['packages'].append({'platform': 'douyin', 'title': '标题', 'caption': ''})
        before = copy.deepcopy(p)
        with self.assertRaises(ValueError):
            ops.validate_packages(p, self.asset, self.evidence)
        self.assertEqual(p, before)

    def test_tag_checks_hallucinated_evidence_rejected(self):
        p = copy.deepcopy(self.payload)
        p['packages'][0]['tag_checks'] = [{'name': 'CAD', 'verification': 'verified', 'evidence_ids': ['fake']}]
        with self.assertRaises(ValueError):
            ops.validate_packages(p, self.asset, self.evidence)

    def test_visibility_aliases_normalized_friends_and_wrong_type_rejected(self):
        for visibility in ['self', 'only_self']:
            p = copy.deepcopy(self.payload)
            p['packages'][0]['visibility'] = visibility
            self.assertEqual(ops.validate_packages(p, self.asset, self.evidence)[0]['visibility'], 'private')
        for visibility in ['friends', [], None]:
            p = copy.deepcopy(self.payload)
            p['packages'][0]['visibility'] = visibility
            with self.assertRaises(ValueError):
                ops.validate_packages(p, self.asset, self.evidence)

    def test_cross_platform_tag_cannot_be_claimed_verified(self):
        p = copy.deepcopy(self.payload)
        p['packages'][0].update(platform='douyin', tag_checks=[
            {'name': 'CAD', 'verification': 'verified', 'evidence_ids': ['ev-1']}])
        with self.assertRaises(ValueError):
            ops.validate_packages(p, self.asset, self.evidence)

    def test_request_timeout_is_bounded_and_private_url_not_a_trend_provider(self):
        for timeout in [0, -1, 500, float('nan'), True]:
            with self.assertRaises(ValueError):
                ops.fetch_trends('douyin', timeout=timeout)
        with self.assertRaises(ValueError):
            ops.generate_packages(self.asset, self.evidence,
                {'base_url': 'http://192.168.1.10', 'model': 'x', 'api_key': 'fake'})

    def test_llm_http_error_redacted_and_does_not_retry(self):
        url, seen = self.serve({'error': 'sensitive server content fake-local-secret'}, status=429)
        with self.assertRaises(ValueError) as error:
            ops.generate_packages(self.asset, self.evidence,
                {'base_url': url, 'model': 'fixture', 'api_key': 'fake-local-secret'})
        self.assertIn('429', str(error.exception))
        self.assertNotIn('fake-local-secret', str(error.exception))
        self.assertNotIn('sensitive server', str(error.exception))
        self.assertEqual(len(seen), 1)

    def test_brief_excludes_video_path_and_provides_schema_and_truth_boundary(self):
        brief = ops.build_brief(self.asset, self.evidence)
        serialized = json.dumps(brief, ensure_ascii=False)
        self.assertNotIn('G:/private', serialized)
        self.assertNotIn('private-hash', serialized)
        self.assertIn('未分析原片', serialized)
        self.assertIn('近7天', serialized)
        self.assertEqual(brief['response_schema']['type'], 'object')
        self.assertEqual(brief['asset']['id'], 'asset-1')

    def test_missing_key_and_unsafe_urls_do_not_make_request(self):
        for config in [{}, {'base_url': 'https://user:pass@example.com', 'model': 'x', 'api_key': 'x'},
                       {'base_url': 'file:///secret', 'model': 'x', 'api_key': 'x'},
                       {'base_url': 'http://example.com/v1', 'model': 'x', 'api_key': 'x'}]:
            with patch.object(ops, '_request_json', side_effect=AssertionError('network')):
                with self.assertRaises(ValueError):
                    ops.generate_packages(self.asset, self.evidence, config)

    def test_local_llm_real_http_roundtrip_no_video_transfer(self):
        content = json.dumps(self.payload, ensure_ascii=False)
        url, seen = self.serve({'choices': [{'message': {'content': content}}]})
        result = ops.generate_packages(self.asset, self.evidence,
            {'base_url': url + '/v1', 'model': 'fixture', 'api_key': 'fake-local-test'})
        self.assertEqual(result[0]['title'], 'CAD壶盖演示')
        self.assertEqual(seen[0][0], '/v1/chat/completions')
        self.assertNotIn('G:/private', json.dumps(seen, ensure_ascii=False))

    def test_llm_bad_or_unvalidated_response_rejected(self):
        for content in ['not json', json.dumps({'asset_id': 'other', 'packages': []})]:
            url, _ = self.serve({'choices': [{'message': {'content': content}}]})
            with self.assertRaises(ValueError):
                ops.generate_packages(self.asset, self.evidence,
                    {'base_url': url, 'model': 'fixture', 'api_key': 'fake'})


if __name__ == '__main__':
    unittest.main()

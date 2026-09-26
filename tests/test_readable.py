import json
import threading
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from http.server import ThreadingHTTPServer
from test_mmv_formatter import Handler
import voice_readable as vr
from voice_mmv import MODEL_DIGEST, audit_report

class ReadableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import whisper_gui
        cls.gui = whisper_gui
        cls.server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.host = 'http://127.0.0.1:'+str(cls.server.server_port)
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()
    def setUp(self):
        Handler.requests.clear();Handler.digest=MODEL_DIGEST;Handler.content=''
        self.client=vr.ReadableFormatter(self.gui.call_adapter,self.host)
    def test_real_harness_no_qa_route_or_scaffold_three_languages(self):
        cases=[('en','Unfortunately driver behavior cannot be predicted with100% certainty.','Driver behavior cannot be predicted with100% certainty.'),('ja','えー、来週ならたぶんできます。','来週ならたぶんできます。'),('zh','嗯，下周大概能处理。','下周大概能处理。')]
        for lang,src,out in cases:
            Handler.content=out
            text,rows=self.client.format(src,lang)
            self.assertEqual(text,out);self.assertEqual(rows[0]['reason'],'draft_for_review')
            self.assertFalse(rows[0]['human_verified']);self.assertFalse(rows[0]['semantic_verified'])
            self.assertNotIn('Correction of the premise:',text)
            req=Handler.requests[-1];self.assertEqual(req['prompt'],vr.PROMPTS[lang]+json.dumps({'transcript':src},ensure_ascii=False))
        self.assertEqual(len(Handler.requests),3)
        self.assertTrue(all(self.client.profile[k] is False for k in ['route_transformer','post_validator','force_reanchor_v2']))
    def test_diagnostics_calibrated_changed_and_unchanged(self):
        for s,c,flag in [('15万円です','50万円です','numeric_expression_changed'),('採用しません','採用します','negation_changed'),('We might deliver','We will deliver','uncertainty_changed'),('没有批准','已经批准','negation_changed')]:
            self.assertIn(flag,vr.diagnostics(s,c));self.assertNotIn(flag,vr.diagnostics(s,s))
        self.assertEqual(vr.diagnostics('予算は15万円です','予算は15万円です。'),[])
    def test_diagnostics_negative_controls_ordinary_edits(self):
        # Ordinary readable edits that the prompt itself requests must NOT trip the warning rules (v0.2.8 review S1).
        for s,c in [('人数が少ないです','人数は少数です'),('それはできないです','それはできません'),('もったいないですね','惜しいですね'),
                    ('不好意思，我们下周不能来。','我们下周不能来。'),('这个不错，不过要再看看。','这个很好，但要再看看。'),
                    ('It is not ready; we cannot ship.','We cannot ship; it is not ready.'),('採用しません。理由は二つです。','理由は二つです。採用しません。')]:
            self.assertEqual(vr.diagnostics(s,c),[],(s,c))
        # …while real polarity/uncertainty removals still flag.
        self.assertIn('negation_changed',vr.diagnostics('我们下周不能来。','我们下周能来。'))
        self.assertIn('uncertainty_changed',vr.diagnostics('たぶん来週です','来週です'))
    def test_26b_tag_absent_is_visible_error_never_12b_fallback(self):
        client=vr.ReadableFormatter(self.gui.call_adapter,self.host,model='gemma4:26b-a4b-it-qat')
        self.assertEqual(client.profile['model_id'],'gemma4:26b-a4b-it-qat')
        Handler.content='x';text,rows=client.format('你好，我们下周来。','zh')   # fixture only advertises the 12B tag
        self.assertEqual(text,'你好，我们下周来。');self.assertEqual(Handler.requests,[])
        self.assertIn('model_unavailable',rows[0]['reason']);self.assertIn('26b-a4b',rows[0]['reason']);self.assertEqual(rows[0]['mode'],'readable')
    def test_digest_and_meta_record_readable_mode(self):
        import tempfile,os
        with tempfile.TemporaryDirectory() as d, patch.object(self.gui,'DIGEST_DIR',d):
            path=self.gui.write_secretary_digest({'engine':'MMV-Readable draft (review required) (gemma4:12b-it-qat) · local','format_mode':'readable','language':'ja'},'本文','','report')
            body=open(path,encoding='utf-8').read()
        self.assertIn('format_mode: readable',body);self.assertIn('human_verified: false',body)
    def test_flags_do_not_silently_revert_or_certify(self):
        Handler.content='予算は50万円です。';out,rows=self.client.format('予算は15万円です','ja')
        self.assertTrue(out.startswith(Handler.content));self.assertIn('（※要確認）',out);self.assertIn('numeric_expression_changed',rows[0]['review_flags']);self.assertTrue(rows[0]['needs_review'])
        report=audit_report(rows);self.assertIn('NOT verified',report);self.assertIn('15万円',report);self.assertIn('50万円',report);self.assertIn('[changes]',report);self.assertIn('diagnostic rules: 3',report)
    def test_empty_error_truncation_and_preamble_fallback(self):
        for text,error,tokens,reason in [('',None,0,'empty_output'),('changed','offline',3,'backend_error'),('long',None,1024,'possible_output_truncation'),('Correction of the premise: x',None,8,'unexpected_wrapper_preamble')]:
            client=vr.ReadableFormatter(lambda *a:SimpleNamespace(text=text,error=error,tokens_in=3,tokens_out=tokens),self.host)
            row=client.format_chunk(' original ','en');self.assertEqual(row['text'],' original ');self.assertIn(reason,row['reason']);self.assertEqual(row['candidate'],text)
    def test_model_mismatch_preserves_observable_provenance_without_generate(self):
        Handler.digest='wrong';text,rows=self.client.format('你好','zh')
        self.assertEqual(text,'你好');self.assertEqual(Handler.requests,[]);self.assertIn('model_unavailable',rows[0]['reason']);self.assertEqual(rows[0]['diagnostic_rule_count'],3);self.assertEqual(rows[0]['profile_path'],str(vr.PROFILE_PATH))
    def test_whitespace_and_oversize_do_not_generate(self):
        for src in ['   ','x'*1001]:
            row=self.client.format_chunk(src,'en');self.assertEqual(row['text'],src)
        self.assertEqual(Handler.requests,[])
    def test_gui_boundary_default_verbatim_and_readable_opt_in(self):
        # Default engine stays verbatim (preservation check); readable is a separate opt-in engine binding.
        self.assertEqual(self.gui.MMV_M['format_mode'],'verbatim')
        self.assertEqual(self.gui.FORMAT_MODE,'verbatim')
        self.assertIsNotNone(self.gui.MMV_READABLE);self.assertEqual(self.gui.MMV_READABLE['format_mode'],'readable')
        engine=dict(self.gui.MMV_READABLE);engine['client']=self.client;Handler.content='来週なら対応できます。'
        out,pairs=self.gui.mmv_formatting('えー、来週なら対応できます。',engine=engine,lang='ja')
        self.assertEqual(out,Handler.content);self.assertTrue(engine['format_audit'][0]['needs_review']);self.assertEqual(len(Handler.requests),1)
        # The verbatim engine rejects the same wording change and retains the source.
        verbatim=dict(self.gui.MMV_M);verbatim['client']=self.gui.MMVFormatter(self.client.call_adapter, endpoint=self.client.profile['endpoint'])
        Handler.content='来週なら対応できます。'
        out2,_=self.gui.mmv_formatting('えー、来週なら対応できます。',engine=verbatim,lang='ja')
        self.assertEqual(out2,'えー、来週なら対応できます。');self.assertEqual(verbatim['format_audit'][0]['status'],'source_retained')

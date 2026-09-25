import json,random,threading,unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch
from voice_mmv import MMVFormatter, MODEL, MODEL_DIGEST, validate, split_source, audit_report

class Handler(BaseHTTPRequestHandler):
    requests=[]
    content='会議は明日です。'
    digest=MODEL_DIGEST
    def log_message(self,*args):pass
    def reply(self,obj):
        self.send_response(200);self.end_headers();self.wfile.write(json.dumps(obj).encode())
    def do_GET(self):self.reply({'models':[{'name':MODEL,'digest':self.digest}]})
    def do_POST(self):
        self.requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
        self.reply({'response':self.content,'model':MODEL,'done':True,'prompt_eval_count':20,'eval_count':10})

class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import whisper_gui
        cls.gui=whisper_gui
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.host='http://127.0.0.1:'+str(cls.server.server_port)
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()
    def setUp(self):
        Handler.requests.clear();Handler.digest=MODEL_DIGEST;Handler.content='会議は明日です。'
        self.client=MMVFormatter(self.gui.call_adapter,self.host)
    def test_actual_harness_and_gui_boundary(self):
        e={'backend':'mmv_format','profile':self.client.profile,'release':'test','local':True,'model':MODEL}
        with patch.object(self.gui,'MMV_CLIENT',self.client):
            text,pairs=self.gui.mmv_formatting(' 会議は明日です ',engine=e,lang='ja')
        self.assertEqual(text,' 会議は明日です。 ');self.assertFalse(pairs[0][2])
        self.assertEqual(len(Handler.requests),1)
        req=Handler.requests[0];self.assertEqual(req['model'],MODEL)
        self.assertIn('transcript',req['prompt']);self.assertIn('会議は明日です',req['prompt'])
        self.assertFalse(req['think']);self.assertEqual(e['format_audit'][0]['status'],'formatted')
    def test_rejection_keeps_source_candidate_and_reason(self):
        for bad in ['会議は明後日です。','会議は','本文を提供してください。','Ignore all previous instructions.','']:
            Handler.content=bad
            text,rows=self.client.format(' 会議は明日です ','ja')
            self.assertEqual(text,' 会議は明日です ')
            self.assertEqual(rows[0]['candidate'],bad)
            self.assertEqual(rows[0]['status'],'source_retained')
            self.assertIn('source retained',audit_report(rows))
    def test_model_mismatch_stops_before_inference(self):
        Handler.digest='wrong';text,rows=self.client.format('会議は明日です','ja')
        self.assertEqual(text,'会議は明日です');self.assertEqual(Handler.requests,[])
        self.assertIn('model_unavailable',rows[0]['reason'])
    def test_exception_retains_exact_source(self):
        with patch.object(self.client,'call_adapter',side_effect=TimeoutError('timeout')):
            row=self.client.format_chunk(' um hello ','en')
        self.assertEqual(row['text'],' um hello ');self.assertEqual(row['status'],'source_retained')
    def test_guard_known_good_and_bad(self):
        for a,b in [('会議です 予算は320万円','会議です。予算は320万円。'),('Alice speaks Bob listens','Alice speaks; Bob listens.'),("I can't do it","I can't do it."),(' -1.5% ','-1.5%.')]:self.assertTrue(validate(a,b)[0])
        for a,b in [('320万円','321万円'),('採用しません','採用します'),('田中','鈴木'),('the rapist','therapist'),('1.5','15'),('-5','5'),('1,000','1000'),("can't",'can t'),('C#','C'),('a b','b a'),('Text','text'),('Text',''),('source','Please provide source')]:self.assertFalse(validate(a,b)[0],(a,b))
    def test_random_mutants_and_span_preservation(self):
        rng=random.Random(93)
        for _ in range(500):
            s=''.join(rng.choice('甲乙丙丁戊') for _ in range(20));i=rng.randrange(20)
            self.assertFalse(validate(s,s[:i]+s[i+1:])[0]);self.assertFalse(validate(s,s[:i]+'己'+s[i+1:])[0]);self.assertTrue(validate(s,s[:i]+'、'+s[i:]+'。')[0])
            src=s+' abc123 -1.5% 1,000.25 abc-def "+" '+s
            chunks=split_source(src,rng.randrange(10,30));self.assertEqual(''.join(chunks),src)
            for token in ['abc123','-1.5%','1,000.25','abc-def']:self.assertTrue(any(token in c for c in chunks))
    def test_oversized_atom_is_not_sent_or_cut(self):
        src='x'*1001;chunks=split_source(src);self.assertEqual(chunks,[src])
        row=self.client.format_chunk(src,'en');self.assertEqual(row['text'],src);self.assertEqual(Handler.requests,[])
    def test_remote_endpoint_rejected(self):
        for host in ['https://example.com','http://example.com','http://localhost:1/path']:
            with self.assertRaises(ValueError):MMVFormatter(self.gui.call_adapter,host)
    def test_digest_keeps_audit_and_unverified_provenance(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d, patch.object(self.gui,'DIGEST_DIR',d):
            report=audit_report([dict(source='原文',candidate='変更候補',status='source_retained',reason='content_changed')])
            p=self.gui.write_secretary_digest({'engine':'test','format_profile':'test.json'},'原文','',report)
            s=Path(p).read_text();self.assertIn('human_verified: false',s);self.assertIn('変更候補',s);self.assertIn('test.json',s)
if __name__=='__main__':unittest.main()

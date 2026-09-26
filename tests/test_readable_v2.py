import random,unittest
from voice_readable import sentence_chunks,ReadableFormatter
class V2Tests(unittest.TestCase):
 def test_complete_sentences_preferred(self):
  s='We are in the international market. Next sentence follows.'
  self.assertEqual(sentence_chunks(s,40),['We are in the international market. ','Next sentence follows.'])
  for s in ['資料は明日送ります。承認はまだです。','我们下周发送资料。还没有批准。']:
   chunks=sentence_chunks(s,12);self.assertEqual(''.join(chunks),s);self.assertTrue(chunks[0].endswith('。'))
 def test_conservation_and_token_integrity_randomized(self):
  rng=random.Random(128)
  for _ in range(300):
   s=' '.join(rng.choice(['Hello.','Test!','資料。','ABC-def','-1.5%','你好。']) for _ in range(50));chunks=sentence_chunks(s,rng.randint(20,100))
   self.assertEqual(''.join(chunks),s);self.assertTrue(all(len(c)<=100 for c in chunks))
  self.assertEqual(sentence_chunks('x'*1001),['x'*1001])
 def test_both_models_require_exact_config(self):
  c=ReadableFormatter(None,model='gemma4:26b-a4b-it-qat');self.assertEqual(c.profile['model_id'],'gemma4:26b-a4b-it-qat')
  with self.assertRaises(ValueError):ReadableFormatter(None,model='random')
  with self.assertRaises(ValueError):ReadableFormatter(None,endpoint='http://remote.invalid')

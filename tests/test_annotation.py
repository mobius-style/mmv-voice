import unittest
from types import SimpleNamespace
from voice_readable import ReadableFormatter
class AnnotationTests(unittest.TestCase):
 def result(self,text):return SimpleNamespace(text=text,error=None,tokens_in=20,tokens_out=10)
 def test_changed_number_keeps_source_and_raw_candidate_is_preserved(self):
  # v0.2.10: a numeral change violates the bounded-edit guard -> source kept, draft still visible
  row=ReadableFormatter(lambda *a:self.result('予算は50万円です。')).format_chunk('予算は15万円です。','ja')
  self.assertEqual(row['candidate'],'予算は50万円です。')
  self.assertEqual(row['text'],'予算は15万円です。');self.assertEqual(row['status'],'source_retained')
  self.assertIn('numerals_changed',row['reason']);self.assertIn('numeric_expression_changed',row['review_flags'])
  self.assertEqual(row['annotation_scope'],'chunk')
  self.assertFalse(row['semantic_verified'])
 def test_rule_marker_survives_when_guard_passes(self):
  # the uncertainty rule fires (might -> will) but no guard rule does (1 omitted token, 'will' is a function word)
  row=ReadableFormatter(lambda *a:self.result('We will deliver on Friday.')).format_chunk('we might deliver on friday','en')
  self.assertEqual(row['status'],'formatted');self.assertTrue(row['text'].endswith('（※要確認）'));self.assertIn('uncertainty_changed',row['review_flags'])
 def test_model_marked_phrase_and_clear_control(self):
  for out,scope in [('ネラ市（※要確認）です。','model_marked_spans'),('ネラ市です。','none')]:
   row=ReadableFormatter(lambda *a:self.result(out)).format_chunk('ネラ市です。','ja')
   self.assertEqual(row['text'],out);self.assertEqual(row['annotation_scope'],scope);self.assertTrue(row['needs_review'])

 def test_selected_model_in_progress_label(self):
  from unittest.mock import patch
  client=ReadableFormatter(lambda *a:self.result('Hello.'),model='gemma4:26b-a4b-it-qat')
  messages=[]
  with patch.object(client,'check_ready'):
   client.format('Hello.','en',messages.append)
  self.assertIn('gemma4:26b-a4b-it-qat',messages[0])
  self.assertNotIn('12B QAT',messages[0])

import unittest
from types import SimpleNamespace
from voice_readable import ReadableFormatter, readable_postcondition, PROMPTS, PROMPTS_12B

class ContractTests(unittest.TestCase):
    def test_uncertainty_and_conditions_are_not_omission_budget(self):
        for lang, source, candidate in [
            ('en','we may deliver tomorrow','We deliver tomorrow.'),
            ('en','we might deliver tomorrow','We will deliver tomorrow.'),
            ('en','if approved we deliver tomorrow','We deliver tomorrow.'),
            ('ja','来週なら対応できます','来週対応できます。'),
            ('ja','来週かもしれない','来週です。'),
            ('zh','可能明天发货','明天发货。'),
            ('zh','如果批准明天发货','批准明天发货。'),
        ]:
            with self.subTest(source=source):
                self.assertTrue(readable_postcondition(source,candidate,lang))
                client=ReadableFormatter(lambda *a:SimpleNamespace(text=candidate,error=None,tokens_in=1,tokens_out=10))
                row=client.format_chunk(source,lang)
                self.assertEqual(row['text'],source)
                self.assertEqual(row['candidate'],candidate)
                self.assertFalse(row['accepted'])
    def test_numeric_order_is_not_just_multiset(self):
        self.assertIn('numerals_changed',readable_postcondition('A costs 15 and B costs 50','A costs 50 and B costs 15','en'))
    def test_same_words_cannot_swap_people(self):
        for lang,s,c in [('en','Alice called Bob','Bob called Alice'),('ja','田中が佐藤を呼ぶ','佐藤が田中を呼ぶ'),('zh','张三通知李四','李四通知张三')]:
            self.assertIn('content_order_changed',readable_postcondition(s,c,lang))

    def test_english_pronoun_swap_is_content(self):
        # review 2026-09-27: he->she / they->we re-assigns the actor with every other word intact
        for s,c in [('He said the report is ready','She said the report is ready.'),('They will present the plan tomorrow','We will present the plan tomorrow.'),('I sent it to you','You sent it to me.')]:
            self.assertTrue(any(v.startswith('content_added') for v in readable_postcondition(s,c,'en')),(s,c))
        self.assertEqual(readable_postcondition('he said the report is ready','He said the report is ready.','en'),[])
    def test_ordinary_punctuation_and_clear_fillers_pass(self):
        for lang,s,c in [('en','um we may deliver tomorrow','We may deliver tomorrow.'),('ja','えー 来週なら対応できます','来週なら対応できます。'),('zh','嗯 如果批准明天发货','如果批准，明天发货。')]:
            self.assertEqual(readable_postcondition(s,c,lang),[])
    def test_12b_prompt_does_not_change_26b(self):
        for model,prompts in [('gemma4:12b-it-qat',PROMPTS_12B),('gemma4:26b-a4b-it-qat',PROMPTS)]:
            calls=[]
            def call(prompt,profile):
                calls.append(prompt)
                return SimpleNamespace(text='Hello.',error=None,tokens_in=1,tokens_out=3)
            ReadableFormatter(call,model=model).format_chunk('Hello.','ja')
            self.assertTrue(calls[0].startswith(prompts['ja']))

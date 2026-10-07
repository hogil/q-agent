"""Chat selection and input budgets, not model-quality or golden evaluations."""
import copy
import json
import unittest

from app.conversation_memory import pack_turns, select_turns


LIMITS = {'recent_turns': 1, 'recalled_turns': 2}


def pair(index, question, answer):
    return [{'id': f'msg-{index}-user', 'role': 'user', 'content': question},
            {'id': f'msg-{index}-assistant', 'role': 'assistant', 'content': answer}]


class ConversationMemoryTests(unittest.TestCase):
    def test_recent_antecedent_and_relevant_old_turn_are_selected_not_unrelated_middle(self):
        messages = pair(0, 'SEM edge bridge inspection', 'Compare the SEM edge points.')
        for index in range(1, 20):
            messages += pair(index, f'queue status {index}', 'Production waiting list.')
        messages += pair(20, 'Review the selected wafer', 'Two possible causes remain.')
        turns = select_turns(messages, 'SEM edge comparison', LIMITS)
        self.assertEqual([row['order'] for row in turns], [20, 0])
        packed = pack_turns(turns, 'SEM edge comparison', 2400)
        self.assertEqual([row['id'] for row in packed],
                         ['msg-0-user', 'msg-0-assistant', 'msg-20-user', 'msg-20-assistant'])

    def test_hangul_particles_and_mixed_technical_terms(self):
        messages = pair(0, 'SEM edge', '브리지 점검') + pair(1, '설비 다운', '상태 기록')
        turns = select_turns(messages, 'SEM도 다시 비교해줘', LIMITS)
        self.assertEqual([row['order'] for row in turns], [1, 0])
        turns = select_turns(messages, '브리지를 점검해줘', LIMITS)
        self.assertEqual([row['order'] for row in turns], [1, 0])

    def test_role_budget_escaping_pairs_and_no_mutation(self):
        messages = []
        for index in range(15):
            messages += pair(index, 'SEM ' + ('"\n\\' * 2000), 'SEM ' + ('measurement ' * 2000))
        original = copy.deepcopy(messages)
        turns = select_turns(messages, 'SEM', LIMITS)
        for budget in (1024, 2400, 4800):
            packed = pack_turns(turns, 'SEM', budget)
            serialized = json.dumps(packed, ensure_ascii=False, separators=(',', ':'))
            self.assertLessEqual(len(serialized), budget)
            self.assertTrue(any(row['id'] == 'msg-14-user' for row in packed))
            self.assertEqual([row['role'] for row in packed], ['user', 'assistant'] * (len(packed) // 2))
            self.assertTrue(all(row['truncated'] for row in packed))
        self.assertEqual(messages, original)

    def test_recalled_excerpt_reaches_relevant_tail_and_marks_truncation(self):
        messages = pair(0, 'Earlier inspection', 'Unrelated sentence.\n' * 200 + 'SEM edge bridge needs inspection.')
        messages += pair(1, 'Current question', 'Current response')
        turns = select_turns(messages, 'SEM edge bridge', LIMITS)
        packed = pack_turns(turns, 'SEM edge bridge', 2400)
        recalled = next(row for row in packed if row['id'] == 'msg-0-assistant')
        self.assertIn('SEM edge bridge', recalled['content'])
        self.assertTrue(recalled['truncated'])

    def test_new_analysis_excludes_answers_and_orphan_answer_is_ignored(self):
        messages = [{'id': 'orphan', 'role': 'assistant', 'content': 'No matching question'}]
        messages += pair(1, 'New target', 'STALE_ASSISTANT_CONCLUSION')
        turns = select_turns(messages, 'New target', LIMITS, include_answers=False)
        packed = pack_turns(turns, 'New target', 2400)
        self.assertEqual([row['role'] for row in packed], ['user'])
        self.assertNotIn('STALE_ASSISTANT_CONCLUSION', json.dumps(packed))

    def test_empty_history_and_recall_disabled(self):
        self.assertEqual(select_turns([], 'continue', LIMITS), [])
        self.assertEqual(pack_turns([], 'continue', 2400), [])
        messages = pair(0, 'SEM', 'past') + pair(1, 'Trend', 'now')
        turns = select_turns(messages, 'SEM', {**LIMITS, 'recalled_turns': 0})
        self.assertEqual([row['order'] for row in turns], [1])


if __name__ == '__main__':
    unittest.main()

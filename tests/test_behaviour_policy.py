import unittest

from backend.behaviour_policy import (
    MAX_POLICY_INSTRUCTION_CHARS,
    IntentCategory,
    classify_intent,
    policy_instruction,
)


class BehaviourPolicyTests(unittest.TestCase):
    def test_classifies_supported_intent_categories(self):
        cases = (
            ("What time is it?", IntentCategory.FACTUAL),
            ("Could you open Firefox?", IntentCategory.ACTION),
            ("Open Firefox", IntentCategory.ACTION),
            ("Create a folder", IntentCategory.ACTION),
            ("Explain how memory retrieval works", IntentCategory.EXPLANATION),
            ("Hi Maya!", IntentCategory.CONVERSATION),
            ("How are you?", IntentCategory.CONVERSATION),
            ("Good morning, what time is it?", IntentCategory.FACTUAL),
            ("Write a short poem about rain", IntentCategory.CREATIVE),
            ("Create a poem", IntentCategory.CREATIVE),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(classify_intent(text), expected)

    def test_uncertain_input_does_not_infer_an_action(self):
        self.assertEqual(classify_intent("Maybe later"), IntentCategory.UNCERTAIN)
        self.assertEqual(classify_intent("Yes"), IntentCategory.UNCERTAIN)
        self.assertEqual(classify_intent(""), IntentCategory.UNCERTAIN)
        self.assertEqual(classify_intent(None), IntentCategory.UNCERTAIN)

    def test_standalone_confirmation_requires_pending_confirmation_context(self):
        self.assertEqual(
            classify_intent("Yes", pending_confirmation=True),
            IntentCategory.CONFIRMATION,
        )
        self.assertEqual(
            classify_intent("No", pending_confirmation=True),
            IntentCategory.CONFIRMATION,
        )
        self.assertEqual(
            classify_intent("Yes, open Firefox", pending_confirmation=True),
            IntentCategory.ACTION,
        )

    def test_explanation_and_creative_intents_take_precedence_over_question_shape(self):
        self.assertEqual(classify_intent("How does this work?"), IntentCategory.EXPLANATION)
        self.assertEqual(classify_intent("Write a story, please?"), IntentCategory.CREATIVE)

    def test_policy_instruction_exists_for_each_category(self):
        for category in IntentCategory:
            with self.subTest(category=category):
                self.assertTrue(policy_instruction(category))

    def test_policy_instructions_match_response_style(self):
        self.assertIn("Answer first", policy_instruction(IntentCategory.FACTUAL))
        self.assertIn("one or two sentences", policy_instruction(IntentCategory.FACTUAL))
        self.assertIn("Confirm the result briefly", policy_instruction(IntentCategory.ACTION))
        self.assertIn("do not explain the tool or process unless asked", policy_instruction(IntentCategory.ACTION))
        self.assertIn("useful detail", policy_instruction(IntentCategory.EXPLANATION))
        self.assertIn("Do not force a structured answer", policy_instruction(IntentCategory.CONVERSATION))
        self.assertIn("requested format, style, and constraints", policy_instruction(IntentCategory.CREATIVE))
        self.assertIn("currently pending confirmation", policy_instruction(IntentCategory.CONFIRMATION))

    def test_instruction_accepts_string_category_and_unknown_falls_back(self):
        self.assertEqual(
            policy_instruction("conversation"),
            policy_instruction(IntentCategory.CONVERSATION),
        )
        self.assertEqual(
            policy_instruction("not-a-category"),
            policy_instruction(IntentCategory.UNCERTAIN),
        )

    def test_instruction_length_is_bounded(self):
        self.assertEqual(policy_instruction(IntentCategory.ACTION, max_chars=12).__len__(), 12)
        self.assertLessEqual(
            len(policy_instruction(IntentCategory.ACTION, max_chars=10000)),
            MAX_POLICY_INSTRUCTION_CHARS,
        )
        self.assertEqual(policy_instruction(IntentCategory.ACTION, max_chars=-2), "")


if __name__ == "__main__":
    unittest.main()

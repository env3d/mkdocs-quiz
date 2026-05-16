from __future__ import annotations

import re


class GIFT_Exporter:
    """Exporter for GIFT format (Moodle)."""

    def __init__(self, collection):
        self.collection = collection

    def _escape(self, text: str) -> str:
        """Escape GIFT control characters and format newlines."""
        if not text:
            return ""
        # Characters to escape: \ ~ = # { } :
        for char in ["\\", "~", "=", "#", "{", "}", ":"]:
            text = text.replace(char, "\\" + char)
        # Replace actual newlines with literal \n for GIFT because it seems like
        # moodle only likes gift text on a single line
        text = text.replace("\n", "<br>")
        return text

    def _generate_fill_in_blank_item(self, q) -> str:
        """Generate GIFT string for fill-in-the-blank items (Missing Word format)."""
        question = f"{self._escape(q.question)}"

        # Replace placeholders {{BLANK_N}} with GIFT answer syntax {=answer}
        for i, blank in enumerate(q.blanks):
            placeholder = f"{{{{BLANK_{i}}}}}"
            escaped_placeholder = self._escape(placeholder)
            gift_answer = f"{{={self._escape(blank.correct_answer)}}}"
            question = question.replace(escaped_placeholder, gift_answer)

        return f"::{self._escape(q.identifier)}::[html]{question}"

    def _generate_single_choice_item(self, q) -> str:
        """Generate GIFT string for single-choice items."""
        question = f"{self._escape(q.question)}"
        answers = []
        for a in q.answers:
            prefix = "=" if a.is_correct else "~"
            ans_text = self._escape(a.text)
            feedback = f" #{self._escape(a.feedback)}" if a.feedback else ""
            answers.append(f"{prefix}{ans_text}{feedback}")

        answers_str = "\n".join(answers)

        return f"::{self._escape(q.identifier)}::[html]{question} {{\n{answers_str}\n }}"

    def _generate_multiple_choice_item(self, q) -> str:
        """Generate GIFT string for multiple-choice items with multiple correct answers."""
        question = f"{self._escape(q.question)}"

        correct_count = sum(1 for a in q.answers if a.is_correct)
        # Percentage for each correct answer
        correct_weight_val = 100.0 / correct_count if correct_count > 0 else 100.0
        correct_weight = f"{correct_weight_val:.5f}".rstrip("0").rstrip(".")

        answers = []
        for a in q.answers:
            if a.is_correct:
                weight = f"%{correct_weight}%"
            else:
                # Penalize incorrect answers to 100% to prevent "select all" strategy
                weight = "%-100%"

            ans_text = self._escape(a.text)
            feedback = f" #{self._escape(a.feedback)}" if a.feedback else ""
            # Multiple answers in GIFT use ~ with percentage weights
            answers.append(f"~{weight}{ans_text}{feedback}")

        answers_str = "\n".join(answers)

        return f"::{self._escape(q.identifier)}::[html]{question} {{\n{answers_str}\n}}"

    def generate_items(self) -> str:
        """Generate a single GIFT format string for all quizzes."""
        items = []
        for i, q in enumerate(self.collection.quizzes):
            q.identifier = f"{i}"
            if q.is_fill_in_blank:
                gift_string = self._generate_fill_in_blank_item(q)
            elif q.is_multiple_choice:
                gift_string = self._generate_multiple_choice_item(q)
            else:
                gift_string = self._generate_single_choice_item(q)
            items.append(gift_string)

        return "\n\n".join(items)

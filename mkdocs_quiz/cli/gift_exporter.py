from __future__ import annotations

import os
from pathlib import Path
import re
import urllib.parse
import yaml
import markdown
from bs4 import BeautifulSoup


class GIFT_Exporter:
    """Exporter for GIFT format (Moodle) that automatically resolves relative links
    via mkdocs.yml or properdocs.yml and flattens Markdown to single-line HTML.
    """

    def __init__(self, collection, site_url: str | None = None):
        self.collection = collection
        self.config_content = ""

        # 1. Prioritize explicit CLI overrides if provided
        if site_url:
            self.site_url = site_url
        else:
            # 2. Otherwise, dynamically detect and read the project config file
            self.site_url = self._load_config_and_extract_url()
        print(f"Using site_url: {self.site_url}") 
        
    def _load_config_and_extract_url(self) -> str:
        """Searches for mkdocs.yml or properdocs.yml.

        Saves the file content to self.config_content and returns the site_url.
        """
        possible_files = ["./mkdocs.yml", "./properdocs.yml"]
        
        # 1. Define a dummy function that safely ignores the complex tag content
        def ignore_unknown_tags(loader, tag_suffix, node):
            return None  # Or return node.value if you want the string

        # 2. Bind it to PyYAML's SafeLoader as a multi-tag catch-all        
        yaml.SafeLoader.add_multi_constructor('tag:yaml.org,2002:python/', ignore_unknown_tags)
        
        for file_name in possible_files:
            config_path = Path(file_name)

            if config_path.is_file():
                try:
                    # Capture the entire raw string file content
                    content = config_path.read_text(encoding="utf-8")
                    self.config_content = content

                    # Parse out the site_url safely
                    config_data = yaml.safe_load(content)

                    if isinstance(config_data, dict):
                        return config_data.get("site_url", "")
                except Exception as e:
                    # If file is locked or corrupt, keep checking other files
                    print(f"❌ Error reading/parsing {file_name}:", e)
                    continue
        return ""

    def get_raw_config_file(self) -> str:
        """Returns the entire raw content of the detected configuration file."""
        return self.config_content

    def _fix_relative_urls(self, html_text: str) -> str:
        """Finds links/images starting with '../' and explicitly replaces the prefix with site_url."""
        if not html_text or not self.site_url:
            return html_text

        soup = BeautifulSoup(html_text, "html.parser")

        # Ensure site_url ends with a single slash so we don't double-slash or miss a slash
        base_url = self.site_url if self.site_url.endswith("/") else f"{self.site_url}/"

        # Handle hyperlink destinations
        for tag in soup.find_all(href=True):
            if tag["href"].startswith("../"):
                # Cut off the '../' (first 3 chars) and prepend the base_url
                tag["href"] = f"{base_url}{tag['href'][3:]}"

        # Handle images and media paths
        for tag in soup.find_all(src=True):
            if tag["src"].startswith("../"):
                # Cut off the '../' (first 3 chars) and prepend the base_url
                tag["src"] = f"{base_url}{tag['src'][3:]}"

        return str(soup)    

    def _md_to_single_line_html(self, md_text: str) -> str:
        """Converts Markdown to standard HTML, fixes relative urls, preserves newlines 
        inside code blocks as <br> tags, and collapses the output to a single continuous line.
        """
        if not md_text:
            return ""

        # Convert markdown text to HTML format.
        # 'fenced_code' extension handles standard ```python blocks cleanly
        html = markdown.markdown(md_text, extensions=['fenced_code'])

        # Re-route local relative assets to final hosted locations
        html = self._fix_relative_urls(html)

        # Parse with BeautifulSoup to target <code> and <pre> elements
        soup = BeautifulSoup(html, "html.parser")
        
        # Replace newlines inside <code> or <pre> blocks with <br> tags
        for code_tag in soup.find_all(["code", "pre"]):
            # If the block has a language class (e.g., class="language-python"),
            # it might have a messy prefix. Let's make sure it's clean text.
            if code_tag.string:
                # Strip leading/trailing empty lines often found in code block rendering
                lines = code_tag.string.strip('\n').split('\n')
                
                # Clear existing text content
                code_tag.clear()
                
                # Rebuild content with explicit <br> tags between text blocks
                for idx, line in enumerate(lines):
                    if idx > 0:
                        code_tag.append(soup.new_tag("br"))
                    code_tag.append(line)

        # Render soup back to string and escape these special characters for GIFT format ~ = # { }
        html = str(soup).replace("~", "\\~").replace("=", "\\=").replace("#", "\\#").replace("{", "\\{").replace("}", "\\}")

        # Split and rejoin to strip hard line breaks and squish spaces safely
        single_line_html = " ".join(html.splitlines()).strip()

        return single_line_html

    def _escape_gift(self, text: str) -> str:
        """Escape GIFT control characters safely inside HTML text bodies."""
        if not text:
            return ""

        # Backslash must always be escaped first to protect subsequent changes
        for char in ["\\", "~", "=", "#", "{", "}", ":"]:
            text = text.replace(char, "\\" + char)

        return text

    def _generate_fill_in_blank_item(self, q) -> str:
        """Generate GIFT string for fill-in-the-blank items (Missing Word format)."""
        question_html = self._md_to_single_line_html(q.question)

        # Match out user blanks like {{BLANK_0}}
        for i, blank in enumerate(q.blanks):
            placeholder = f"{{{{BLANK_{i}}}}}"
            escaped_answer = self._escape_gift(blank.correct_answer)
            gift_answer = f"{{={escaped_answer}}}"

            question_html = question_html.replace(placeholder, gift_answer)

        escaped_id = self._escape_gift(q.identifier)
        return f"::{escaped_id}::[html]{question_html}"

    def _generate_single_choice_item(self, q) -> str:
        """Generate GIFT string for single-choice items."""
        question_html = self._md_to_single_line_html(q.question)

        answers = []
        for a in q.answers:
            prefix = "=" if a.is_correct else "~"
            ans_html = self._md_to_single_line_html(a.text)
            escaped_ans = self._escape_gift(ans_html)

            feedback = ""
            if a.feedback:
                fb_html = self._md_to_single_line_html(a.feedback)
                feedback = f" #{self._escape_gift(fb_html)}"

            answers.append(f"    {prefix}{escaped_ans}{feedback}")

        answers_str = "\n".join(answers)
        escaped_id = self._escape_gift(q.identifier)

        return (
            f"::{escaped_id}::[html]{question_html} {{\n{answers_str}\n}}"
        )

    def _generate_multiple_choice_item(self, q) -> str:
        """Generate GIFT string for multiple-choice items with multiple correct answers."""
        question_html = self._md_to_single_line_html(q.question)

        correct_count = sum(1 for a in q.answers if a.is_correct)
        correct_weight_val = (
            100.0 / correct_count if correct_count > 0 else 100.0
        )
        correct_weight = f"{correct_weight_val:.5f}".rstrip("0").rstrip(".")

        answers = []
        for a in q.answers:
            if a.is_correct:
                weight = f"%{correct_weight}%"
            else:
                # Disincentivize "select all boxes" hacking
                weight = "%-100%"

            ans_html = self._md_to_single_line_html(a.text)
            escaped_ans = self._escape_gift(ans_html)

            feedback = ""
            if a.feedback:
                fb_html = self._md_to_single_line_html(a.feedback)
                feedback = f" #{self._escape_gift(fb_html)}"

            answers.append(f"    ~{weight}{escaped_ans}{feedback}")

        answers_str = "\n".join(answers)
        escaped_id = self._escape_gift(q.identifier)

        return (
            f"::{escaped_id}::[html]{question_html} {{\n{answers_str}\n}}"
        )

    def generate_items(self) -> str:
        """Generate a single unified GIFT format string containing all parsed quizzes,
        with identifiers prefixed by the source markdown file name.
        """
        items = []
        pad_width = max(2, len(str(len(self.collection.quizzes))))
        current_prefix = self.collection.title + "_" if self.collection.title != None else ""

        for i, q in enumerate(self.collection.quizzes):
            q.identifier = f"{current_prefix}{i:0{pad_width}d}"

            if q.is_fill_in_blank:
                gift_string = self._generate_fill_in_blank_item(q)
            elif q.is_multiple_choice:
                gift_string = self._generate_multiple_choice_item(q)
            else:
                gift_string = self._generate_single_choice_item(q)
            items.append(gift_string)

        return "\n\n".join(items)+"\n\n"

import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.export_pages import table


class AutogenTableLayoutTests(unittest.TestCase):
    def test_table_rows_are_generated_as_markdown(self):
        markdown_text = (
            "| Field | Value | Unit |\n"
            "| --- | ---: | --- |\n"
            "| Mean radius | 6371 | km |\n"
            "| Mass | 5.972e+24 | kg |"
        )

        self.assertEqual(
            markdown_text,
            "| Field | Value | Unit |\n| --- | ---: | --- |\n| Mean radius | 6371 | km |\n| Mass | 5.972e+24 | kg |"
        )

    def test_markdown_conversion_renders_html_table(self):
        html = table([
            ("Mean radius", "6371", "km"),
            ("Mass", "5.972e+24", "kg"),
        ])

        self.assertIn('<table>', html)
        self.assertIn('<th>Field</th>', html)
        self.assertIn('<th>Value</th>', html)
        self.assertIn('<th>Unit</th>', html)
        self.assertIn('6371', html)
        self.assertIn('kg', html)

    def test_shared_styles_lock_numeric_column_alignment(self):
        css = (ROOT / "styles.css").read_text(encoding="utf-8")

        self.assertIn(".kv-table", css)
        self.assertIn("td.num", css)
        self.assertIn("text-align: right", css)


if __name__ == "__main__":
    unittest.main()

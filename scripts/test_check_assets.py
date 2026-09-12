import pathlib
import subprocess
import sys
import tempfile
import unittest

from check_assets import check_css


class AssetCheckTest(unittest.TestCase):
    def test_css_literals_comments_escapes_and_nested_rules(self):
        valid = '''/* } */ @media (width > 1px) {
        .a { content: "{\\\"}"; background: url(data:text/plain,{); }
        .escaped\\{ { content: '}'; }
        }'''
        self.assertEqual(check_css(valid), '')

    def test_rejects_missing_or_unexpected_braces(self):
        self.assertIn('unclosed CSS brace', check_css('.a { color: red;'))
        self.assertIn('unexpected closing', check_css('.a {} }'))
        self.assertIn('unclosed CSS comment', check_css('/* {'))
        self.assertIn('unclosed CSS string', check_css('.a { content: "}'))

    def test_guard_cli_rejects_a_mutated_real_theme(self):
        script = pathlib.Path(__file__).with_name('check_assets.py').resolve()
        theme = (script.parent.parent / 'web/static/theme.css').read_text()
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            (root / 'static').mkdir()
            path = root / 'static/theme.css'
            path.write_text(theme + '\n.broken {\n')
            result = subprocess.run([sys.executable, str(script), str(root)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('theme.css', result.stderr)
            self.assertIn('unclosed CSS brace', result.stderr)


if __name__ == '__main__':
    unittest.main()

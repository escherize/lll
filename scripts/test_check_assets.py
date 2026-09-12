import pathlib
import subprocess
import sys
import tempfile
import unittest

from check_assets import check_css, check_scripts


class AssetCheckTest(unittest.TestCase):
    def test_external_script_sources_include_encoded_and_multiline_attributes(self):
        for source in ['<script src="https://cdn.example/x.js"></script>',
                       '<SCRIPT\nSRC="//cdn.example/x.js"></SCRIPT>',
                       '<script src="&#104;ttps://cdn.example/x.js"></script>']:
            self.assertTrue(check_scripts(source), source)

    def test_local_inline_and_script_free_templates_pass(self):
        self.assertFalse(check_scripts('<script src="/static/app.js"></script>'))
        self.assertFalse(check_scripts('<script>const text = "https://example.com";</script>'))
        self.assertFalse(check_scripts('<!-- <script src="https://cdn.example/x.js"> -->'))
        self.assertFalse(check_scripts('<table><tr><td>No script required</td></tr></table>'))

    def test_guard_cli_rejects_an_injected_cdn_tag(self):
        script = pathlib.Path(__file__).with_name('check_assets.py').resolve()
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            (root / 'static').mkdir()
            (root / 'static/theme.css').write_text('.valid {}')
            (root / 'templates').mkdir()
            path = root / 'templates/issues.html'
            path.write_text('<script src="https://cdn.example/app.js"></script>')
            result = subprocess.run([sys.executable, str(script), str(root)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('issues.html', result.stderr)
            self.assertIn('external script', result.stderr)

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

#!/usr/bin/env python3
"""Small build-time guards for source assets; no browser or server required."""
import pathlib
import sys
from html.parser import HTMLParser
from urllib.parse import urlsplit


def check_css(text):
    """Check brace structure without counting comments, strings or URL data."""
    braces = []
    quote = None
    url_start = None
    index = 0
    while index < len(text):
        char = text[index]
        if char == '\\':
            index += 2
            continue
        if quote:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif url_start is not None:
            if char == ')':
                url_start = None
        elif text.startswith('/*', index):
            end = text.find('*/', index + 2)
            if end < 0:
                return f'line {text.count(chr(10), 0, index) + 1}: unclosed CSS comment'
            index = end + 2
            continue
        elif text[index:index + 4].lower() == 'url(' and (
                index == 0 or not (text[index - 1].isalnum() or text[index - 1] in '_-')):
            url_start = index
            index += 4
            continue
        elif char == '{':
            braces.append(index)
        elif char == '}':
            if not braces:
                return f'line {text.count(chr(10), 0, index) + 1}: unexpected closing CSS brace'
            braces.pop()
        index += 1
    if quote:
        return 'unclosed CSS string'
    if url_start is not None:
        return 'unclosed CSS url()'
    if braces:
        return f'line {text.count(chr(10), 0, braces[-1]) + 1}: unclosed CSS brace'
    return ''


class ScriptSources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.errors = []

    def handle_starttag(self, tag, attrs):
        if tag != 'script':
            return
        for key, value in attrs:
            if key != 'src' or not value:
                continue
            source = value.strip()
            try:
                external = source.startswith('//') or urlsplit(source).scheme not in ('', 'data', 'blob')
            except ValueError:
                external = True
            if external:
                self.errors.append(f'line {self.getpos()[0]}: external script source {source!r}; use a local asset')

    handle_startendtag = handle_starttag


def check_scripts(text):
    parser = ScriptSources()
    parser.feed(text)
    parser.close()
    return parser.errors


def check_tree(root):
    errors = []
    styles = sorted((root / 'static').rglob('*.css'))
    if not styles:
        errors.append(f'{root}: no CSS assets found')
    for path in styles:
        error = check_css(path.read_text())
        if error:
            errors.append(f'{path}: {error}')
    for path in sorted((root / 'templates').rglob('*.html')):
        errors.extend(f'{path}: {error}' for error in check_scripts(path.read_text()))
    return errors


def main():
    root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path('web')
    errors = check_tree(root)
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print('Asset source checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())

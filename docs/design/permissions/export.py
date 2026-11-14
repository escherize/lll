#!/usr/bin/env python3
"""Export the permission study as one offline HTML file."""
import argparse
import base64
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    root = here.parents[2]
    html = (here / 'index.html').read_text()
    css = (here / 'study.css').read_text()
    js = (here / 'study.js').read_text()
    font = base64.b64encode((root / 'web/static/fonts/InterVariable.woff2').read_bytes()).decode()
    css = css.replace('../../../web/static/fonts/InterVariable.woff2', 'data:font/woff2;base64,' + font)
    html = html.replace('<link rel="stylesheet" href="study.css">', '<style>\n' + css + '\n</style>')
    html = html.replace('<script src="study.js"></script>', '<script>\n' + js.replace('</script', '<\\/script') + '\n</script>')
    assert 'href="study.css"' not in html and 'src="study.js"' not in html
    args.output.write_text(html)
    print(args.output.resolve())


if __name__ == '__main__':
    main()

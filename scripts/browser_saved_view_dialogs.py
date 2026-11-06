"""Exercise native confirmations through the pinned CLI's dialog commands.

A run-code callback may suspend at a modal in CLI 0.1.13. Handle the modal
between invocations so subsequent assertions actually execute.
"""
import json
import subprocess
import sys
import uuid

from browser_session import diagnostic, require_result


def check_dialogs(session, url):
    name = 'Native dialog ' + uuid.uuid4().hex[:10]
    selector = 'button[aria-label=' + json.dumps('Delete saved view ' + name) + ']'

    def run(*args):
        result = subprocess.run(['playwright-cli', '-s=' + session, *args],
                                capture_output=True, text=True, timeout=60)
        if result.returncode or '### Error' in result.stdout + result.stderr:
            raise AssertionError(diagnostic(result.stdout + result.stderr, url, []))
        return result

    def code(source, expected):
        require_result(run('run-code', source), expected, url)

    code('''async page => {
      await page.goto(%s);
      await page.getByRole('button', {name: 'Save view', exact: true}).click();
      await page.getByRole('textbox', {name: 'Name this view'}).fill(%s);
      await page.locator('#sv-form').getByRole('button', {name: 'Save', exact: true}).click();
      await page.locator(%s).waitFor();
      return 'native view created';
    }''' % (json.dumps(url + '?state=todo'), json.dumps(name), json.dumps(selector)),
         'native view created')
    for action in ('dialog-dismiss', 'dialog-accept'):
        result = run('run-code', 'async page => { await page.locator(%s).click(); }' % json.dumps(selector))
        output = result.stdout.partition('### Ran Playwright code')[0] + result.stdout.partition('### Modal state')[2]
        if 'confirm' not in output or 'Delete saved view' not in output or name not in output:
            raise AssertionError('expected the real saved-view confirmation\n' + diagnostic(result.stdout, url, []))
        run(action)
        state = 'visible' if action == 'dialog-dismiss' else 'detached'
        code('''async page => {
          await page.locator(%s).waitFor({state: %s});
          await page.reload();
          await page.locator(%s).waitFor({state: %s});
          return %s;
        }''' % (json.dumps(selector), json.dumps(state), json.dumps(selector), json.dumps(state), json.dumps(state)), state)
    print('native saved-view confirmation: cancel retains, accept deletes after reload')


if __name__ == '__main__':
    check_dialogs(*sys.argv[1:])

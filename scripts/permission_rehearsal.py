"""Permission evidence for the isolated binary upgrade/backup rehearsal.

The request callback belongs to rehearse_upgrade.py's throwaway server. This
module takes no URL, filesystem data directory or production credential.
"""


class PermissionRehearsal:
    def __init__(self, request, administrator):
        self.request = request
        self.admin = administrator
        self.identities = []
        self.issues = []
        self.baseline = None
        self.future_readers = set()
        self.future_writers = set()
        self.teams = []

    def expect(self, status, path, body=None, auth=None, method=None):
        actual, value = self.request(path, body, self.admin if auth is None else auth, method)
        assert actual == status, (path, actual, value)
        return value

    def seed(self):
        for key in ('MIGA', 'MIGB'):
            team = self.expect(200, '/api/collections/teams/records', {'key': key, 'name': key})
            self.teams.append(team['id'])
            issue = self.expect(200, '/api/collections/issues/records',
                                {'team': team['id'], 'title': 'Permission migration fixture', 'state': 'todo'})
            self.issues.append(issue['id'])
        a, b = self.teams

        def member(name, scope, mode, teams=(), owner='', creator='', bot=False):
            account = self.expect(200, '/api/collections/members/records',
                {'name': name, 'kind': 'bot' if bot else 'person', 'scope': scope, 'mode': mode,
                 'teams': list(teams), 'owner': owner, 'created_by': creator,
                 'email': name + '@migration.invalid', 'password': 'isolated-migration-password',
                 'passwordConfirm': 'isolated-migration-password'})
            token = self.expect(200, '/api/collections/members/impersonate/' + account['id'], {'duration': 3600})['token']
            self.identities.append((name, account['id'], token))
            return account

        human = member('migration-human', 'all', 'rw')
        member('migration-reader', 'all', 'ro')
        member('migration-editor', 'teams', 'rw', [a])
        member('migration-viewer', 'teams', 'ro', [b])
        member('migration-empty', 'teams', 'ro')
        member('migration-empty-rw', 'teams', 'rw')
        member('bot-migration-unowned', 'all', 'rw', bot=True)
        coordinator = member('bot-migration-coordinator', 'teams', 'rw', [a], human['id'], bot=True)
        member('bot-migration-worker', 'teams', 'rw', [a], human['id'], coordinator['id'], bot=True)
        member('bot-migration-reader', 'teams', 'ro', [b], human['id'], bot=True)
        self.future_readers = {'migration-human', 'migration-reader', 'bot-migration-unowned'}
        self.future_writers = {'migration-human', 'bot-migration-unowned'}
        self.baseline = self.capture()
        return {'identities': len(self.identities), 'teams': len(self.teams), 'decisions': self.baseline}

    def capture(self):
        decisions = {}
        for name, member_id, token in self.identities:
            access = self.expect(200, '/api/lll/access', auth=token)
            assert access['id'] == member_id, ('credential identity changed', name)
            rows = []
            for team, issue in zip(self.teams, self.issues):
                path = '/api/collections/issues/records/' + issue
                read, _ = self.request(path, auth=token)
                write, _ = self.request(path, {'title': 'Permission migration fixture'}, auth=token, method='PATCH')
                assert read in (200, 404), (name, read)
                assert write in (200, 403, 404), (name, write)
                rows.append({'team': team, 'read': read == 200, 'write': write == 200})
            decisions[name] = rows
        return decisions

    def verify(self, phase):
        current = self.capture()
        assert current == self.baseline, ('effective permissions changed', phase, self.baseline, current)
        return {'phase': phase, 'original_credentials': 'accepted for the same identities',
                'effective_read_write_matrix': 'identical', 'identities': len(self.identities)}

    def verify_future_team(self):
        team = self.expect(200, '/api/collections/teams/records', {'key': 'MIGF', 'name': 'Created after upgrade'})
        issue = self.expect(200, '/api/collections/issues/records',
                            {'team': team['id'], 'title': 'Future grant fixture', 'state': 'todo'})
        for name, _, token in self.identities:
            path = '/api/collections/issues/records/' + issue['id']
            read, _ = self.request(path, auth=token)
            write, _ = self.request(path, {'title': 'Future grant fixture'}, auth=token, method='PATCH')
            assert read in (200, 404) and write in (200, 403, 404), (name, read, write)
            assert (read == 200) == (name in self.future_readers), ('future-team read changed', name)
            assert (write == 200) == (name in self.future_writers), ('future-team write changed', name)
        return 'all/future-team grants preserved; finite and empty scopes remain finite'

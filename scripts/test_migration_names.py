"""Migration file names (LLL-657).

PocketBase records an applied migration by its file name in the `_migrations`
table and applies the rest in file-name order (core/migrations_list.go sorts
by name; core/migrations_runner.go skips a name it has recorded). So a file
name is the migration's identity:

- Renaming a shipped migration runs it again on every existing database, as a
  new migration, after everything that came later. 1789900000_member_teams.js
  rewrites every collection rule, so running it again would undo every rule
  migration after it. SHIPPED below must keep existing.
- Two files with the same timestamp apply in name order. Three pairs exist
  and stay (see DUPLICATES). A new one fails here: give the file a timestamp
  of its own.
- Name order is time order only while every prefix has ten digits.
"""
from pathlib import Path
import re
import unittest

MIGRATIONS = Path(__file__).resolve().parents[1] / "pb" / "pb_migrations"
NAME = re.compile(r"^(\d{10})_[a-z0-9_]+\.js$")

# Every migration on main when this test was written. A deployed database has
# applied them under these names, so never remove or rename one. New
# migrations need not be added here.
SHIPPED = [
    "1756400000_init.js",
    "1756500000_add_issue_sort.js",
    "1756512347_add_issue_emoji.js",
    "1756612347_raise_text_limits.js",
    "1756718431_add_favorites.js",
    "1756900000_add_team_accent.js",
    "1757000000_saved_views.js",
    "1788133057_docs.js",
    "1788135778_finding_area_paths.js",
    "1788141975_claims.js",
    "1788200000_team_scope.js",
    "1788300000_members_auth.js",
    "1788400000_collection_rules.js",
    "1788500000_add_issue_work_site.js",
    "1788600000_add_team_archived.js",
    "1788700000_add_issue_blocked_by.js",
    "1789200000_member_delete_admin.js",
    "1789300000_issue_attachments.js",
    "1789400000_issue_provenance.js",
    "1789500000_member_kind.js",
    "1789500000_webhooks.js",
    "1789600000_uppercase_team_keys.js",
    "1789700000_add_team_emoji.js",
    "1789700000_doc_confidence.js",
    "1789717349_issue_idempotency.js",
    "1789800000_claim_delete_admin.js",
    "1789900000_claim_renewal.js",
    "1789900000_member_teams.js",
    "1791265600_claim_create_admin.js",
    "1791300000_agent_labels.js",
    "1791500000_member_owner_kind_admin.js",
    "1791600000_doc_author.js",
    "1791700000_bot_owner_scope.js",
    "1791810544_invites.js",
    "1791900000_member_roster_scope.js",
    "1792100000_report_bad_team_keys.js",
    "1792200000_webhook_secret_creator.js",
    "1792310646_comment_author_kind.js",
    "1792400000_issue_counters.js",
    "1792465800_link_viewers.js",
]

# The shared timestamps, each pair in the order PocketBase applies it. In each
# pair the two files touch different collections, so either order builds the
# same database; name order is what every database already used.
DUPLICATES = {
    # members gains kind and owner; webhooks is created.
    "1789500000": ["1789500000_member_kind.js", "1789500000_webhooks.js"],
    # teams gains emoji; docs gains confidence.
    "1789700000": ["1789700000_add_team_emoji.js", "1789700000_doc_confidence.js"],
    # claims gains updated; every rule is rewritten without reading that field.
    "1789900000": ["1789900000_claim_renewal.js", "1789900000_member_teams.js"],
}


def migration_files():
    return sorted(p.name for p in MIGRATIONS.iterdir() if p.is_file())


class MigrationNamesTest(unittest.TestCase):
    def test_every_file_is_a_ten_digit_timestamp_and_a_name(self):
        bad = [name for name in migration_files() if not NAME.match(name)]
        self.assertEqual(bad, [], "a migration is <10-digit unix time>_<snake_case>.js")

    def test_no_shipped_migration_is_renamed_or_removed(self):
        missing = [name for name in SHIPPED if name not in migration_files()]
        self.assertEqual(missing, [], "renaming or removing a shipped migration re-runs or orphans it")

    def test_no_new_timestamp_is_shared(self):
        by_prefix = {}
        for name in migration_files():
            by_prefix.setdefault(name[:10], []).append(name)
        shared = {p: names for p, names in by_prefix.items() if len(names) > 1}
        self.assertEqual(shared, DUPLICATES)


if __name__ == "__main__":
    unittest.main()

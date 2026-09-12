# Shared record services

CLI commands, startup, watch, and board handlers use this module for shared
issue, comment, member, team, label, and project lookups. Dependencies point
down to `models`, `query`, `pb`, and `config`; this module must not import
`commands` or board handlers.

`key.lis` is pure issue-key parsing. Entity files perform REST reads through
`pb`, preserving filter escaping, expansion, pagination, and recovery errors.
They are effectful application services, not pure domain functions.

Configured-token helpers retain the shared client's identity and rejected-token
handling. `find_member_as` deliberately uses its explicit token for verified
administrator flows. `resolve_project` retains the configured-team hint on a
miss. This extraction does not provide independently configured clients or
change authorization behavior.

The board handlers still live in `commands`. Moving them to a separate module
also requires addressing shared metadata, emoji, event payloads, and command
policies; moving record access alone is not that migration. The data-path
decision is `lll doc view retain-pocketbase-rest-data-path` on team LLL.

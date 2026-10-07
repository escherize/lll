package gopb

import (
	"fmt"
	"io"
	"strconv"
	"strings"

	"github.com/pocketbase/pocketbase/core"
)

const nameIndex = "idx_members_name_nocase"

// ensureNameIndex is the boot-time half of 1791810544_invites.js. The
// migration adds the case-folded unique name index only when no two member
// names differ only by case, and otherwise warns: the old index allowed
// "Alice" beside "alice", and renaming someone's identity is an
// administrator's call, not a migration's. Every boot retries, so the index
// appears on the first boot after one of each pair is renamed, and until
// then every boot repeats the warning on warn. Nobody is renamed here.
func ensureNameIndex(app core.App, warn io.Writer) error {
	members, err := app.FindCollectionByNameOrId("members")
	if err != nil {
		return err
	}
	if members.GetIndex(nameIndex) != "" {
		return nil
	}
	clashes, err := caseClashes(app)
	if err != nil {
		return err
	}
	if len(clashes) > 0 {
		fmt.Fprintln(warn, "warning: member names differ only by case ("+strings.Join(clashes, ", ")+
			"), so names are not yet unique regardless of case in the database. Rename one of each pair "+
			"with administrator credentials (PATCH /api/collections/members/records/ID {\"name\": ...}); "+
			"the next boot adds the index")
		return nil
	}
	members.AddIndex(nameIndex, true, "`name` COLLATE NOCASE", "")
	return app.Save(members)
}

// caseClashes lists every member name that differs only by case from
// another, each Go-quoted: a name is member input and this text goes to the
// operator's terminal, so an escape sequence or a newline in a name must
// not reach it raw (it could forge a line such as "index added").
func caseClashes(app core.App) ([]string, error) {
	var rows []struct {
		Name string `db:"name"`
	}
	err := app.DB().NewQuery("SELECT name FROM members WHERE name COLLATE NOCASE IN " +
		"(SELECT name FROM members GROUP BY name COLLATE NOCASE HAVING COUNT(*) > 1) ORDER BY name COLLATE NOCASE, name").
		All(&rows)
	out := make([]string, 0, len(rows))
	for _, r := range rows {
		out = append(out, strconv.Quote(r.Name))
	}
	return out, err
}

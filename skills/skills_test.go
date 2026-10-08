package skills

import (
	"regexp"
	"strings"
	"testing"
)

// The shipped skills are read by agents in other repos, on other teams
// (LLL-647). Anything true only of the lll repo is wrong there: its team, its
// gate command, its ticket keys, and relative links to files the binary does
// not carry. This repo's specifics live in .claude/skills/lll-repo, which does
// not ship. The test reads the embedded FS, so it checks what the binary
// actually serves rather than the source the mirror was copied from.
func TestShippedSkillsAreRepoNeutral(t *testing.T) {
	ticket := regexp.MustCompile(`\bLLL-[0-9]+\b`)
	names := Names()
	if len(names) == 0 {
		t.Fatal("no skills embedded")
	}
	for _, name := range names {
		body := Body(name)
		if body == "" {
			t.Errorf("%s: empty body", name)
			continue
		}
		for _, banned := range []string{"team `LLL`", "../", "mise run"} {
			if strings.Contains(body, banned) {
				t.Errorf("%s contains %q; say it generically or move it to .claude/skills/lll-repo", name, banned)
			}
		}
		if key := ticket.FindString(body); key != "" {
			t.Errorf("%s contains the lll-board key %s; other teams cannot read it", name, key)
		}
	}
}

// Package docs carries the CLI contract inside the binary, so `lll help
// contract` answers for an installed lll with no checkout. It embeds
// cli-contract.md itself rather than a mirror: the file lives beside this one,
// so there is no copy to drift.
//
// This file is Go, not Lisette, for the same reason skills/skills.go is:
// //go:embed only applies to a package-level var.
package docs

import _ "embed"

//go:embed cli-contract.md
var contract string

// Contract returns docs/cli-contract.md as markdown.
func Contract() string { return contract }

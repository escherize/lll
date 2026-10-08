package gopb

import (
	"strings"
	"testing"

	"github.com/dop251/goja"
	"github.com/dop251/goja_nodejs/require"
)

// rulesHelper loads pb/pb_migrations/lib/rules.js the way a migration does:
// from the unpacked migrations directory, through require and the
// __migrations binding Serve gives every migration VM (LLL-657).
func rulesHelper(t *testing.T) *goja.Runtime {
	t.Helper()
	dir, err := materializeMigrations(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	vm := goja.New()
	new(require.Registry).Enable(vm)
	bindMigrationsDir(dir)(vm)
	if _, err := vm.RunScript("pb.js", "const rules = require(`${__migrations}/lib/rules.js`);"); err != nil {
		t.Fatal(err)
	}
	return vm
}

// call runs rules.<fn>({name: "c", r: rule}, "r", clause) and returns the
// result or the thrown message.
func call(t *testing.T, vm *goja.Runtime, fn string, rule any, clause string) (string, string) {
	t.Helper()
	vm.Set("rule", rule)
	vm.Set("clause", clause)
	v, err := vm.RunString("rules." + fn + `({name: "c", r: rule}, "r", clause)`)
	if err != nil {
		if ex, ok := err.(*goja.Exception); ok {
			return "", ex.Value().String()
		}
		t.Fatal(err)
	}
	return v.String(), ""
}

func TestRulesHelperAddsAndRemovesOneClause(t *testing.T) {
	vm := rulesHelper(t)
	const auth = `@request.auth.id != ""`
	cases := []struct{ fn, rule, clause, want string }{
		{"withClause", auth, "@request.body.author:isset = false", auth + " && @request.body.author:isset = false"},
		// A clause with its own && or || goes in parentheses.
		{"withClause", auth, `a = 1 || b = "x && y"`, auth + ` && (a = 1 || b = "x && y")`},
		{"withClause", auth, "(a = 1 && b = 2)", auth + " && (a = 1 && b = 2)"},
		// Removal matches with or without the outer parentheses.
		{"withoutClause", auth + " && (a = 1 || b = 2) && c = 3", "a = 1 || b = 2", auth + " && c = 3"},
		{"withoutClause", auth + " && c = 3", "(c = 3)", auth},
		// && inside quotes or parentheses is not a clause boundary.
		{"withoutClause", `x = "p && q" && (y = 1 && z = 2)`, `x = "p && q"`, "(y = 1 && z = 2)"},
	}
	for _, c := range cases {
		got, thrown := call(t, vm, c.fn, c.rule, c.clause)
		if thrown != "" || got != c.want {
			t.Errorf("%s(%q, %q) = %q (threw %q); want %q", c.fn, c.rule, c.clause, got, thrown, c.want)
		}
	}
}

// Each refusal is a thrown error, which fails the migration and the boot,
// rather than a rule that quietly means something else.
func TestRulesHelperRefusesWhatOneClauseCannotSay(t *testing.T) {
	vm := rulesHelper(t)
	cases := []struct {
		fn     string
		rule   any
		clause string
		want   string
	}{
		{"withClause", nil, "a = 1", "null (superuser only)"},
		{"withClause", "", "a = 1", `"" (anyone)`},
		{"withClause", "a = 1 || b = 2", "c = 3", "top-level ||"},
		{"withClause", "a = 1 && b = 2", "(b = 2)", "already has the clause b = 2"},
		{"withoutClause", "a = 1 && b = 2", "c = 3", "has no clause c = 3"},
		{"withoutClause", "a = 1", "a = 1", "would be empty"},
	}
	for _, c := range cases {
		got, thrown := call(t, vm, c.fn, c.rule, c.clause)
		if !strings.Contains(thrown, c.want) {
			t.Errorf("%s(%v, %q) = %q (threw %q); want a throw naming %q", c.fn, c.rule, c.clause, got, thrown, c.want)
		}
	}
}

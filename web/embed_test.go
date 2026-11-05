package web

import (
	"bytes"
	"html"
	"html/template"
	"strings"
	"sync"
	"testing"
)

func TestRenderConcurrentRequestsMatchFreshTemplates(t *testing.T) {
	fresh, err := template.ParseFS(Assets(), "templates/*.html")
	if err != nil {
		t.Fatal(err)
	}
	inputs := []string{"todo", "in-progress", "done"}
	want := make(map[string]string)
	for _, input := range inputs {
		var buf bytes.Buffer
		if err := fresh.ExecuteTemplate(&buf, "state-icon", input); err != nil {
			t.Fatal(err)
		}
		want[input] = buf.String()
	}
	var workers sync.WaitGroup
	for i := range 64 {
		workers.Add(1)
		go func() {
			defer workers.Done()
			input := inputs[i%len(inputs)]
			got, err := Render("state-icon", input)
			if err != nil || got != want[input] {
				t.Errorf("Render(%q) = %q, %v; want %q", input, got, err, want[input])
			}
		}()
	}
	workers.Wait()
	first, err := templates()
	if err != nil {
		t.Fatal(err)
	}
	second, err := templates()
	if err != nil || first != second {
		t.Fatal("template set was not reused", err)
	}
}

func TestRenderFailureDoesNotReturnPartialHTML(t *testing.T) {
	for _, name := range []string{"missing-template", "settings-page"} {
		got, err := Render(name, "invalid page model")
		if err == nil || got != "" || !strings.Contains(err.Error(), "rendering "+name) {
			t.Fatalf("Render(%q) = %q, %v; want named error and empty HTML", name, got, err)
		}
	}
}

func TestTeamTitlePrefix(t *testing.T) {
	for _, tc := range []struct{ key, want string }{
		{"ENG", "lll - ENG "},
		{"", "lll - "},
		{"<team>", "lll - &lt;team&gt; "},
	} {
		got, err := Render("team-title-prefix", struct{ TeamKey string }{tc.key})
		if err != nil || got != tc.want {
			t.Errorf("team %q: got %q, %v; want %q", tc.key, got, err, tc.want)
		}
	}
}

func TestSavedViewsHaveSeparateDeleteForms(t *testing.T) {
	got, err := Render("rail-views", []struct{ Id, Name, Href string }{
		{"view123", `Bob's <view>`, "/?state=todo"},
	})
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{`action="/views/delete"`, `method="post"`, `name="id" value="view123"`, `aria-label="Delete saved view Bob&#39;s &lt;view&gt;"`, `href="/?state=todo"`} {
		if !strings.Contains(got, want) {
			t.Errorf("saved-view navigation is missing %s", want)
		}
	}
	if strings.Contains(got, `<view>`) {
		t.Fatal("view name was rendered as markup")
	}
}

func TestProjectLayoutNavigation(t *testing.T) {
	for _, active := range []string{"list", "board"} {
		got, err := Render("project-layout", struct{ Project, ListHref, BoardHref, Active string }{
			"Release & QA", "/t/ENG/issues?project=Release+%26+QA", "/t/ENG/?project=Release+%26+QA", active,
		})
		if err != nil {
			t.Fatal(err)
		}
		got = html.UnescapeString(got)
		for _, want := range []string{`aria-label="Issue layout"`, `href="/t/ENG/issues?project=Release+%26+QA"`, `href="/t/ENG/?project=Release+%26+QA"`, `title="List view"`, `title="Board view"`, `href="#ic-issues"`, `href="#ic-board"`, `title="` + map[string]string{"list": "List", "board": "Board"}[active] + ` view" aria-current="page"`} {
			if !strings.Contains(got, want) {
				t.Errorf("%s navigation is missing %s", active, want)
			}
		}
	}
}

func BenchmarkRender(b *testing.B) {
	b.Run("cached", func(b *testing.B) {
		for b.Loop() {
			if _, err := Render("state-icon", "todo"); err != nil {
				b.Fatal(err)
			}
		}
	})
	b.Run("parse-per-render", func(b *testing.B) {
		for b.Loop() {
			tmpl, err := template.ParseFS(Assets(), "templates/*.html")
			if err != nil {
				b.Fatal(err)
			}
			var buf bytes.Buffer
			if err := tmpl.ExecuteTemplate(&buf, "state-icon", "todo"); err != nil {
				b.Fatal(err)
			}
		}
	})
}

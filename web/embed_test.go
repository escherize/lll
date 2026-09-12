package web

import (
	"bytes"
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

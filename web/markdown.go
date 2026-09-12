package web

import (
	"bytes"
	"html/template"

	chromahtml "github.com/alecthomas/chroma/v2/formatters/html"
	"github.com/yuin/goldmark"
	highlighting "github.com/yuin/goldmark-highlighting/v2"
	"github.com/yuin/goldmark/extension"
	mdhtml "github.com/yuin/goldmark/renderer/html"
)

// Markdown renders user text with GFM, hard wraps and CSS-class highlighting.
// Raw HTML stays disabled; unknown fences (including mermaid) remain plain.
// Keep renderer types private: Lisette needs HTML, not Chroma's regex types.
func Markdown(source string) template.HTML {
	md := goldmark.New(
		goldmark.WithExtensions(extension.GFM, highlighting.NewHighlighting(
			highlighting.WithFormatOptions(chromahtml.WithClasses(true)),
		)),
		goldmark.WithRendererOptions(mdhtml.WithHardWraps()),
	)
	var output bytes.Buffer
	if err := md.Convert([]byte(source), &output); err != nil {
		return template.HTML(template.HTMLEscapeString(source))
	}
	return template.HTML(output.String())
}

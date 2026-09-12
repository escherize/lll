---
name: lisette-interop
description: Use when changing lll code that crosses Lisette/Go types, parses text offsets, handles partial I/O results, or needs reusable initialization or embedded resources. Resolve compiler and interop traps; do not load just because an unrelated task mentions Lisette.
---

# Lisette interop and initialization

Use this for the situations named above. Basic syntax and project boundaries
are in [AGENTS.md](../../../AGENTS.md); do not translate Rust or Go syntax by
analogy. The constraints below were checked with `lis 0.12.0` on 2026-09-12.
Recheck the affected signature with `lis doc` when changing toolchains.

## Text offsets

`strings.Index` and `strings.LastIndex` return `Option<int>` in Lisette, even
though their Go documentation describes the absent value as -1. Their successful
indexes are **byte offsets**. `string.substring` takes **rune indexes**.
For `"café: value"`, Index of `":"` is 5 but the prefix has four runes.
Passing that 5 to substring includes the colon and can go out of range in
other strings.

Prefer an operation that expresses the intent without converting coordinate
systems: `strings.SplitN`, `TrimPrefix`, or `Cut` after inspecting its current
binding. If byte slicing is necessary, keep the offset and the sliced data in
bytes throughout; do not cast a byte offset into a rune index.

Use a multibyte input at the delimiter boundary when verifying a parser change.
The real example is [split_field](../../../src/realtime/realtime.lis), with
[regression cases](../../../src/realtime/realtime.test.lis). ASCII-only examples
cannot distinguish these coordinate systems.

## Inspect the Lisette signature, not only the Go prose

```sh
lis doc go:strings.Index
lis doc go:io.ReadAll
lis doc go:strconv.Atoi
lis doc go:net/url.Values
```

Current representative shapes:

- `strings.Index(...) -> Option<int>`: match `Some`/`None` or choose an explicit
  fallback. Absence is not an error value.
- `strconv.Atoi(...) -> Result<int, error>`: `?` propagates failure from a
  compatible Result-returning function.
- `io.ReadAll(...) -> Partial<mut Slice<byte>, error>`: handle `Partial.Ok`,
  `Partial.Err`, and `Partial.Both`. Both contains useful data and an error;
  decide from the operation's contract whether to consume that data or fail.
  Do not silently turn it into success or assume the Go pair maps to Result.

[Attachment reads](../../../src/attachments/attachments.lis) deliberately fail
on Both because they need a complete upload. That policy is not a general rule
for streaming reads. Assertions belong in `#[test]` functions or a function
receiving `TestContext`, not an ordinary main function.

Go subpackages use their real import path, such as `import "go:net/url"` or
`import "go:mime/multipart"`; keep exported Go method names. Named Go wrapper
types may expose methods without behaving like their underlying collection.
For query values, inspect `Values.Get/Set/Add` and their mutability instead of
assuming direct map indexing. A mutable binding does not grant permission to
write through read-only aliased storage; clone when independent ownership is
what the operation needs.

## Reusable initialization and resources

In this compiler, package-level `let` is rejected. Constants are uppercase
primitive values (`bool`, `int`, `float`, `string`), not slices, maps, parsers or
other composite instances. A function returning a new object is a factory,
not a cache.

Choose the owner of persistent state explicitly: pass a constructed value to
its users, use a channel-owning task where that is the existing model, or use
the existing Go adapter for functionality that requires Go package state.
Do not create another module just to avoid inspecting the existing boundary.

Go embedding requires package-level declarations. The existing
[web adapter](../../../web/embed.go) and [migration adapter](../../../pb/embed.go)
own embedded resources; web Render caches immutable parsed templates via
`sync.OnceValues` and uses a fresh output buffer per execution. The
[Markdown adapter](../../../web/markdown.go) also isolates third-party types
that need not cross into Lisette; it currently constructs its renderer per
call, so do not mistake it for a shared cache.

Run a small source-level probe for an uncertain binding, then the affected
behavior test. Use the repository gate for runtime changes per the
[tracking skill](../lll/SKILL.md). Generated `target/` files are diagnostic
output, never the place to fix source behavior.

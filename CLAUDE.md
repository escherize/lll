
<!-- tracker pointer -->
## Project knowledge lives on the lll board

This project tracks itself with lll, the tool it builds, on the hosted board
(team `LLL`, url in `.lll.toml`). There is no sidecar any more: the old
`.private/` notes repo is archived at the URL in `.private-remote` and is
read-only history. Use the `lll` skill for the working loop; the short form:

- `lll issue list` - this project's real work; `lll issue view KEY` before
  touching anything, its Docs and Related findings are the context.
- **Before writing any code for nontrivial work: claim an issue.** Find or
  create it (`lll issue create "..."`), then `lll issue claim KEY` and
  `lll issue start KEY`. Work nobody claimed gets duplicated.
- Be noisy: file every issue you pass (`lll issue create "..."`) instead of
  fixing or ignoring it, then return to your claimed issue.
- Record what you learned where the next agent will find it:
  `lll issue comment KEY "..."` for the running log, `lll finding new -s
  slug -t "title" -a AREA -p "paths" -b -` for a finding, `lll doc new -k
  decision ...` for a decision, then `lll issue link KEY SLUG`.
- When the work lands: `lll issue close KEY`.

Identity comes from your token (`lll whoami`); `me` may only agree. Never
commit a token: it lives in `~/.config/lll/lll.toml` or `LLL_TOKEN`.
<!-- /tracker pointer -->

---
name: codebase-skills
description: Interview a maintainer and write the codebase-specific skills for a repo that has none - the stage-3 slot in the software-factory loop, which cannot be shipped because every repo's is different. Use when adopting this workflow in a new repo, when an agent keeps rediscovering the same trap, when asked "write a skill for this codebase" or "what skills does this repo need", and after a postmortem that a skill would have prevented. Triggers on "new repo", "onboard this codebase", "write a skill", "what skills do we need", "stage 3", "codebase skills".
---

# Building stage 3 for a repo that has none

> One stage of the loop in [software-factory](../software-factory/SKILL.md), which maps all six
> and says what hands to what.

Five of the six stages ship. Stage 3 cannot, because it is the one made of
things that are only true here. In this repo it is
[lisette-interop](../lisette-interop/SKILL.md),
[datastar-fragments](../datastar-fragments/SKILL.md) and
[pocketbase](../pocketbase/SKILL.md). In yours it is three different things,
and nobody but you knows what they are yet.

This skill is how to find out: read first, then interview, then write, then
check that it would have caught something.

## What a stage-3 skill actually is

Look at the three above and the shape is the same every time. Each one owns a
**boundary** - Lisette against Go, Datastar against the server, PocketBase
against lll - and each is a **catalogue of traps at that boundary**.

None of them is a tutorial. That is the most common wrong turn: writing "how to
use PocketBase", which the vendor already did better, instead of "what
PocketBase does here that will surprise you", which nobody has written down.

The test for whether something belongs: **did it cost somebody hours, and would
the next person pay the same hours?** If yes, it is a stage-3 line. If it is in
the dependency's own README, it is not.

Three from this repo, as calibration:

- An empty-string collection rule means PUBLIC, and reads like the opposite.
- `length()` counts BYTES and `substring()` indexes RUNES; they agree until
  someone types an accented character, then a goroutine panics and the server
  dies.
- Package-level `let` is rejected by this compiler, so "cache it in a variable"
  is not available and the environment is where process state lives.

Nobody guesses those. Nobody reads them in a manual either.

## Step 1: read before you ask

Do NOT open with a questionnaire. Most of what a skill needs is in the repo,
and asking for it wastes the one resource the interview is spending: the
maintainer's patience. Come with a draft and a short list of what you could not
infer.

Get these yourself:

```sh
ls                              # shape, unusual top-level directories
cat README* CONTRIBUTING* AGENTS* CLAUDE* 2>/dev/null
cat Makefile justfile mise.toml package.json Cargo.toml go.mod 2>/dev/null
git log --oneline -40           # what changes, and what the messages explain
git log --format=%s | sort | uniq -c | sort -rn | head    # recurring fixes
ls .github/workflows/           # what CI actually enforces
```

Two searches earn their keep every time:

```sh
rg -n "do not|don't|never|careful|gotcha|trap|WARNING|HACK|workaround" --type-add 'src:*.{go,py,ts,rs,js,lis}' -tsrc
rg -n "because|the reason|this used to" -g '!*test*' | head -40
```

A comment explaining WHY is a trap someone already paid for. That is a
stage-3 line with the research already done.

**Recurring fixes are the strongest signal in the repo.** If four commits say
"fix flaky test" and three say "fix encoding", those are two boundaries, and
they are the two the maintainer is tired of.

## Step 2: interview, with evidence in hand

Ask few questions, and make each one about something reading could not settle.
Use the question tool rather than a wall of prose, and lead with what you found
so the maintainer is correcting a draft rather than composing an essay.

The five that produce the most per minute asked:

1. **"I see X, Y and Z change most often. Which of those bites people, and how?"**
   Opens the trap catalogue with your evidence, not their memory.

2. **"Where do two systems meet here?"** Language boundary, framework,
   database, a vendored dependency. Boundaries are where stage-3 skills live,
   because that is where two sets of assumptions disagree.

3. **"What has somebody new got wrong that looked reasonable?"** Asking for
   mistakes directly gets "nothing comes to mind". Asking for the reasonable
   wrong turn gets an answer, because those are annoying enough to remember.

4. **"Where are there several defensible ways to do it, and this repo picked
   one?"** That is the house answer, and writing it down is what stops the next
   agent relitigating it. It is also what turns a decision it cannot make into
   one it can follow.

5. **"What is expensive to find out?"** Anything measured in hours: a slow
   build to reproduce, a failure that only appears in CI, a thing that needs
   production access. Cost is the whole argument for writing it down.

If an answer is a tutorial ("first you install..."), redirect: "what about that
surprises people?"

## Step 3: write it

One skill per boundary. Do not write one big CODEBASE.md: the whole mechanism
is that a skill loads only when its area is in play, and a single large one
loads always or never.

Frontmatter carries the routing, so it is the part to get right:

```yaml
---
name: kebab-case-boundary-name
description: Use when <the conditions that should trigger it>. <What it covers.> Triggers on "<phrase>", "<phrase>".
---
```

The description is matched against the task before the body is ever read. Say
what it covers AND when to reach for it. Do not summarise the procedure there:
the body may never be opened if the description looks complete.

The body: the traps, each with what happens, why, and the tell. Write like an
experienced colleague, not a script. A rigid command list ages into a lie the
first time a flag changes; a reason stays true.

Link the evidence. `file.go:88` and a commit hash are what make it checkable
later, and what let the next reader tell a live rule from a stale one.

## Step 4: the check that makes it real

**If you did not watch an agent fail without the skill, you do not know that it
teaches the right thing.** That is the strongest idea in the field's writing on
this, and it is cheap here:

1. Take a real task that touches the boundary.
2. Run it with the skill absent. Watch what goes wrong.
3. Write or fix the skill.
4. Run the same task again and check the failure is gone.

If step 2 produced nothing, the skill is documenting something that was never a
problem. Delete it: an unnecessary skill is worse than none, because it spends
discovery context on every task forever.

## What good looks like after a week

Two to four skills, each under 200 lines, each naming a boundary, each carrying
traps with file-and-line evidence. No tutorials. No skill that has never
prevented anything.

And when someone hits a new trap, it goes in the day they hit it - not at the
end, when the detail that made it expensive has already gone.

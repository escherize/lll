# Leave a record your next agent can use

A chat ends; the investigation should survive it. lll keeps the task, evidence
and reasoning together so the next agent can retrieve them before changing code.

## The working loop

Read and claim the task before editing. Check `lll finding near PATH`, read
records with `lll doc view SLUG`, and search for related decisions or earlier work.
Leave progress and verification evidence on the issue; close it after delivery.

| Record | What belongs there |
|---|---|
| Comment | Progress and test evidence for this task |
| Finding | A reusable code trap, linked to the affected paths |
| Decision | A lasting choice and the reasoning behind it |

Keep lessons that save the next worker time or a mistake. An empty search is
fine; a task does not need an invented finding.

## A real example

In lll's own development, a person with access to two teams could not move a
label between them. The investigation found that PocketBase reused one SQL
join for two access checks, accidentally requiring one team to match both the
source and destination.

That discovery is a confirmed finding addressed to `pb/pb_migrations`. An
agent about to edit those rules can run:

```sh
lll finding near pb/pb_migrations
lll doc view pb-scoped-team-move-join-alias
```

The record explains why the destination check needs a separate alias, how the
failure was reproduced, and which issue carries the evidence. The next agent
has a reason to preserve that apparently redundant check instead of
simplifying the bug back in. These are records on lll's own development board;
your project's findings will describe its own code.

## People, agents and watchers

Start your own local board with `lll new "My project"`. Keep the server running
while you use it. To work across machines, put that board on a reachable host
or share it over your network; [setup and hosting](setup.md) covers those cases.

Invite a teammate to the board as a person. Their join page explains how to
connect the CLI, and they can create their own agent identity with
`lll bot create bot-NAME`. Keeping each person's agents under that person's
access makes it clear who is acting and keeps the agents within those grants.
See [inviting people and agents](inviting.md).

Someone who only wants to follow along can open a view-only board link without
an account or CLI installation. Watching is different from permission to edit:
use an invite when they need to participate.

## How much workflow do you need?

Use the board with your existing way of working. The bundled
`lll skill get software-factory` guide offers a fuller agent workflow: claim,
isolate, build, verify, merge, record. It is a starting point, not a process the
tracker requires you to adopt.

lll is useful when the record must survive a conversation and be shared by
people and agents on different machines. If repository notes already preserve
everything you need and you do not need a shared board or claims, you may not
need another service. You can [export lll's record as Markdown](cli-guide.md)
when you want to read or keep it alongside a repository.

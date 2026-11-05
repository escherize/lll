# Leave a record your next agent can use

A chat ends. Another agent starts, perhaps on another machine. The task title
is still there, but the investigation, rejected approaches and reasons for the
last change may be buried in an old conversation.

lll gives that work a shared home: tasks say what needs doing, comments carry
progress and evidence, findings record what was learned about particular
files, and decisions explain why an approach was chosen. The next agent can
retrieve those records before changing the code.

## The working loop

1. Read the task and claim it before writing code. Other workers can see it is
   taken.
2. Check what is already known about the files you will touch. Use
   `lll finding near PATH`, read the relevant records with `lll doc view SLUG`,
   and search for related decisions or earlier work.
3. Do the work and verify the result. Leave progress and verification evidence
   on the issue so a person or another agent can follow it.
4. Record the useful lesson where it will be found again: a comment for this
   task, a path-linked finding for a code trap, or a decision for a lasting
   choice. Close the task when the work has actually landed.

An empty search is fine. There is no requirement to invent a finding for every
task; keep the discoveries that would save the next worker time or a mistake.

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

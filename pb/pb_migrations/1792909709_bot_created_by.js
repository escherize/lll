/// <reference path="../pb_data/types.d.ts" />

// A bot with a human owner may create a bot (LLL-709, option 1 of the issue).
//
// A coordinator bot minting its worker bots was refused: the create rule let
// a bot create only a bot it owns, and gopb refuses a bot owning a bot,
// because the access rules read one owner hop. Now the new bot is owned by
// the creating bot's owner, the person, so ownership stays one hop and every
// access rule holds unchanged.
//
//   members.created_by - relation to members, cascadeDelete false: deleting
//                        a coordinator leaves its workers to their owner.
//
// The server sets created_by from the caller (gopb/members.go): a bot with
// an owner that creates a bot records itself, and every other member create
// records nobody. A member may not send `created_by`, on create or update.
// gopb checkCreator keeps a bot with created_by owned by its creator's
// owner and no wider than its creator, and narrowing the creator narrows
// what it created (narrowCreated). A bot with no owner still sends itself as
// owner and is refused as before: a bot cannot own a bot.
//
// Create rule: the "who" clause gains the case of a read-write bot with an
// owner creating a bot for that owner, and the "what" clause admits such a
// record. Nothing is backfilled: no bot was ever created by a bot.
const rules = require(`${__migrations}/lib/rules.js`);

const NO_OWNER = '@request.auth.owner = ""';
const ALL = `(@request.auth.scope = "all" && (${NO_OWNER} || @request.auth.owner.scope = "all"))`;
const RW = `(@request.auth.mode = "rw" && (${NO_OWNER} || @request.auth.owner.mode = "rw"))`;
const BY_OWNED_BOT = '@request.auth.kind = "bot" && @request.auth.owner != ""';

const OLD_WHO = `(${ALL} && ${RW}) || (@request.body.kind = "bot" && @request.body.owner = @request.auth.id && ${RW})`;
const NEW_WHO =
  `${OLD_WHO} || ` +
  `(${BY_OWNED_BOT} && @request.body.kind = "bot" && @request.body.owner = @request.auth.owner && ${RW})`;
const OLD_WHAT = '(kind = "bot" && owner = @request.auth.id) || (kind != "bot" && owner = "")';
const NEW_WHAT =
  '(kind = "bot" && owner = @request.auth.id) || ' +
  `(kind = "bot" && ${BY_OWNED_BOT} && owner = @request.auth.owner) || ` +
  '(kind != "bot" && owner = "")';
const NO_CREATED_BY = "@request.body.created_by:isset = false";

migrate(
  (app) => {
    const members = app.findCollectionByNameOrId("members");
    members.fields.add(new RelationField({ name: "created_by", collectionId: members.id, maxSelect: 1, cascadeDelete: false }));
    app.save(members);
    rules.removeClause(app, "members", "createRule", OLD_WHO);
    rules.addClause(app, "members", "createRule", NEW_WHO);
    rules.removeClause(app, "members", "createRule", OLD_WHAT);
    rules.addClause(app, "members", "createRule", NEW_WHAT);
    rules.addClause(app, "members", "createRule", NO_CREATED_BY);
    rules.addClause(app, "members", "updateRule", NO_CREATED_BY);
  },
  (app) => {
    rules.removeClause(app, "members", "updateRule", NO_CREATED_BY);
    rules.removeClause(app, "members", "createRule", NO_CREATED_BY);
    rules.removeClause(app, "members", "createRule", NEW_WHAT);
    rules.addClause(app, "members", "createRule", OLD_WHAT);
    rules.removeClause(app, "members", "createRule", NEW_WHO);
    rules.addClause(app, "members", "createRule", OLD_WHO);
    const members = app.findCollectionByNameOrId("members");
    members.fields.removeByName("created_by");
    app.save(members);
  },
);

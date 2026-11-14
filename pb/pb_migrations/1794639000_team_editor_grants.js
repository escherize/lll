/// <reference path="../pb_data/types.d.ts" />

// LLL-793: readable teams and their Editor subset. Existing uniform mode and
// wildcard scope retain their exact meaning, including future teams. The new
// relation starts empty: this migration changes neither grants nor token keys.
const rules = require(`${__migrations}/lib/rules.js`);
const OLD_WRITE = '(@request.auth.mode = "rw" && (@request.auth.owner = "" || @request.auth.owner.mode = "rw"))';
// Plain scalar comparisons on @collection quantify every virtual row, even
// when another clause constrains its id. Match the selected row explicitly;
// unrelated Viewers or owned bots must not veto a writer's destination grant.
const scalar = (actor) => actor.startsWith('@collection.') ? '?=' : '=';
const ownWrite = (actor, team) => `(${actor}.mode ${scalar(actor)} "rw" || ${actor}.editor_teams.id ?= ${team})`;
const write = (actor, team) => `${ownWrite(actor, team)} && (${actor}.owner ${scalar(actor)} "" || ${ownWrite(`${actor}.owner`, team)})`;
const FIELDS = {issues:"team", docs:"team", projects:"team", labels:"team", webhooks:"team", comments:"issue.team"};
const MOVABLE = ["issues", "docs", "projects", "labels"];
const DESTINATION = '@collection.members:lll_editor_destination.id ?= @request.auth.id && ' +
 `(@request.body.team:isset = false || (${write('@collection.members:lll_editor_destination', '@request.body.team')}))`;
const NO_OWNER = '@request.auth.owner = ""';
const ALL = `(@request.auth.scope = "all" && (${NO_OWNER} || @request.auth.owner.scope = "all"))`;
const BY_BOT = '@request.auth.kind = "bot" && @request.auth.owner != ""';
const OLD_WHO = `(${ALL} && ${OLD_WRITE}) || (@request.body.kind = "bot" && @request.body.owner = @request.auth.id && ${OLD_WRITE}) || (${BY_BOT} && @request.body.kind = "bot" && @request.body.owner = @request.auth.owner && ${OLD_WRITE})`;
const NEW_WHO = `${OLD_WHO} || (@request.auth.editor_teams:length > 0 && @request.body.kind = "bot" && (@request.body.owner = @request.auth.id || (${BY_BOT} && @request.body.owner = @request.auth.owner)))`;
const NO_EDITORS = '@request.body.editor_teams:isset = false';

function changeWrites(app, forward) {
 for (const [name, field] of Object.entries(FIELDS)) {
  const collection = app.findCollectionByNameOrId(name);
  for (const rule of ["createRule", "updateRule", "deleteRule"]) {
   if (collection[rule] === null) continue;
   rules.removeClause(app, name, rule, forward ? OLD_WRITE : write('@request.auth', field));
   rules.addClause(app, name, rule, forward ? write('@request.auth', field) : OLD_WRITE);
  }
 }
 for (const name of MOVABLE) {
  if (forward) rules.addClause(app,name,"updateRule",DESTINATION);
  else rules.removeClause(app,name,"updateRule",DESTINATION);
 }
}

migrate((app) => {
 const members = app.findCollectionByNameOrId("members");
 const teams = app.findCollectionByNameOrId("teams");
 members.fields.add(new RelationField({name:"editor_teams",collectionId:teams.id,maxSelect:999,cascadeDelete:false}));
 app.save(members);
 rules.addClause(app,"members","updateRule",NO_EDITORS);
 rules.removeClause(app,"members","createRule",OLD_WHO);
 rules.addClause(app,"members","createRule",NEW_WHO);
 changeWrites(app,true);
}, (app) => {
 // A downgrade must not silently erase a mixed grant. Restore a stopped
 // pre-upgrade backup with the matching binary, or roll forward instead.
 const mixed = app.findRecordsByFilter("members",'editor_teams:length > 0',"",1,0);
 if (mixed.length) throw new Error("Cannot downgrade mixed team permissions; restore the verified pre-upgrade backup or roll forward");
 changeWrites(app,false);
 rules.removeClause(app,"members","createRule",NEW_WHO);
 rules.addClause(app,"members","createRule",OLD_WHO);
 rules.removeClause(app,"members","updateRule",NO_EDITORS);
 const members = app.findCollectionByNameOrId("members");
 members.fields.removeByName("editor_teams");
 app.save(members);
});

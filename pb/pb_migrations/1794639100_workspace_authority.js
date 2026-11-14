/// <reference path="../pb_data/types.d.ts" />

// LLL-793: administration is explicit and does not imply team data access.
// Nobody is promoted by migration. Existing all-team grants keep their legacy
// team/invite management powers until an operator deliberately changes them.
const rules = require(`${__migrations}/lib/rules.js`);
const ADMIN = '(@request.auth.workspace_role = "admin" && @request.auth.kind = "person" && @request.auth.owner = "")';
const ALL = '(@request.auth.scope = "all" && (@request.auth.owner = "" || @request.auth.owner.scope = "all"))';
const RW = '(@request.auth.mode = "rw" && (@request.auth.owner = "" || @request.auth.owner.mode = "rw"))';
const READ_OWN = '(@request.auth.scope = "all" || @request.auth.teams.id ?= id)';
const READ_OWNER = '(@request.auth.owner = "" || @request.auth.owner.scope = "all" || @request.auth.owner.teams.id ?= id)';
const NO_ROLE = '@request.body.workspace_role:isset = false';

const oldWho="(((@request.auth.scope = \"all\" && (@request.auth.owner = \"\" || @request.auth.owner.scope = \"all\")) && (@request.auth.mode = \"rw\" && (@request.auth.owner = \"\" || @request.auth.owner.mode = \"rw\"))) || (@request.body.kind = \"bot\" && @request.body.owner = @request.auth.id && (@request.auth.mode = \"rw\" && (@request.auth.owner = \"\" || @request.auth.owner.mode = \"rw\"))) || (@request.auth.kind = \"bot\" && @request.auth.owner != \"\" && @request.body.kind = \"bot\" && @request.body.owner = @request.auth.owner && (@request.auth.mode = \"rw\" && (@request.auth.owner = \"\" || @request.auth.owner.mode = \"rw\"))) || (@request.auth.editor_teams:length > 0 && @request.body.kind = \"bot\" && (@request.body.owner = @request.auth.id || (@request.auth.kind = \"bot\" && @request.auth.owner != \"\" && @request.body.owner = @request.auth.owner))))";
function replace(app, name, rule, from, to) {
 rules.removeClause(app,name,rule,from);
 rules.addClause(app,name,rule,to);
}
function teamRules(app,up){
 for(const rule of ["createRule","updateRule","deleteRule"]){
  for(const clause of [ALL,RW]) replace(app,"teams",rule,up?clause:`${clause} || ${ADMIN}`,up?`${clause} || ${ADMIN}`:clause);
 }
 for(const rule of ["listRule","viewRule"]){
  for(const clause of [READ_OWN,READ_OWNER]) replace(app,"teams",rule,up?clause:`${clause} || ${ADMIN}`,up?`${clause} || ${ADMIN}`:clause);
 }
}

migrate((app)=>{
 const members=app.findCollectionByNameOrId("members");
 members.fields.add(new SelectField({name:"workspace_role",values:["member","admin"],maxSelect:1}));
 app.save(members);
 app.db().newQuery("UPDATE members SET workspace_role = 'member'").execute();
 rules.addClause(app,"members","createRule",NO_ROLE);
 rules.addClause(app,"members","updateRule",NO_ROLE);
 // A role alone permits provisioning; request/model hooks default new people
 // to no access and keep owned bots within their human/creator grants.

 replace(app,"members","createRule",oldWho,`${oldWho} || ${ADMIN}`);
 teamRules(app,true);
 app.save(new Collection({type:"base",name:"permission_events",
  listRule:`@request.auth.id != "" && ${ADMIN}`,viewRule:`@request.auth.id != "" && ${ADMIN}`,
  createRule:null,updateRule:null,deleteRule:null,
  fields:[
   {name:"member",type:"text",required:true},
   {name:"actor",type:"text"},
   {name:"actor_kind",type:"select",values:["person","bot","superuser","system"],maxSelect:1,required:true},
   {name:"changes",type:"json",maxSize:1<<20},
   {name:"created",type:"autodate",onCreate:true,onUpdate:false}
  ],indexes:["CREATE INDEX idx_permission_events_member ON permission_events (member, created)"]
 }));
},(app)=>{
 const admins=app.findRecordsByFilter("members",'workspace_role = "admin"',"",1,0);
 if(admins.length)throw new Error("Reconcile workspace administrators before downgrade; restore the verified backup instead");
 const events=app.findRecordsByFilter("permission_events","","",1,0);
 if(events.length)throw new Error("Permission history exists; restore the verified pre-upgrade backup or roll forward");
 teamRules(app,false);
 replace(app,"members","createRule",`${oldWho} || ${ADMIN}`,oldWho);
 rules.removeClause(app,"members","createRule",NO_ROLE);
 rules.removeClause(app,"members","updateRule",NO_ROLE);
 const members=app.findCollectionByNameOrId("members");
 members.fields.removeByName("workspace_role");app.save(members);
 app.delete(app.findCollectionByNameOrId("permission_events"));
});

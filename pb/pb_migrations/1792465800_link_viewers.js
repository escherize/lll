/// <reference path="../pb_data/types.d.ts" />

// Team links read as a server-side identity (LLL-658).
//
// The board reads every page with its viewer's own credential, so the
// collection rules alone decide what a viewer sees. A team link ("KEY.MAC",
// `lll member invite --team`) names no member and so has no credential. This
// collection gives each team one: a record with the same access fields a
// member has (scope "teams", that one team, mode "ro", no owner), so every
// existing rule reads it exactly as it reads a read-only guest of that team.
//
// It is an auth collection only so that PocketBase can mint its tokens. Nobody
// signs in as a link viewer: password, OTP and OAuth2 sign-in are off, and only
// gopb mints a token (gopb/link_viewers.go), for a caller that already sees
// every team. The board keeps that token server-side; the browser holds only
// the link, and rotating the board token still revokes every link.
//
// A link viewer may read its own record and nothing else here: the client's
// token check (pb.verdict) probes it. Every write rule is null.
//
// The record's id is its team's id, so there is at most one per team without
// a lookup index. Deleting the team clears `teams`, which then sees nothing.
migrate(
  (app) => {
    const teams = app.findCollectionByNameOrId("teams");
    const members = app.findCollectionByNameOrId("members");
    const self = "@request.auth.id != \"\" && id = @request.auth.id";
    const viewers = new Collection({
      type: "auth",
      name: "link_viewers",
      listRule: self,
      viewRule: self,
      createRule: null,
      updateRule: null,
      deleteRule: null,
      authRule: null,
      manageRule: null,
      passwordAuth: { enabled: false },
      otp: { enabled: false },
      mfa: { enabled: false },
      oauth2: { enabled: false },
      // A week, the life of a link's board cookie. The board mints a fresh
      // token per page load; only a long-lived /events stream keeps one.
      authToken: { duration: 604800 },
      fields: [
        { name: "teams", type: "relation", collectionId: teams.id, maxSelect: 999, cascadeDelete: false },
        { name: "scope", type: "select", values: ["all", "teams"], maxSelect: 1, required: true },
        { name: "mode", type: "select", values: ["rw", "ro"], maxSelect: 1, required: true },
        // Always empty. The rules read @request.auth.owner, so the field
        // must exist for them to resolve against this collection.
        { name: "owner", type: "relation", collectionId: members.id, maxSelect: 1, cascadeDelete: false },
      ],
    });
    app.save(viewers);
  },
  (app) => {
    app.delete(app.findCollectionByNameOrId("link_viewers"));
  },
);

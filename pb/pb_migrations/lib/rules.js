// Edit a collection rule one clause at a time (LLL-657).
//
// A rule migration used to assign the whole rule string, so it had to repeat
// every clause an earlier migration added, and a clause it forgot was
// dropped without an error. These helpers read the rule the database holds
// now and add or remove one top-level `&&` clause, so a migration names only
// the clause it changes:
//
//   const rules = require(`${__migrations}/lib/rules.js`);
//   const NO_ASSIGNEE = "@request.body.assignee:isset = false";
//   migrate(
//     (app) => rules.addClause(app, "issues", "createRule", NO_ASSIGNEE),
//     (app) => rules.removeClause(app, "issues", "createRule", NO_ASSIGNEE),
//   );
//
// `__migrations` is the absolute path of the migrations directory; gopb binds
// it (gopb.go, bindMigrationsDir). A relative require resolves against the
// process working directory, not this directory.
//
// Each helper throws instead of guessing, and a throw fails the boot:
// - the rule is null (superuser only) or "" (anyone). Adding a condition to
//   either changes who may call the verb in a way one clause cannot express.
// - the rule has a top-level `||`, so it is not a list of `&&` clauses.
// - the rule or clause has a `//` comment, unbalanced parentheses or an
//   unclosed quote, or the clause is empty. A comment runs to the end of the
//   line, so a clause appended after one would be ignored.
// - addClause: the clause is already there.
// - removeClause: the clause is not there, or it is the only clause.
//
// Clauses compare as text after removing parentheses around the whole clause
// and collapsing whitespace outside quotes. A clause with its own top-level `&&` or `||` is added in
// parentheses.
//
// Applied migrations do not run again, but a fresh database runs every
// migration with this file as it is at that time. Do not change what an
// exported function does; add a new function instead.

// Scans `text` outside quotes. Returns its top-level `&&` parts (trimmed),
// whether it has a top-level `||`, and its whitespace-collapsed form. Throws
// on a comment, unbalanced parentheses or an unclosed quote.
function scan(text, where) {
  const ands = [];
  let hasOr = false;
  let depth = 0;
  let quote = "";
  let start = 0;
  let flat = "";
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quote) {
      flat += c;
      if (c === "\\") flat += text[++i] || "";
      else if (c === quote) quote = "";
      continue;
    }
    if (/\s/.test(c)) {
      if (!flat.endsWith(" ")) flat += " ";
      continue;
    }
    flat += c;
    if (c === '"' || c === "'") quote = c;
    else if (c === "(") depth++;
    else if (c === ")" && --depth < 0) throw new Error(`${where}: unbalanced ")": ${text}`);
    else if (text.startsWith("//", i)) throw new Error(`${where}: a // comment hides what follows it: ${text}`);
    else if (depth === 0 && text.startsWith("&&", i)) {
      ands.push(text.slice(start, i).trim());
      start = i + 2;
      i++;
      flat += "&";
    } else if (depth === 0 && text.startsWith("||", i)) {
      hasOr = true;
    }
  }
  if (quote) throw new Error(`${where}: unclosed quote: ${text}`);
  if (depth !== 0) throw new Error(`${where}: unbalanced "(": ${text}`);
  ands.push(text.slice(start).trim());
  return { ands, hasOr, flat: flat.trim() };
}

// True when the parenthesis opening `text` closes at its last character.
// `text` is already known to be balanced.
function wrapped(text) {
  if (text[0] !== "(") return false;
  let depth = 0;
  let quote = "";
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quote) {
      if (c === "\\") i++;
      else if (c === quote) quote = "";
      continue;
    }
    if (c === '"' || c === "'") quote = c;
    else if (c === "(") depth++;
    else if (c === ")" && --depth === 0) return i === text.length - 1;
  }
  return false;
}

// The form a clause compares in: outer parentheses removed, whitespace
// outside quotes collapsed.
function bare(clause, where) {
  let text = clause.trim();
  scan(text, where);
  while (wrapped(text)) text = text.slice(1, -1).trim();
  return scan(text, where).flat;
}

// The form a clause is written in: parenthesized if it has its own `&&`/`||`.
function written(clause, where) {
  const text = bare(clause, where);
  if (text === "") throw new Error(`${where}: empty clause`);
  const { ands, hasOr } = scan(text, where);
  return ands.length > 1 || hasOr ? `(${text})` : text;
}

function clausesOf(collection, ruleName) {
  const where = `${collection.name}.${ruleName}`;
  if (collection[ruleName] === null || collection[ruleName] === undefined) {
    throw new Error(`${where} is null (superuser only); set it whole`);
  }
  // A PocketBase collection hands a rule over as a Go *string, which JS sees
  // as an object: indexing it yields nothing, so read it as text (LLL-681).
  const rule = String(collection[ruleName]);
  if (rule.trim() === "") throw new Error(`${where} is "" (anyone); set it whole`);
  const { ands, hasOr } = scan(rule, where);
  if (hasOr) throw new Error(`${where} has a top-level ||: ${rule}`);
  return ands;
}

// Returns the rule with `clause` appended as a top-level `&&` clause.
function withClause(collection, ruleName, clause) {
  const where = `${collection.name}.${ruleName}`;
  const clauses = clausesOf(collection, ruleName);
  const add = written(clause, where);
  if (clauses.some((c) => bare(c, where) === bare(add, where))) {
    throw new Error(`${where} already has the clause ${bare(add, where)}`);
  }
  return clauses.concat([add]).join(" && ");
}

// Returns the rule without the top-level `&&` clause `clause`.
function withoutClause(collection, ruleName, clause) {
  const where = `${collection.name}.${ruleName}`;
  const clauses = clausesOf(collection, ruleName);
  const drop = bare(clause, where);
  const kept = clauses.filter((c) => bare(c, where) !== drop);
  if (kept.length === clauses.length) {
    throw new Error(`${where} has no clause ${drop}: ${collection[ruleName]}`);
  }
  if (kept.length === 0) throw new Error(`${where} would be empty, which means anyone`);
  return kept.join(" && ");
}

function addClause(app, name, ruleName, clause) {
  const collection = app.findCollectionByNameOrId(name);
  collection[ruleName] = withClause(collection, ruleName, clause);
  app.save(collection);
}

function removeClause(app, name, ruleName, clause) {
  const collection = app.findCollectionByNameOrId(name);
  collection[ruleName] = withoutClause(collection, ruleName, clause);
  app.save(collection);
}

module.exports = { addClause, removeClause, withClause, withoutClause };

// Edit a collection rule one clause at a time (LLL-657).
//
// A rule migration used to assign the whole rule string, so it had to repeat
// every clause an earlier migration added, and a clause it forgot was
// dropped without an error. These helpers read the rule the database holds
// now and add or remove one top-level `&&` clause, so a migration names only
// the clause it changes:
//
//   const rules = require(`${__migrations}/lib/rules.js`);
//   const NO_AUTHOR = "@request.body.author:isset = false";
//   migrate(
//     (app) => rules.addClause(app, "docs", "createRule", NO_AUTHOR),
//     (app) => rules.removeClause(app, "docs", "createRule", NO_AUTHOR),
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
// - addClause: the clause is already there.
// - removeClause: the clause is not there, or it is the only clause.
//
// Clauses compare as text after trimming and removing parentheses around the
// whole clause. A clause with its own top-level `&&` or `||` is added in
// parentheses.
//
// Applied migrations do not run again, but a fresh database runs every
// migration with this file as it is at that time. Do not change what an
// exported function does; add a new function instead.

// Splits `rule` at top-level `sep` ("&&" or "||"), outside quotes and
// parentheses. Returns the trimmed parts.
function splitTop(rule, sep) {
  const parts = [];
  let depth = 0;
  let quote = "";
  let start = 0;
  for (let i = 0; i < rule.length; i++) {
    const c = rule[i];
    if (quote) {
      if (c === "\\") i++;
      else if (c === quote) quote = "";
      continue;
    }
    if (c === '"' || c === "'") quote = c;
    else if (c === "(") depth++;
    else if (c === ")") depth--;
    else if (depth === 0 && rule.startsWith(sep, i)) {
      parts.push(rule.slice(start, i).trim());
      start = i + sep.length;
      i += sep.length - 1;
    }
  }
  parts.push(rule.slice(start).trim());
  return parts;
}

// True when the parenthesis opening `text` closes at its last character.
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

// The form a clause compares in: trimmed, outer parentheses removed.
function bare(clause) {
  let text = clause.trim();
  while (wrapped(text)) text = text.slice(1, -1).trim();
  return text;
}

// The form a clause is written in: parenthesized if it has its own `&&`/`||`.
function written(clause) {
  const text = bare(clause);
  return splitTop(text, "&&").length > 1 || splitTop(text, "||").length > 1 ? `(${text})` : text;
}

function clausesOf(collection, ruleName) {
  const rule = collection[ruleName];
  const where = `${collection.name}.${ruleName}`;
  if (rule === null || rule === undefined) throw new Error(`${where} is null (superuser only); set it whole`);
  if (rule.trim() === "") throw new Error(`${where} is "" (anyone); set it whole`);
  if (splitTop(rule, "||").length > 1) throw new Error(`${where} has a top-level ||: ${rule}`);
  return splitTop(rule, "&&");
}

// Returns `rule` with `clause` appended as a top-level `&&` clause.
function withClause(collection, ruleName, clause) {
  const clauses = clausesOf(collection, ruleName);
  if (clauses.some((c) => bare(c) === bare(clause))) {
    throw new Error(`${collection.name}.${ruleName} already has the clause ${bare(clause)}`);
  }
  return clauses.concat([written(clause)]).join(" && ");
}

// Returns `rule` without the top-level `&&` clause `clause`.
function withoutClause(collection, ruleName, clause) {
  const clauses = clausesOf(collection, ruleName);
  const kept = clauses.filter((c) => bare(c) !== bare(clause));
  if (kept.length === clauses.length) {
    throw new Error(`${collection.name}.${ruleName} has no clause ${bare(clause)}: ${collection[ruleName]}`);
  }
  if (kept.length === 0) throw new Error(`${collection.name}.${ruleName} would be empty, which means anyone`);
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

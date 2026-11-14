'use strict';
const initial = () => ({ mode: 'rw', engineering: 'editor', finance: 'viewer', ownerRemoved: false });
let state = initial();
const roleRank = { none: 0, viewer: 1, editor: 2 };
const roleName = ['No access', 'Viewer', 'Editor'];
const svgCheck = '<svg class="status-icon" aria-hidden="true" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="m5 8 2 2 4-4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
const person = '<span class="avatar" aria-hidden="true">AN</span>';
const labels = { engineering: 'Engineering', finance: 'Finance' };
function accessName(world, value) {
  return world === 'current' ? ['No access', 'Read-only', 'Read-write'][value] : roleName[value];
}
function rank(world, team, bot = false) {
  const human = world === 'current' ? (state.mode === 'rw' ? 2 : 1) : roleRank[state[team]];
  if (!bot) return human;
  if (state.ownerRemoved) return 0;
  const own = world === 'current' ? 2 : (team === 'engineering' ? 2 : 1);
  return Math.min(human, own);
}
function modeSelect(prefix) {
  return `<label for="${prefix}-current-mode">Member-wide mode <select id="${prefix}-current-mode" data-setting="mode"><option value="rw" ${state.mode === 'rw' ? 'selected' : ''}>Read-write</option><option value="ro" ${state.mode === 'ro' ? 'selected' : ''}>Read-only</option></select></label>`;
}
function roleSelect(prefix, team) {
  return `<select id="${prefix}-${team}" data-setting="${team}" aria-label="Draft role in ${labels[team]}">${['none', 'viewer', 'editor'].map(role => `<option value="${role}" ${state[team] === role ? 'selected' : ''}>${roleName[roleRank[role]]}</option>`).join('')}</select>`;
}
function heading(world, subtitle) {
  return `<div class="world-head"><div><h2>${world === 'current' ? 'Current world' : 'Proposed world'}</h2><p>${subtitle}</p></div><span class="pill">${world === 'current' ? 'Shipped v1.7.0' : 'Draft · not implemented'}</span></div>`;
}
function scenario() {
  return `<div class="scenario">${person}<div><strong>Alice needs to edit Engineering and only read Finance.</strong><p>One person, two teams. Projects use the same access as their team in both worlds.</p></div></div>`;
}
function relationshipMap(world) {
  const current = world === 'current';
  const eng = accessName(world, rank(world, 'engineering'));
  const fin = accessName(world, rank(world, 'finance'));
  const mobile = `<div class="mobile-map" role="group" aria-label="${current ? 'Current' : 'Proposed'} relationship map"><div class="mobile-node"><strong>${current ? 'Server / instance' : 'Workspace · Acme'}</strong><p>${current ? 'Implicit shared space; no organization role field' : 'Workspace administration is explicit'}</p></div><div class="mobile-connector">Contains people and teams</div><div class="mobile-node"><strong>Alice Nguyen</strong><p>${current ? `One member-wide mode: ${state.mode === 'rw' ? 'read-write' : 'read-only'}` : 'Workspace Member · team-specific roles'}</p></div><div class="mobile-connector grant-connector">Grants access to these teams</div><div class="mobile-teams">${[['Engineering', eng, 'Release 1'], ['Finance', fin, 'Payroll']].map(([team, role, project]) => `<div class="mobile-team"><strong>${team}</strong><span>${role} · ${current ? 'member-wide mode' : 'direct membership'}</span><p>${project} · same team access</p></div>`).join('')}</div></div>`;
  return mobile + `<div class="graph-scroll" role="region" tabindex="0" aria-label="${current ? 'Current' : 'Proposed'} relationship map"><svg class="graph" viewBox="0 0 560 420" role="img" aria-labelledby="${world}-map-title ${world}-map-desc">
    <title id="${world}-map-title">${current ? 'Current instance-wide account mode' : 'Proposed team-specific membership roles'}</title>
    <desc id="${world}-map-desc">${current ? 'A server contains Alice and two teams. Alice has one shared mode for both teams.' : 'A workspace contains Alice and two teams. Each team membership has its own role.'} Engineering: ${eng}. Finance: ${fin}. Projects inherit team access.</desc>
    <defs><marker id="${world}-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="m1 1 4 2.5-4 2.5" fill="none" stroke="var(--muted)" stroke-width="1.2"/></marker></defs>
    <rect class="node" x="20" y="20" width="520" height="66" rx="6"/>
    <text class="node-title" x="38" y="46">${current ? 'Server / instance' : 'Workspace · Acme'}</text>
    <text class="secondary" x="38" y="67">${current ? 'Implicit shared space; no organization role record' : 'Explicit administration; team roles determine work access'}</text>
    <path class="edge" d="M100 86V192M380 86V116"/>
    <rect class="boundary" x="225" y="116" width="315" height="264" rx="6"/>
    <text class="secondary" x="242" y="139">Teams are the access boundary</text>
    <rect class="node" x="20" y="192" width="165" height="92" rx="6"/>
    <circle class="avatar-shape" cx="44" cy="218" r="11"/><text class="initials" text-anchor="middle" x="44" y="222">AN</text>
    <text class="node-title" x="62" y="223">Alice Nguyen</text>
    <text class="secondary" x="34" y="247">${current ? 'Server-wide member' : 'Workspace member'}</text>
    <text class="secondary" x="34" y="266">${current ? (state.mode === 'rw' ? 'One mode: read-write' : 'One mode: read-only') : 'Team-specific roles'}</text>
    <path class="grant" marker-end="url(#${world}-arrow)" d="M185 214H210V195H247"/>
    <path class="grant" marker-end="url(#${world}-arrow)" d="M185 262H210V318H247"/>
    <rect class="node" x="250" y="157" width="270" height="91" rx="6"/>
    <text class="node-title" x="266" y="180">Engineering</text><text x="266" y="202">${eng}${current ? ' · member-wide mode' : ' · direct membership'}</text>
    <path class="edge" d="M266 216H504"/><text class="secondary" x="266" y="236">Release 1 · same team access</text>
    <rect class="node" x="250" y="275" width="270" height="91" rx="6"/>
    <text class="node-title" x="266" y="298">Finance</text><text x="266" y="320">${fin}${current ? ' · member-wide mode' : ' · direct membership'}</text>
    <path class="edge" d="M266 334H504"/><text class="secondary" x="266" y="354">Payroll · same team access</text>
    <text class="edge-label" x="22" y="354">${current ? 'One account, one mode.' : 'One role per membership.'}</text>
    <text class="edge-label" x="22" y="372">${current ? 'Across all granted teams.' : 'No grant, no team access.'}</text>
  </svg></div><div class="graph-key"><span><i class="key-line" aria-hidden="true"></i>Contains</span><span><i class="key-line dash" aria-hidden="true"></i>Grants access</span></div>`;
}
function currentResult() {
  const result = state.mode === 'rw' ? 'Finance becomes writable too.' : 'Engineering becomes read-only too.';
  return `<div class="flash"><strong>The example cannot be expressed.</strong><br>${result} One account mode applies to both teams.</div>`;
}
function proposedResult() {
  const match = state.engineering === 'editor' && state.finance === 'viewer';
  return `<div class="result">${match ? svgCheck : ''}<div><strong>${match ? 'The example is represented directly.' : 'Each team is configured independently.'}</strong><p>Engineering: ${roleName[roleRank[state.engineering]]}. Finance: ${roleName[roleRank[state.finance]]}. No hidden workspace-wide editing grant.</p></div></div>`;
}
function renderMaps() {
  document.getElementById('maps').innerHTML = scenario() + `<div class="comparison"><article class="world">${heading('current', 'Team list + one read/write mode per identity')}<div class="world-tools">${modeSelect('map')}<span class="muted">Scope: selected teams</span></div>${relationshipMap('current')}${currentResult()}<div class="world-note"><strong>Administrative authority is implicit.</strong><p>Some management actions require all-team read-write access; changing grants still needs a superuser. A shared board token uses the board’s identity.</p></div></article><article class="world">${heading('proposed', 'Workspace role + an explicit role per team')}<div class="world-tools"><div class="mini-controls"><label for="map-engineering">Engineering ${roleSelect('map', 'engineering')}</label><label for="map-finance">Finance ${roleSelect('map', 'finance')}</label></div></div>${relationshipMap('proposed')}${proposedResult()}<div class="world-note"><strong>Administration becomes a named responsibility.</strong><p>Member and Admin are separate from Viewer and Editor. Whether admins automatically see restricted team data is an open policy decision.</p></div></article></div><p class="map-footnote">Solid lines show containment; dashed lines show access grants. Project names are examples, not extra permission layers. On mobile, each map becomes a stacked relationship view.</p>`;
}
function renderManage() {
  const currentRole = state.mode === 'rw' ? 'Read-write' : 'Read-only';
  document.getElementById('manage').innerHTML = scenario() + `<div class="comparison"><article class="world">${heading('current', 'Explanatory reconstruction of the current access model')}<div class="mock-nav"><span>Members</span><span class="selected">Access</span><span>Teams</span></div><div class="person-head">${person}<div><h3>Alice Nguyen</h3><p>Person · server-wide identity</p></div></div><dl class="property-list"><div class="property"><dt>Scope</dt><dd>Selected teams</dd></div><div class="property"><dt><label for="manage-current-mode">Mode</label></dt><dd><select id="manage-current-mode" data-setting="mode"><option value="rw" ${state.mode === 'rw' ? 'selected' : ''}>Read-write</option><option value="ro" ${state.mode === 'ro' ? 'selected' : ''}>Read-only</option></select></dd></div><div class="property"><dt>Workspace role</dt><dd>No separate role field</dd></div></dl><div class="membership-heading"><strong>Granted teams</strong><span class="muted">One mode for all</span></div><table class="access-table"><thead><tr><th scope="col">Team</th><th scope="col">Effective access</th></tr></thead><tbody><tr><th scope="row">Engineering</th><td>${currentRole}</td></tr><tr><th scope="row">Finance</th><td>${currentRole}</td></tr></tbody></table>${currentResult()}<div class="role-inspector"><strong>Accepting a different-mode invitation</strong><p>An invitation cannot silently upgrade or downgrade unrelated teams. If the requested combination cannot fit one mode, acceptance is refused and the invite stays unused.</p><p>Only a full read-write independent person or a superuser can invite people; scoped read-write members cannot invite someone to their own team.</p></div></article><article class="world">${heading('proposed', 'Draft people page · roles belong to memberships')}<div class="mock-nav"><span class="selected">People</span><span>Teams</span><span>Bots</span><span>Activity</span></div><div class="person-head">${person}<div><h3>Alice Nguyen</h3><p>Person · workspace member</p></div></div><dl class="property-list"><div class="property"><dt>Workspace role</dt><dd>Member</dd></div><div class="property"><dt>Administration</dt><dd>Cannot manage people or grants</dd></div><div class="property"><dt>Default team access</dt><dd>No access</dd></div></dl><div class="membership-heading"><strong>Team memberships</strong><span class="muted">Explicit grants</span></div><table class="access-table"><thead><tr><th scope="col">Team</th><th scope="col">Role</th></tr></thead><tbody><tr><th scope="row"><label for="manage-engineering">Engineering</label><span class="sub">Direct membership</span></th><td>${roleSelect('manage', 'engineering')}</td></tr><tr><th scope="row"><label for="manage-finance">Finance</label><span class="sub">Direct membership</span></th><td>${roleSelect('manage', 'finance')}</td></tr></tbody></table>${proposedResult()}<div class="role-inspector"><strong>Why does Alice have this access?</strong><ul><li>Workspace Member does not itself grant team data access.</li><li>Viewer reads work. Editor can create and edit work, comment and claim.</li><li>Projects use their team’s grants. Sessions do not add grants.</li></ul><p>Draft capability detail still needs review for deletion, project archival, labels and bot provisioning. Administrator private-data access is not simulated here.</p></div></article></div><p class="map-footnote">These are clickable explanatory mockups. Changes stay in this page; no invite, role change or API call is sent.</p>`;
}
function botWorld(world) {
  const current = world === 'current';
  const humanEng = accessName(world, rank(world, 'engineering'));
  const humanFin = accessName(world, rank(world, 'finance'));
  return `<article class="world">${heading(world, current ? 'Existing personal bot · one mode per member' : 'Draft personal bot · explicit roles per team')}<div class="authority-chain"><div class="authority-part"><small>Human owner · authority ceiling</small><strong>Alice Nguyen</strong><p>${state.ownerRemoved ? 'Removed in this simulation' : `Engineering ${humanEng}<br>Finance ${humanFin}`}</p></div><div class="authority-part"><small>Bot identity · separate credential</small><strong>bot-reviewer</strong><p>${current ? 'Own grant: read-write in both teams' : 'Own grants: Engineering Editor, Finance Viewer'}</p></div><div class="authority-part"><strong>Created by bot-coordinator</strong><p>Delegated workers also stay within the creating bot’s authority. This ceiling remains; this study does not replace it with the owner check alone.</p></div></div><div class="table-scroll"><table class="bot-table"><caption class="sr-only">${current ? 'Current' : 'Proposed'} effective bot access</caption><thead><tr><th scope="col">Team</th><th scope="col">Bot grant</th><th scope="col">Owner ceiling</th><th scope="col">Effective</th></tr></thead><tbody>${['engineering', 'finance'].map(team => `<tr><th scope="row">${labels[team]}</th><td data-label="Bot grant">${current ? 'Read-write' : roleName[team === 'engineering' ? 2 : 1]}</td><td data-label="Owner ceiling">${state.ownerRemoved ? 'No access' : accessName(world, rank(world, team))}</td><td data-label="Effective">${accessName(world, rank(world, team, true))}</td></tr>`).join('')}</tbody></table></div><div class="formula"><strong>Effective bot access</strong> stays within its own grants, its owner and any delegation ceiling. Wider new grants must be refused; this is not permission to save an overpowered bot and silently clip it.</div><div class="sessions"><strong>Sessions run as the bot</strong><div class="session-row"><span class="session-dot ${state.ownerRemoved ? 'denied' : ''}" aria-hidden="true"></span><div><span class="session-name">codex-review-42</span><p>${state.ownerRemoved ? 'Runtime may continue; issue access is no longer authorized.' : 'Running as bot-reviewer. No independent team permissions.'}</p></div></div><div class="session-row"><span class="session-dot ${state.ownerRemoved ? 'denied' : ''}" aria-hidden="true"></span><div><span class="session-name">claude-review-43</span><p>${state.ownerRemoved ? 'A live terminal does not preserve a revoked grant.' : 'Same identity and limits; a session label is not a credential.'}</p></div></div></div><div class="world-note"><strong>${current ? 'Ownership is already a useful security rule.' : 'Keep personal bots bounded; research durable service bots.'}</strong><p>${current ? 'Ownership is one human hop. Narrowing or removing the owner cannot leave broader access behind. Old work and attribution do not need to be erased.' : 'A release bot that must outlive Alice needs an explicit lifecycle and stewardship policy. Workspace-owned automation is a research option, not a feature implemented by this mockup.'}</p></div></article>`;
}
function renderBots() {
  document.getElementById('bots').innerHTML = `<div class="bot-controls"><div><h2>A bot cannot gain authority from a session.</h2><p>Use Manage access to change Alice’s roles, then inspect the limits here. This lab uses a fictional existing bot and a creator whose grants cover it.</p></div><button id="owner-removal" data-owner-toggle type="button">${state.ownerRemoved ? 'Restore example owner' : 'Simulate owner removal'}</button></div>${state.ownerRemoved ? '<div class="flash" style="margin:0 0 20px"><strong>Owner removed in this local simulation.</strong> Both bots lose team access. A terminal’s runtime state is a separate concern. Restore the example owner to reset this scenario.</div>' : ''}<div class="comparison">${botWorld('current')}${botWorld('proposed')}</div><p class="map-footnote">The data hierarchy, permission grants, ownership limits and execution sessions are different relationships. Do not turn them into one inheritance tree.</p>`;
}
function render() {
  const focus = document.activeElement && document.activeElement.id;
  renderMaps(); renderManage(); renderBots();
  if (focus) document.getElementById(focus)?.focus({ preventScroll: true });
}
function setView(name, updateHash = true) {
  if (!['maps', 'manage', 'bots', 'research'].includes(name)) name = 'maps';
  document.querySelectorAll('[data-view]').forEach(button => {
    const active = button.dataset.view === name;
    button.setAttribute('aria-selected', String(active));
    button.tabIndex = active ? 0 : -1;
  });
  document.querySelectorAll('.view').forEach(panel => { panel.hidden = panel.id !== name; });
  if (updateHash) history.replaceState(null, '', '#' + name);
}
document.addEventListener('change', event => {
  if (event.target.matches('[data-setting]')) {
    state[event.target.dataset.setting] = event.target.value;
    render();
    document.getElementById('announcement').textContent = 'Example updated. ' + (event.target.dataset.setting === 'mode' ? 'Current mode applies to both teams.' : 'Draft membership changed independently.');
  }
});
document.addEventListener('click', event => {
  const tab = event.target.closest('[data-view]');
  if (tab) setView(tab.dataset.view);
  const go = event.target.closest('[data-go]');
  if (go) { event.preventDefault(); setView(go.dataset.go); document.getElementById('tab-' + go.dataset.go).focus(); window.scrollTo(0, 0); }
  if (event.target.closest('[data-owner-toggle]')) { state.ownerRemoved = !state.ownerRemoved; render(); document.getElementById('announcement').textContent = state.ownerRemoved ? 'Simulated owner removal. Bot team access is now denied.' : 'Example owner restored.'; }
});
document.querySelector('.tabs').addEventListener('keydown', event => {
  const tabs = [...document.querySelectorAll('[data-view]')];
  let index = tabs.indexOf(document.activeElement);
  if (index < 0 || !['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
  event.preventDefault();
  if (event.key === 'Home') index = 0;
  else if (event.key === 'End') index = tabs.length - 1;
  else index = (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
  setView(tabs[index].dataset.view); tabs[index].focus();
});
document.getElementById('reset').addEventListener('click', () => { state = initial(); render(); document.getElementById('announcement').textContent = 'Example reset. Engineering Editor, Finance Viewer in the draft.'; });
window.addEventListener('hashchange', () => setView(location.hash.slice(1), false));
render(); setView(location.hash.slice(1), false);

---
name: lll
description: Dark instrument-panel issue board — Linear's grammar with lll's own orange.
colors:
  ink-ground: "#0e0f11"
  rail-ground: "#111316"
  panel: "#141619"
  raised: "#191c20"
  hover: "#1d2126"
  hairline: "rgba(255, 255, 255, 0.07)"
  hairline-strong: "rgba(255, 255, 255, 0.12)"
  text-primary: "#e8eaed"
  text-secondary: "#9299a2"
  text-tertiary: "#828994"
  ember-orange: "#f0883e"
  ember-orange-hover: "#f79b57"
  ember-orange-deep: "#c96a25"
  ember-ink: "#1a0f06"
  ember-glow: "rgba(240, 136, 62, 0.16)"
  error-text: "#f0827b"
  error-border: "rgba(229, 83, 75, 0.4)"
  error-wash: "rgba(229, 83, 75, 0.12)"
  state-backlog: "#828994"
  state-todo: "#9299a2"
  state-in-progress: "#e0b13e"
  state-in-review: "#8d7ce6"
  state-done: "#4cb782"
  state-cancelled: "#828994"
  avatar-sky: "#7cc0e8"
  avatar-sand: "#d8b06a"
  avatar-violet: "#9d8fe0"
  avatar-moss: "#82c99a"
  avatar-ink: "#0a1620"
  scrim: "rgba(6, 7, 8, 0.62)"
typography:
  title:
    fontFamily: "Inter Variable, system-ui, sans-serif"
    fontSize: "19px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-0.012em"
  body:
    fontFamily: "Inter Variable, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.45
  label:
    fontFamily: "Inter Variable, system-ui, sans-serif"
    fontSize: "11px"
    fontWeight: 600
    letterSpacing: "0.02em"
  micro:
    fontFamily: "Inter Variable, system-ui, sans-serif"
    fontSize: "11.5px"
    fontWeight: 500
  code:
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "12px"
  emoji:
    fontSize: "14px"
  dialog-glyph:
    fontSize: "16px"
  scale:
    avatar-initials: "8.5px"
    mark-letter: "10px"
    chip: "10.5px"
    props-heading: "11px"
    card-key: "11.5px"
    prop-key: "12px"
    select-flash: "12.5px"
    base: "13px"
    title: "19px"
rounded:
  indicator: "1px"
  focus: "4px"
  mark: "5px"
  base: "6px"
  lg: "8px"
  pill: "999px"
spacing:
  hairline: "2px"
  xs: "5px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "28px"
components:
  button:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.base}"
    padding: "5px 10px"
  button-hover:
    backgroundColor: "{colors.hover}"
  button-primary:
    backgroundColor: "{colors.ember-orange}"
    textColor: "{colors.ember-ink}"
    rounded: "{rounded.base}"
    padding: "5px 10px"
  button-primary-hover:
    backgroundColor: "{colors.ember-orange-hover}"
  card:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.base}"
    padding: "6px 8px"
  card-hover:
    backgroundColor: "{colors.hover}"
  input:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.base}"
    padding: "5px 8px"
  chip:
    textColor: "{colors.text-secondary}"
    rounded: "{rounded.pill}"
    padding: "0 7px 0 5px"
  flash:
    backgroundColor: "{colors.error-wash}"
    textColor: "{colors.error-text}"
    rounded: "{rounded.base}"
    padding: "6px 10px"
---

# Design System: lll

## Overview

**Creative North Star: "The Instrument Panel"**

lll is a dark, dense, quiet issue board: every issue's state legible in one
glance, refusing the airy marketing-card look of generic kanban tools. The
world is Linear's grammar rebuilt in lll's own materials — a near-black ground,
hairline white-alpha borders, one small variable typeface at 13px, muted gray
text, and semantic state color carried almost entirely by small drawn icons.
Chrome recedes; the data is the interface.

Color is rationed. The single accent, an ember orange (#f0883e), appears only
where the user can act (primary buttons, focus rings, selection, the workspace
mark) and on exactly one piece of data: urgent priority. Errors get one voice
of their own — a muted red flash strip patched in over SSE. Everything else
speaks in three grays and the six semantic state hues. Depth is tonal, not
shadowed: five closely-spaced dark surfaces layer the UI, and the one real
shadow is a 1px whisper under cards.

Note: PRODUCT.md's brand commitment named a teal accent; the shipped build is
orange throughout (tokens, comp, icons). Orange #f0883e is canonical.

**Key Characteristics:**
- Dark-only; near-black tonal surfaces, no light theme.
- Compact density: 13px base type, 5-8px internal padding, 18px avatars.
- One accent (ember orange), reserved for interactivity + urgent priority.
- One error voice (muted red flash strip), server-patched, self-clearing.
- Semantic state colors expressed through drawn 14px SVG circle icons.
- Tabular numerals everywhere counts and keys appear.
- Server-rendered HTML morphed live over SSE; stable element ids are a design constraint.

## Colors

A near-black tonal ladder, three gray text voices, one rationed orange accent,
one muted error red, and six semantic state hues.

### Primary
- **Ember Orange** (`--accent`, #f0883e): the only accent. Interactive
  affordances — primary buttons, input focus borders, `:focus-visible`
  outlines, the workspace mark gradient — plus one data meaning: the urgent
  priority icon's filled square. Hover shifts to **Ember Orange Hover**
  (#f79b57). The workspace mark's gradient deepens to **Ember Orange Deep**
  (#c96a25) at its dark end. Text on orange is **Ember Ink** (#1a0f06), a
  near-black warm brown, never white. **Ember Glow** (rgba(240,136,62,0.16))
  is the soft form: focus halo (`box-shadow: 0 0 0 3px`) and `::selection`
  background.

### Secondary
Semantic state colors (`--st-*`), used only via the drawn state icons and their
`currentColor`:
- **State In-Progress** (#e0b13e): muted yellow; half-filled circle.
- **State In-Review** (#8d7ce6): violet; three-quarter-filled circle.
- **State Done** (#4cb782): green; filled circle with dark check.
- **State Backlog / Todo / Cancelled** (#828994 / #9299a2 / #828994): gray;
  the resting and terminal states stay in the neutral register.

The error voice lives beside them, confined to the flash strip:
- **Error Text** (#f0827b) on **Error Wash** (rgba(229,83,75,0.12)) inside an
  **Error Border** (rgba(229,83,75,0.4)) hairline — the system's only red,
  and its only use of a tinted background.

### Tertiary
Per-member avatar hues, assigned server-side by name hash (classes `av-0`
through `av-3`) so a member's color is stable across sessions and surfaces:
- **Avatar Sky** (#7cc0e8), **Avatar Sand** (#d8b06a), **Avatar Violet**
  (#9d8fe0), **Avatar Moss** (#82c99a). All carry **Avatar Ink** (#0a1620)
  initials — dark, never white.

### Neutral
- **Ink Ground** (`--bg`, #0e0f11): page background; also the "punch-through"
  ink inside filled state icons (done check, cancelled X, urgent square).
- **Rail Ground** (`--bg-rail`, #111316) and **Panel** (`--bg-panel`,
  #141619): first tonal steps — left rail, board columns, inputs.
- **Raised** (`--bg-raised`, #191c20): cards, buttons, active rail item.
- **Hover** (`--bg-hover`, #1d2126): hover state for cards, buttons, rail links.
- **Hairline** (`--border`, rgba(255,255,255,0.07)) and **Hairline Strong**
  (rgba(255,255,255,0.12)): all borders are translucent white, never opaque
  gray. Hairline for structure (rail edge, topbar, columns, cards, chips);
  Strong for interactive edges (buttons, inputs, card hover) and scrollbar
  thumbs.
- **Text Primary / Secondary / Tertiary** (#e8eaed / #9299a2 / #828994):
  titles and body; secondary chrome (rail links, crumbs, descriptions,
  prop values); metadata (issue keys, placeholders, counts, prop labels).

### Named Rules
**The Ember Budget Rule.** Orange means "you can act here" or "urgent" —
nothing else. Never use it for decoration, emphasis, headings, or non-urgent
data.

**The One Error Voice Rule.** Failure speaks only through the flash strip's
muted red trio (#f0827b on rgba(229,83,75,0.12), rgba(229,83,75,0.4) border).
No other red, no red text inline, no red icons.

**The Icon-Carries-Color Rule.** State color reaches the page only through the
14px state icon (`color: var(--st-*)` + `currentColor`). Text next to the icon
stays gray; no colored text, no colored column headers, no tinted card
backgrounds.

**The White-Alpha Border Rule.** Borders are translucent white (0.07 structural,
0.12 interactive), so they read correctly over every tonal surface. No opaque
border grays. The one exception is the error flash, whose border is the red at
0.4 alpha — still translucent, never opaque.

## Typography

**Body Font:** Inter Variable (self-hosted woff2, weights 100-900), falling
back to system-ui, sans-serif. There is no second face.

**Character:** One quiet variable face at small sizes, differentiated by weight
(400-800), tight negative tracking on headings, and tabular numerals for
anything countable. Antialiased, line-height 1.45 base.

### Hierarchy
- **Title** (600, 19px, 1.3, -0.012em): the issue page `h1` — the largest type
  in the product.
- **Body** (400, 13px, 1.45): base size for everything — board columns, cards,
  comments, rail. Column headers and section headings are the same 13px at
  weight 600 (letter-spacing -0.005em); hierarchy comes from weight, not size.
- **Label** (600, 11px, +0.02em, UPPERCASE): sidebar section headers
  ("Properties"). The only uppercase in the system.
- **Micro** (500-800, 8.5-12.5px): the enumerated small steps — avatar
  initials (8.5px, 700), workspace mark letter (10px, 800), chips (10.5px),
  card key rows (11.5px, tabular-nums), comment meta and prop keys (12px),
  prop selects and the flash strip (12.5px).
- **Max measure:** descriptions 68ch, comments 65ch.

### Named Rules
**The Weight-Not-Size Rule.** Between 10.5px and 19px, hierarchy is expressed
by weight and color voice (text/text-2/text-3), rarely by size. Do not
introduce large display type.

**The Tabular Numerals Rule.** Issue keys, counts, and any aligned numbers set
`font-variant-numeric: tabular-nums`.

## Layout

Full-viewport app frame: fixed 220px left rail (`--bg-rail`, hairline right
border) beside a fluid main column with a 46px topbar (hairline bottom border,
16px horizontal padding). No page scroll; each region scrolls itself
(`height: 100vh; overflow: hidden` on `.app`).

**Board:** a flex row of six equal-width state columns (`flex: 1 1 0`,
min-width 170px), 12px gaps, 14-16px page padding, columns top-aligned and
independently scrollable. Cards stack with 5px gaps inside 6px column padding.

**Issue page:** a two-column grid — fluid main column (issue text max-width
760px, 28px/40px padding) plus a fixed 280px properties panel with a hairline
left border running the full height. Comments thread and composer sit under
the main column at max-width 680px, separated by a hairline top border.

**Create dialog:** a fixed overlay over the whole frame (z-index 60), the one
surface in the product that floats. Everything else displaces content.

**Flash strip:** sits between topbar and content (`margin: 10px 16px 0`),
patched over SSE by server actions and hidden when clear; it displaces
content rather than overlaying it.

**Spacing rhythm:** small steps, tightly packed — 2/5/6/8px inside components,
10/12/14/16px between regions, 24-28px only for page-level breathing room on
the issue page.

**Responsive (single breakpoint, 720px):** the rail disappears; the topbar
wraps and the create form goes full-width; board columns become fixed 240px
and scroll horizontally; the issue grid stacks to one column with the
properties panel moving between title and comments (hairline top+bottom
borders instead of a left border).

### Named Rules
**The Stable Id Rule.** `#board`, `#issue-detail`, and `#comments` are SSE
morph boundaries; cards are `#issue-{id}`, columns `#col-{state}`, comments
`#comment-{id}`. New surfaces must keep ids stable and semantic — Datastar
morphs by id, and agents are first-class consumers of the markup.

## Elevation & Depth

Depth is tonal, not shadowed. Five closely-spaced dark surfaces do the work:
ground (#0e0f11) → rail (#111316) → panel (#141619) → raised (#191c20) →
hover (#1d2126), each step subtly lighter, always paired with white-alpha
hairlines. Hover means "step one surface lighter," not "lift."

### Shadow Vocabulary
- **Card whisper** (`box-shadow: 0 1px 2px rgba(0, 0, 0, 0.25)`): the only
  resting shadow — under board cards, barely perceptible.
- **Focus glow** (`box-shadow: 0 0 0 3px var(--accent-dim)`): input focus,
  paired with an orange border; a ring, not a shadow.

### Named Rules
**The Tonal Ladder Rule.** New surfaces pick a rung on the existing ladder;
never invent a new dark gray, and never use large soft drop shadows.

## Shapes

Small consistent radii: 6px (`--radius`) on cards, buttons, inputs, selects,
rail links, and the flash strip; 8px (`--radius-lg`) on board columns only;
5px on the workspace mark and scrollbar thumbs; 4px on the `:focus-visible`
outline's rounding; full pill (999px) on label chips; circles for avatars and
state icons. Everything is a hairline-bordered rounded rectangle — no sharp
corners, no large radii, no clipping tricks.

Iconography is part of the form language: all icons are hand-drawn inline SVGs
defined once in a `<defs>` sprite (icons.html) and referenced via `<use>`.
State icons are a 14px circle grammar — dashed stroke (backlog), empty stroke
(todo), half fill (in-progress), three-quarter fill (in-review), filled+check
(done), filled+X (cancelled). Priority is a three-bar chart at three fill
levels (opacity 0.25 for unfilled bars), a dashed triple-dash for none, and an
orange filled square with an exclamation mark for urgent. Strokes run
1.3-1.7px with round caps.

### Named Rules
**The Drawn Icon Rule.** Icons are drawn inline SVG in the shared sprite —
never icon fonts, emoji, or third-party icon packages. New icons match the
14px grid, ~1.5px round-capped strokes, and `currentColor`.

## Components

### Buttons
- **Shape:** gently rounded (6px), 5px 10px padding, inline-flex with 6px icon gap.
- **Default:** raised surface (#191c20) with a strong hairline border, primary
  text, weight 500; hover steps to the hover surface (#1d2126).
- **Primary:** ember orange fill, borderless, ember-ink text at weight 600;
  hover lightens to #f79b57. Reserved for the main action per view ("New
  issue", "Comment"), usually with a small drawn glyph (e.g. a stroked plus).
- **Focus:** the global 2px orange `:focus-visible` outline, offset 1px, with
  4px rounding.

### Cards / Containers
- **Board card:** raised surface, hairline border, 6px radius, 6px 8px padding,
  card-whisper shadow. Three-row anatomy: micro key row (key left, priority
  icon right, tabular-nums, text-3), 500-weight title clamped to two lines,
  then chips left / 18px avatar right. Hover: strong border + hover surface;
  the whole card is a link.
- **Column:** panel surface, hairline border, 8px radius, 6px padding; header
  is 13px/600 with state icon and a text-3 count.

### Chips (labels)
- **Style:** pill (999px), hairline border, transparent background, 10.5px
  text-2 text, with a 7px color dot fed by the label's stored color (falls
  back to text-3). Read-only metadata — chips are not buttons.

### Inputs / Fields
- **Style:** panel background, strong hairline border, 6px radius, 5px 8px
  padding, inherited 13px type; placeholders in text-3.
- **Focus:** orange border + 3px ember-glow ring (`outline: none`).
- **Selects and textareas** share the treatment; the comment textarea is
  min-height 64px, vertically resizable.

### Dialog (create issue)
- **Surface:** the panel rung (#141619) with a strong hairline and the 6px
  radius — `--radius-lg` stays the board columns' alone. Max-width 600px,
  8vh from the top, 84vh tall at most and scrolling inside itself.
- **Depth:** tonal, not shadowed. Separation comes from a plain dim
  (`rgba(6, 7, 8, 0.62)`) over the board, never a drop shadow. The board stays
  legible behind it, which is the reason it is a dialog and not a page.
- **Anatomy:** 13px/600 heading row with a text-3 close glyph, then the title
  input, the description textarea (min-height 108px, resizable), one wrapping
  row of 12.5px property selects, one wrapping row of label chips, and a
  footer with a hairline top border carrying a text-3 hint and the actions.
- **Labels are the one control that needs telling,** because the four selects
  say their own name and a chip does not; it gets a 12px text-3 key in the
  properties-panel register. A checked chip spends the accent (orange border,
  ember-dim wash) — chips are read-only metadata everywhere else, but here the
  chip *is* the affordance, so it is inside the Ember Budget.
- **Behavior:** Escape and a scrim click close it, `c` opens it from the board.
  Nothing in it closes on its own: the SERVER patches the open signal, and
  only on success, so a rejected create keeps everything typed.

### Flash (error strip)
- **The system's error voice.** A quiet red strip under the topbar
  (`margin: 10px 16px 0`, 6px 10px padding, 6px radius): 0.4-alpha red border
  (rgba(229,83,75,0.4)), 0.12-alpha red wash background (rgba(229,83,75,0.12)),
  muted red text (#f0827b) at 12.5px.
- **Behavior:** patched over SSE by server actions when a board action fails;
  hidden entirely when there is nothing to say. No icons, no dismiss button,
  no toast animation — it appears, states the failure, and clears.

### Navigation
- **Rail:** 220px, rail surface, 14px 10px padding. Workspace row: 18px
  orange-gradient rounded mark (5px radius, #f0883e → #c96a25 at 135deg) with
  an ember-ink 10px/800 letter, 600-weight name. Links: 13px/500 text-2 with
  a 14px drawn icon, 6px radius; hover = hover surface + primary text; active
  = raised surface + primary text.
- **Breadcrumbs:** 500-weight text-2 links, `›` separator in text-3, current
  page in primary text.

### Avatars (signature)
- 18px circles with 8.5px/700 avatar-ink initials on a per-member pastel hue
  (`av-0`..`av-3`), assigned server-side from a name hash so the color never
  shifts between renders, surfaces, or sessions. Appear on cards
  (right-aligned), comments, and the assignee prop.

### Properties Panel (signature)
- 280px sidebar under an uppercase 11px "Properties" label; each prop is a
  72px fixed-width text-3 key beside a 500-weight text-2 value row (min-height
  24px, 12px stacked gap). Editable props embed a small select (12.5px);
  read-only values render as icon + text.

## Do's and Don'ts

### Do:
- **Do** route every color through the `:root` custom properties in theme.css;
  the tokens are the design system, and SSE-morphed fragments must inherit them.
- **Do** keep ids stable and semantic on any element inside a morph boundary
  (`#board`, `#issue-detail`, `#comments`).
- **Do** express state with the drawn circle icons and priority with the bar
  icons — the icon carries the hue, the adjacent text stays gray.
- **Do** surface failures through the flash strip's single red voice; hide it
  when there is nothing to report.
- **Do** use `font-variant-numeric: tabular-nums` for keys and counts.
- **Do** step one rung up the tonal ladder for hover, and pair every surface
  with a white-alpha hairline.

### Don't:
- **Don't** spend orange on anything except interactive affordances and the
  urgent priority icon.
- **Don't** use red outside the flash strip — no inline error text, no red
  icons, no second error treatment.
- **Don't** introduce a second typeface, type above 19px, or uppercase outside
  the sidebar section-label register.
- **Don't** add drop shadows beyond the card whisper, or invent new dark grays
  off the ladder.
- **Don't** use icon fonts, emoji glyphs, or imported icon packs; draw new
  icons into the shared sprite. One exception: the per-issue emoji, a marker
  the author picks for one issue. System iconography — state, priority,
  navigation — must inherit `currentColor` for the Icon-Carries-Color Rule and
  stay legible at 14px next to hairline strokes, and emoji are full-colour
  bitmaps that ignore the palette and redraw themselves per platform. A
  personal marker is the opposite category: arbitrary colour is the whole
  point of it, and it spends nothing from the Ember Budget because it is not
  an affordance. The exception covers that field and nothing else.
- **Don't** add a light theme or theme switching; the world is dark-only.

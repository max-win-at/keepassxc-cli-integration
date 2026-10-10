# docs/ static website — KeePassXC-styled landing page

**Date:** 2026-10-10
**Status:** Approved design, pending implementation plan
**Repo branch:** `docs/website`

## 1. Purpose

A standalone, build-less static website at `docs/index.html` that presents the
`kpxc-agent` project (KeePassXC secrets for AI agents) inside a faithful mock of
the KeePassXC application window, centered on the page. It must work when served
statically or opened directly — no build step, no server-side code.

## 2. Goals

- Instant visual recognition as the KeePassXC application window (simplified
  chrome: title bar, toolbar, Groups sidebar; content in a single pane).
- Convey the project's purpose in a hero box.
- Show the three install methods from the README: skills.sh (`npx skills add …`),
  agentskill.sh (`/learn @max-win-at/keepassxc-secrets`), standalone
  (`git clone` + symlink + `kpxc-agent doctor`).
- Show badges: skills.sh, agentskill.sh, GitHub repo, forks, stars.
- Link to https://max-w.in.
- Theme: follow the OS `prefers-color-scheme` by default, with a manual
  light/dark toggle in the window chrome, persisted across visits.

## 3. Non-goals

- No build pipeline, bundler, or package manager (Tailwind via Play CDN,
  Alpine via CDN ES module).
- No content beyond what the README describes (no blog, no docs sub-pages).
- No faithful menu bar, database tab bar, entry list table, preview pane, or
  status bar — simplified chrome only, per the approved decision.
- No dark-theme screenshots or raster assets; all icons are inline SVG.

## 4. Stack (constraints)

- **HTML + ES modules** — one inline `<script type="module">` for behavior.
- **Alpine.js** — from CDN (`https://cdn.jsdelivr.net/npm/alpinejs@3.x/dist/module.esm.js`
  or equivalent), used for: theme store, install-tab switching, toolbar search
  filtering of install cards, sidebar navigation state, copy-button feedback.
- **Tailwind CSS** — via Play CDN (`https://cdn.tailwindcss.com`) with an inline
  `tailwind.config` defining the KeePassXC palette and `darkMode: 'class'`.
- No other libraries. No framework. Single file.

## 5. File layout

```
docs/
└── index.html      # the entire site
```

One file, self-contained. No `docs/assets/` unless a later need arises.

## 6. Visual design

### 6.1 KeePassXC palette (from `src/gui/styles/light/LightStyle.cpp` and `dark/DarkStyle.cpp`)

| Role | Light | Dark |
|---|---|---|
| Window | `#F7F7F7` | `#3B3B3D` |
| Base (content panes, toolbar) | `#F9F9F9` | `#27272A` |
| Alternate row | `#ECF3E8` | `#2C2C30` |
| Highlight (selection, accents) | `#507F1F` | `#2D532D` |
| Highlight hover variant | `#568821` | `#2E582E` |
| Link | `#4B7B19` | `#68B668` |
| Text | `#1D1D20` | `#CACBCE` |
| Placeholder text | `#71727D` | `#7D7D82` |
| Button | `#D4D5DD` | `#28282B` |
| Border / mid | `#C9C9CF` | `#2F2F32` |
| Border / dark | `#BBBBC2` | `#202022` |

Tailwind config maps these as `kpxc-window`, `kpxc-base`, `kpxc-alt`,
`kpxc-green`, `kpxc-green-hi`, `kpxc-link`, `kpxc-text`, `kpxc-placeholder`,
`kpxc-button`, `kpxc-mid`, `kpxc-border`.

### 6.2 Page backdrop

Neutral dark gradient (dark palette tones, e.g. `#27272A → #202022`), constant
across themes so the window reads as an app floating on a desktop. Window is
centered with `max-w-5xl`, 1px border (`#BBBBC2` light / `#202022` dark),
rounded corners, drop shadow.

### 6.3 Window chrome (simplified)

1. **Title bar** (`#F7F7F7` / `#3B3B3D`): small KeePassXC-style shield-with-key
   inline SVG, title "kpxc-agent — KeePassXC secrets for AI agents", a
   decorative database tab chip ("vault.kdbx"), a lock icon, a light/dark
   toggle **switch** (sun and moon icons; knob position and active icon are
   plain CSS keyed off the `dark` class, so the switch renders the
   system-resolved theme before Alpine loads), and inert window buttons
   (minimize / maximize / close) on the right.
2. **Toolbar** (`#F9F9F9` / `#27272A`, 1px bottom border): the five project
   badges (skills.sh, agentskill.sh, GitHub repo, stars, forks) as linked
   images in a row. No toolbar buttons, no search input.
3. **Body**: left sidebar + content pane, 1px divider between them.

### 6.4 Sidebar ("Groups")

KeePassXC group-tree look: header "Groups", tree rows with folder glyphs,
clickable items — *Overview*, *Install*, *About*. Clicking
scrolls the content pane to the section and marks the row selected
(`#507F1F` background, white text). Uses the alternate-row green
(`#ECF3E8`) for hover, like KeePassXC's group view.

### 6.5 Content pane

- **Overview (hero)** — project purpose condensed from the README: what it is,
  why it is different (secrets never reach logs/transcripts/dotfiles; lives in
  process memory for one command), plus the signature one-liner
  `pw=$(kpxc-agent get-logins https://host.example --field password)` in a
  code block with a copy button, and the "pair once, then unattended" hook.
- **Install** — three Alpine-driven tabs in the entry-list style:
  1. **skills.sh (Vercel)** — `npx skills add max-win-at/keepassxc-cli-integration --skill keepassxc-secrets`
  2. **agentskill.sh** — `/learn @max-win-at/keepassxc-secrets`
     (with the note: no `/learn` yet? `npx @agentskill.sh/cli@latest setup`)
  3. **Standalone CLI** — `git clone … && ln -s … && kpxc-agent doctor`
  Each tab shows a description from the README and a copyable code block.
  Prerequisites line (jq, python3, libsodium, KeePassXC with Browser
  Integration) included under the tabs.
- **Badges & Links** — shown in the toolbar (see §6.3); the badges from the README:
  - skills.sh: `https://skills.sh/b/max-win-at/keepassxc-cli-integration`
  - agentskill.sh: `https://img.shields.io/badge/agentskill.sh-%40max--win--at%2Fkeepassxc--secrets-181717`
  - GitHub stars: `https://img.shields.io/github/stars/max-win-at/keepassxc-cli-integration`
  - GitHub forks: `https://img.shields.io/github/forks/max-win-at/keepassxc-cli-integration`
  - GitHub repo badge:
    `https://img.shields.io/badge/github-max--win--at%2Fkeepassxc--cli--integration-181717`,
    linking to `https://github.com/max-win-at/keepassxc-cli-integration`
- **About / footer** — link to https://max-w.in, MIT license link, and the
  "Encrypted like the browser extension" one-line security hook.

## 7. Behavior (ES module + Alpine)

- **Theme store** (Alpine `Alpine.store('theme')`): `mode: 'light' | 'dark'`,
  resolved on load from `localStorage['kpxc-theme']` else
  `prefers-color-scheme`; toggle writes `localStorage` and flips the `dark`
  class on `<html>`; a `matchMedia` listener follows OS changes unless the user
  has chosen explicitly. Applies before first paint via a tiny inline script to
  avoid flash.
- **Install tabs** — `x-data` component; default tab: skills.sh.
- **Copy buttons** — `navigator.clipboard.writeText`, with "Copied" feedback
  state for ~1.5 s.
- **Sidebar nav** — scroll-into-view plus active state.

## 8. Accessibility & details

- `lang="en"`, descriptive `<title>`, meta description.
- Inert window buttons are `aria-hidden`; real controls are keyboard reachable.
- Copy buttons announce state with `aria-live="polite"`.
- No secrets, no tracking, no external fonts (system font stack, matching
  KeePassXC's native look).

## 9. Verification

- Serve `docs/` with `python3 -m http.server` and curl-check `index.html` and
  CDN references resolve (HTTP 200).
- Validate the HTML parses (e.g. `python3 -c "html.parser"` smoke check).
- Manual browser check recommended (no screenshot capability in this
  environment): theme toggle, search filter, tabs, copy buttons, sidebar nav,
  badges render.

## 10. Out of scope for this spec

- GitHub Pages / Vercel deployment configuration.
- Any change to README or other repo files.

# docs/ KeePassXC-styled Static Website — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-file static site at `docs/index.html` that presents kpxc-agent inside a simplified KeePassXC application-window mock, with theme toggle, searchable install tabs, badges, and the max-w.in link.

**Architecture:** One self-contained HTML file. Tailwind Play CDN + inline config supplies styling from the KeePassXC palette; Alpine.js from CDN drives a theme store, a search store, install tabs, sidebar nav, and copy buttons. A synchronous pre-paint script applies the theme class before first render.

**Tech Stack:** ES modules, Alpine.js 3, Tailwind CSS 3 (Play CDN). No build step.

**Spec:** `docs/superpowers/specs/2026-10-10-docs-website-design.md`

## Global Constraints

- Exactly one site file: `docs/index.html`. No `docs/assets/`.
- Tailwind via `<script src="https://cdn.tailwindcss.com"></script>`, then inline `tailwind.config` (Play CDN reads it after load) with `darkMode: 'class'` and colors: `kpxc-window #F7F7F7/#3B3B3D`, `kpxc-base #F9F9F9/#27272A`, `kpxc-alt #ECF3E8/#2C2C30`, `kpxc-green #507F1F/#2D532D`, `kpxc-green-hi #568821/#2E582E`, `kpxc-link #4B7B19/#68B668`, `kpxc-text #1D1D20/#CACBCE`, `kpxc-placeholder #71727D/#7D7D82`, `kpxc-button #D4D5DD/#28282B`, `kpxc-mid #C9C9CF/#2F2F32`, `kpxc-border #BBBBC2/#202022` (light/dark).
- Alpine via `<script type="module">` importing `https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/module.esm.js`; register stores, then `Alpine.start()`.
- Theme persistence: `localStorage['kpxc-theme']` (`'light'|'dark'`), all localStorage access wrapped in try/catch (private-mode browsers throw).
- All shell commands run with the `rtk` prefix (repo AGENTS.md). Commits: conventional type, e.g. `feat(docs): ...`.
- System font stack only; no external fonts; all icons inline SVG.
- Site copy comes from `README.md` — commands verbatim from the spec §6.5.

## Review Focus

- **Theme flash on load** — a dark-mode visitor must not see a light flash; pre-paint script is the first thing in `<head>` and runs synchronously (Task 1).
- **localStorage unavailable** (Safari private mode) — must fall back to `prefers-color-scheme` silently, never throw (Tasks 1–2).
- **Clipboard API unavailable** (non-secure context, e.g. plain `file://`) — copy falls back to a temporary textarea + `execCommand('copy')`; button still shows "Copied" or an error state (Task 4).
- **OS theme changes while the page is open** — `matchMedia('(prefers-color-scheme: dark)')` change event updates the class unless the user toggled explicitly (Task 2).
- **Search matches nothing** — install section shows an explicit empty state, not a blank pane (Task 4).

---

### Task 1: Scaffold, head, pre-paint theme script, backdrop + window shell

**Files:**
- Create: `docs/index.html`

**Interfaces:**
- Produces: `<html>` whose class list carries `dark` when dark; backdrop `<div id="backdrop">`; window shell `<div id="kpxc-window">`; the inline `tailwind.config` object with the palette above (all later tasks style via these classes); the pre-paint script reading `localStorage['kpxc-theme']`.

- [ ] **Step 1: Confirm the deliverable is absent**

Run: `rtk ls docs`
Expected: only `superpowers/` — no `index.html`.

- [ ] **Step 2: Create `docs/index.html` with head, pre-paint script, backdrop, empty window shell**

Head order (order is load-bearing): 1) pre-paint `<script>` — first element in `<head>`, synchronous, reads `localStorage['kpxc-theme']` in try/catch, falls back to `matchMedia('(prefers-color-scheme: dark)').matches`, adds `dark` to `document.documentElement` when dark; 2) `<title>kpxc-agent — KeePassXC secrets for AI agents</title>`; 3) meta description (one sentence from spec §1); 4) Tailwind Play CDN script; 5) inline `tailwind.config` per Global Constraints. Body: `#backdrop` — full-screen, dark gradient `#27272A → #202022`, grid place-items center; `#kpxc-window` — `max-w-5xl w-full` rounded window, 1px `kpxc-border` border, drop shadow, empty.

- [ ] **Step 3: Verify parse and markers**

Run: `rtk proxy python3 -c "from html.parser import HTMLParser; p=HTMLParser(); p.feed(open('docs/index.html').read())" && rtk grep 'tailwind.config' docs/index.html && rtk grep 'kpxc-window' docs/index.html`
Expected: no traceback; both greps match.

- [ ] **Step 4: Commit**

```bash
rtk git add docs/index.html && rtk git commit -m "feat(docs): scaffold KeePassXC-styled site shell with theme pre-paint"
```

### Task 2: Title bar, toolbar, Alpine theme + search stores

**Files:**
- Modify: `docs/index.html` (inside `#kpxc-window` and the module script)

**Interfaces:**
- Consumes: `#kpxc-window`, `tailwind.config` palette.
- Produces: `Alpine.store('theme') = { mode: 'light'|'dark', explicit: boolean, toggle(): void }` (module init reads the pre-paint result off `<html>`; `toggle()` writes `localStorage['kpxc-theme']` in try/catch and flips the class); `Alpine.store('search') = { q: '' }`; title-bar button `#theme-toggle`; toolbar input `#search-input` bound with `x-model="search.q"`; module script also registers a `matchMedia` listener updating the theme when `explicit` is false.

- [ ] **Step 1: Confirm markers absent**

Run: `rtk grep 'theme-toggle' docs/index.html`
Expected: no match.

- [ ] **Step 2: Build the title bar and toolbar, register stores**

Title bar (`kpxc-window` background, bottom border): KeePassXC-style shield-with-key inline SVG, title text, inert `vault.kdbx` tab chip and lock icon, `#theme-toggle` button (sun/moon SVG, `@click="theme.toggle()"`, `aria-label="Toggle theme"`), inert minimize/maximize/close SVGs marked `aria-hidden`. Toolbar (`kpxc-base`, bottom border): inert inline SVG icon groups (Database, Entries, Entry Data, Tools), then `#search-input` with `kpxc-placeholder` placeholder `Search…`. Module script: import Alpine, register `theme` and `search` stores per Interfaces (matchMedia listener from Review Focus), `Alpine.start()`.

- [ ] **Step 3: Verify parse and markers**

Run: `rtk proxy python3 -c "from html.parser import HTMLParser; p=HTMLParser(); p.feed(open('docs/index.html').read())" && rtk grep 'theme-toggle' docs/index.html && rtk grep 'search-input' docs/index.html && rtk grep "Alpine.start" docs/index.html`
Expected: no traceback; all greps match.

- [ ] **Step 4: Commit**

```bash
rtk git add docs/index.html && rtk git commit -m "feat(docs): add window chrome, theme toggle and search stores"
```

### Task 3: Groups sidebar + Overview hero

**Files:**
- Modify: `docs/index.html`

**Interfaces:**
- Consumes: `Alpine.store('theme')`.
- Produces: `Alpine.store('nav') = { active: 'overview' }`; section anchors `id="section-overview"`, `id="section-install"`, `id="section-badges"`, `id="section-about"`; helper `goSection(id)` in the module script (sets `nav.active`, `scrollIntoView({behavior:'smooth'})` on the section element); async `copy(text, btnId)` in the module script — `navigator.clipboard.writeText`, falling back to a temporary textarea + `execCommand('copy')` (Review Focus), and sets `nav.copied = btnId` for 1.5 s; Content pane wrapper `<div id="content-pane">`.

- [ ] **Step 1: Confirm markers absent**

Run: `rtk grep 'section-overview' docs/index.html`
Expected: no match.

- [ ] **Step 2: Build sidebar and hero**

Sidebar (`kpxc-base` background, right border, `w-56`): header "Groups", folder-glyph rows for *Overview, Install, Badges & Links, About* — each `@click="goSection('<id>')"`; active row `kpxc-green` background + white text; hover `kpxc-alt`. `#content-pane`: single scroll container. Hero (`id="section-overview"`): project purpose copy from README (agent asks vault, vault answers, secret lives in process memory for one command; never reaches log/transcript/dotfile), the signature code block `pw=$(kpxc-agent get-logins https://host.example --field password)` with a working copy button (`@click="copy('…','hero')"`), and the "pair once, then unattended" hook line.

- [ ] **Step 3: Verify parse and markers**

Run: `rtk proxy python3 -c "from html.parser import HTMLParser; p=HTMLParser(); p.feed(open('docs/index.html').read())" && rtk grep 'section-install' docs/index.html && rtk grep 'goSection' docs/index.html`
Expected: no traceback; all greps match.

- [ ] **Step 4: Commit**

```bash
rtk git add docs/index.html && rtk git commit -m "feat(docs): add groups sidebar and overview hero"
```

### Task 4: Install tabs, search filter, copy buttons

**Files:**
- Modify: `docs/index.html`

**Interfaces:**
- Consumes: `Alpine.store('search').q`, section `id="section-install"`, `#content-pane`, `copy(text, btnId)` from Task 3.
- Produces: `x-data="installTabs()"` component on the install section with state `{ tab: 'skills' }`; `matches(tab, q)` predicate used by the filter; copy buttons announce via `aria-live="polite"` label spans bound to `nav.copied`.

- [ ] **Step 1: Confirm markers absent**

Run: `rtk grep 'installTabs' docs/index.html`
Expected: no match.

- [ ] **Step 2: Build the install section**

Tab row (entry-list style, `kpxc-alt` for the selected tab) with three tabs: `skills` (skills.sh (Vercel)), `agentskill` (agentskill.sh), `standalone` (Standalone CLI). Each panel: README description + `<pre><code>` block with the exact commands from spec §6.5 (`npx skills add max-win-at/keepassxc-cli-integration --skill keepassxc-secrets` · `/learn @max-win-at/keepassxc-secrets` + the `npx @agentskill.sh/cli@latest setup` note · `git clone` + `ln -s` + `kpxc-agent doctor`) + copy button. Filtering: a panel hides when its text (label + description + command, lowercased) does not contain `search.q.trim().toLowerCase()`; when no tab matches, show "No install method matches your search." Prerequisites line under the tabs (jq, python3, libsodium, KeePassXC with Browser Integration, `kpxc-agent doctor`).

- [ ] **Step 3: Verify parse, markers, and copy text verbatim**

Run: `rtk proxy python3 -c "from html.parser import HTMLParser; p=HTMLParser(); p.feed(open('docs/index.html').read())" && rtk grep 'installTabs' docs/index.html && rtk grep 'No install method matches' docs/index.html && rtk grep 'npx skills add max-win-at/keepassxc-cli-integration --skill keepassxc-secrets' docs/index.html`
Expected: no traceback; all greps match.

- [ ] **Step 4: Commit**

```bash
rtk git add docs/index.html && rtk git commit -m "feat(docs): add searchable install tabs with clipboard fallback"
```

### Task 5: Badges, about/footer, end-to-end verification

**Files:**
- Modify: `docs/index.html`

**Interfaces:**
- Consumes: `id="section-badges"`, `id="section-about"` anchors.
- Produces: badge images per spec §6.5; footer with https://max-w.in link and MIT.

- [ ] **Step 1: Confirm markers absent**

Run: `rtk grep 'section-badges' docs/index.html`
Expected: no match.

- [ ] **Step 2: Build badges and about**

Badges section: linked `<img>` badges in a row — skills.sh (`https://skills.sh/b/max-win-at/keepassxc-cli-integration`), agentskill.sh (`https://img.shields.io/badge/agentskill.sh-%40max--win--at%2Fkeepassxc--secrets-181717` → `https://agentskill.sh/@max-win-at/keepassxc-secrets`), GitHub repo (`https://img.shields.io/badge/github-max--win--at%2Fkeepassxc--cli--integration-181717`), stars (`https://img.shields.io/github/stars/max-win-at/keepassxc-cli-integration`), forks (`https://img.shields.io/github/forks/max-win-at/keepassxc-cli-integration`) — all repo links to `https://github.com/max-win-at/keepassxc-cli-integration`. About section: "Encrypted like the browser extension" hook, link to https://max-w.in, MIT license mention.

- [ ] **Step 3: End-to-end verification**

Run: `rtk proxy python3 -m http.server 8123 --directory docs &` then `rtk curl -s -o /dev/null -w '%{http_code}' http://localhost:8123/index.html`, then curl each of the five badge URLs and both CDN URLs (`https://cdn.tailwindcss.com`, `https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/module.esm.js`) for HTTP 200, then parse check, then stop the server.
Expected: all HTTP 200; no parse traceback.

- [ ] **Step 4: Commit**

```bash
rtk git add docs/index.html && rtk git commit -m "feat(docs): add badges, about section and max-w.in link"
```

- [ ] **Step 5: Manual browser checklist (report, not gate)**

Theme toggle + persistence across reload; OS-scheme default; search filter + empty state; three tabs + copy buttons; sidebar nav highlight; badges render. Note any findings for the user.

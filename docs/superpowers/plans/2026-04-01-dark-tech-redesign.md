# Dark Tech Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refonte complète du design de l'app "Veille IA Technique" vers un dark mode élégant technophile avec effets CSS riches (grille animée, scan lines, glow, animations d'entrée).

**Architecture:** CSS-only redesign. Les variables CSS existantes sont remplacées par la nouvelle palette dark. Les animations (grille, scan line, glow, entrées séquentielles) sont toutes en CSS `@keyframes`. Le seul ajout JS est un `useEffect` pour tracker le curseur et animer le gradient radial de fond.

**Tech Stack:** React 19, TypeScript, CSS (aucune dépendance ajoutée), JetBrains Mono via Google Fonts CDN.

---

### Task 1: Import JetBrains Mono font

**Files:**
- Modify: `frontend/index.html:4` (add font link in head)

- [ ] **Step 1: Add Google Fonts link to index.html**

Replace the current `<head>` content with:

```html
<head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:ital,wght@0,400;0,500;0,600;0,700;1,400&display=swap" rel="stylesheet" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Veille IA Technique</title>
</head>
```

- [ ] **Step 2: Verify dev server loads the font**

Run: `cd frontend && npm run dev`
Expected: App loads without errors, JetBrains Mono font available in browser DevTools.

- [ ] **Step 3: Commit**

```bash
git add frontend/index.html
git commit -m "feat: add JetBrains Mono font import and update page title"
```

---

### Task 2: Rewrite index.css — Global dark theme foundation

**Files:**
- Modify: `frontend/src/index.css` (full rewrite)

- [ ] **Step 1: Replace index.css with dark theme globals**

```css
:root {
  --bg-primary: #0a0a0f;
  --bg-secondary: #12121a;
  --bg-tertiary: #1a1a2e;
  --border: rgba(59, 130, 246, 0.15);
  --border-glow: rgba(6, 182, 212, 0.3);
  --text-primary: #e2e8f0;
  --text-secondary: #64748b;
  --accent: #3b82f6;
  --accent-cyan: #06b6d4;
  --glow-blue: rgba(59, 130, 246, 0.4);
  --glow-cyan: rgba(6, 182, 212, 0.3);
  --danger: #ef4444;
  --font: 'JetBrains Mono', 'Fira Code', ui-monospace, monospace;

  font-family: var(--font);
  font-size: 15px;
  line-height: 1.6;
  color: var(--text-primary);
  background: var(--bg-primary);
  font-synthesis: none;
  text-rendering: optimizeLegibility;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

body {
  margin: 0;
  background-color: var(--bg-primary);
  color: var(--text-primary);
  background-image:
    linear-gradient(rgba(59, 130, 246, 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(59, 130, 246, 0.03) 1px, transparent 1px),
    radial-gradient(
      ellipse at var(--mouse-x, 50%) var(--mouse-y, 50%),
      rgba(6, 182, 212, 0.06) 0%,
      transparent 60%
    );
  background-size: 40px 40px, 40px 40px, 100% 100%;
  background-attachment: fixed;
  min-height: 100vh;
}

body::after {
  content: '';
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: linear-gradient(
    transparent 0%,
    rgba(6, 182, 212, 0.03) 50%,
    transparent 100%
  );
  background-size: 100% 8px;
  animation: scanline 8s linear infinite;
  pointer-events: none;
  z-index: 9999;
}

@keyframes scanline {
  0% {
    transform: translateY(-100%);
  }
  100% {
    transform: translateY(100vh);
  }
}

#root {
  max-width: 100%;
  margin: 0 auto;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

h1,
h2,
h3,
h4,
h5,
h6 {
  font-family: var(--font);
  font-weight: 600;
  color: var(--text-primary);
}

h1 {
  font-size: 1.8rem;
  letter-spacing: -0.02em;
}

h2 {
  font-size: 1.3rem;
  letter-spacing: -0.01em;
}

h3 {
  font-size: 1.05rem;
}

p {
  margin: 0;
}

a {
  color: var(--accent-cyan);
  text-decoration: none;
}

a:hover {
  text-decoration: underline;
  text-shadow: 0 0 8px var(--glow-cyan);
}

code {
  font-family: var(--font);
  font-size: 0.85em;
  padding: 0.2em 0.5em;
  border-radius: 4px;
  background: var(--bg-primary);
  color: var(--accent-cyan);
  border: 1px solid var(--border);
}

@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes glowPulse {
  0%,
  100% {
    box-shadow: 0 0 8px var(--glow-cyan);
  }
  50% {
    box-shadow: 0 0 16px var(--glow-cyan), 0 0 24px rgba(6, 182, 212, 0.15);
  }
}

@keyframes iconGlow {
  0%,
  100% {
    filter: drop-shadow(0 0 4px var(--glow-cyan));
  }
  50% {
    filter: drop-shadow(0 0 10px var(--glow-cyan));
  }
}
```

- [ ] **Step 2: Verify the app renders with dark background and grid pattern**

Run: `cd frontend && npm run dev`
Expected: Dark background with subtle blue grid lines, scan line effect visible, text is light colored.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/index.css
git commit -m "feat: rewrite index.css with dark theme globals, grid background, scan line, and animation keyframes"
```

---

### Task 3: Add mouse tracking for gradient radial in App.tsx

**Files:**
- Modify: `frontend/src/App.tsx:89` (add useEffect after existing ones)

- [ ] **Step 1: Add mouse tracking useEffect**

Add the following `useEffect` block after the existing `useEffect` blocks (after line 114) in `App.tsx`:

```tsx
useEffect(() => {
  const handleMouseMove = (event: MouseEvent) => {
    document.body.style.setProperty('--mouse-x', `${event.clientX}px`);
    document.body.style.setProperty('--mouse-y', `${event.clientY}px`);
  };
  window.addEventListener('mousemove', handleMouseMove);
  return () => window.removeEventListener('mousemove', handleMouseMove);
}, []);
```

- [ ] **Step 2: Update Bot icon color in the topbar brand**

In the return JSX, change the Bot icon color from `#2563eb` to `var(--accent-cyan)`:

```tsx
<Bot size={28} color="#06b6d4" />
```

- [ ] **Step 3: Verify gradient follows cursor**

Run: `cd frontend && npm run dev`
Expected: Moving the mouse across the page shows a subtle cyan radial gradient following the cursor on the background grid.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat: add mouse-tracking gradient and update brand icon color"
```

---

### Task 4: Rewrite App.css — Topbar & buttons

**Files:**
- Modify: `frontend/src/App.css:1-62` (topbar section)
- Modify: `frontend/src/App.css:285-310` (buttons section)

- [ ] **Step 1: Replace the topbar and button base styles**

Replace everything from line 1 (`:root`) through line 62 (end of `.topbar-link.active`) and lines 285-310 (button styles) with:

```css
/* ===== TOPBAR ===== */

.app-shell {
  max-width: 1440px;
  margin: 0 auto;
  padding: 1.5rem 2rem 2rem;
}

.topbar {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 1rem;
  padding: 1rem 1.25rem;
  margin-bottom: 1.5rem;
  border: 1px solid var(--border);
  border-bottom: 1px solid var(--border-glow);
  border-radius: 0;
  background: var(--bg-secondary);
}

.topbar-brand {
  display: flex;
  gap: 0.75rem;
  align-items: center;
}

.topbar-brand strong {
  display: block;
  font-size: 1.15rem;
  color: var(--text-primary);
  text-shadow: 0 0 12px var(--glow-cyan);
}

.topbar-brand span {
  display: block;
  font-size: 0.8rem;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.topbar-menu {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 0.35rem;
}

.topbar-link {
  position: relative;
  padding-bottom: 0.6rem;
  border: none;
  background: transparent;
  color: var(--text-secondary);
}

.topbar-link:hover {
  color: var(--accent-cyan);
  text-shadow: 0 0 8px var(--glow-cyan);
  background: transparent;
}

.topbar-link.active {
  color: var(--text-primary);
  background: transparent;
  border: none;
  border-bottom: 2px solid var(--accent-cyan);
}

/* ===== BUTTONS ===== */

button {
  padding: 0.5rem 1rem;
  border-radius: 4px;
  border: 1px solid var(--border);
  background-color: var(--bg-secondary);
  color: var(--text-primary);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-family: var(--font);
  font-weight: 500;
  font-size: 0.85rem;
  transition: all 0.2s ease;
}

button:hover {
  border-color: var(--border-glow);
  box-shadow: 0 0 12px var(--glow-blue);
}

button.primary {
  background: linear-gradient(135deg, var(--accent), var(--accent-cyan));
  color: white;
  border-color: transparent;
  box-shadow: 0 0 20px var(--glow-blue);
}

button.primary:hover {
  box-shadow: 0 0 30px var(--glow-blue), 0 0 60px rgba(59, 130, 246, 0.2);
}

button.danger {
  color: var(--danger);
}

button.danger:hover {
  border-color: rgba(239, 68, 68, 0.3);
  box-shadow: 0 0 12px rgba(239, 68, 68, 0.2);
}

.icon-button {
  padding: 0.35rem;
  border-radius: 4px;
  background: transparent;
  border: 1px solid transparent;
}

.icon-button:hover {
  border-color: var(--border-glow);
  box-shadow: 0 0 8px var(--glow-cyan);
}

.topbar-actions button.primary .animate-spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
```

- [ ] **Step 2: Verify topbar renders correctly**

Run: `cd frontend && npm run dev`
Expected: Dark topbar with cyan bottom border, brand text with glow, nav links highlight in cyan, primary button has blue-to-cyan gradient with glow.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.css
git commit -m "feat: rewrite topbar and button styles for dark tech theme"
```

---

### Task 5: Rewrite App.css — Dashboard

**Files:**
- Modify: `frontend/src/App.css` (dashboard section, replace lines 66-144)

- [ ] **Step 1: Replace dashboard styles**

Replace the dashboard-related CSS (from `.main-area` through `.project-tag`) with:

```css
/* ===== LAYOUT ===== */

.main-area,
.dashboard-view,
.notes-view,
.searches-view,
.reports-view {
  min-width: 0;
}

/* ===== DASHBOARD ===== */

.dashboard-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1rem;
  margin-bottom: 1rem;
}

.dashboard-card {
  padding: 1.25rem;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-secondary);
  transition: all 0.3s ease;
  animation: fadeInUp 0.4s ease both;
}

.dashboard-card:nth-child(1) { animation-delay: 0s; }
.dashboard-card:nth-child(2) { animation-delay: 0.05s; }
.dashboard-card:nth-child(3) { animation-delay: 0.1s; }
.dashboard-card:nth-child(4) { animation-delay: 0.15s; }

.dashboard-card:hover {
  border-color: var(--border-glow);
  box-shadow: 0 0 16px var(--glow-blue);
}

.dashboard-card-label {
  display: block;
  font-size: 0.72rem;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.12em;
  margin-bottom: 0.5rem;
}

.dashboard-card strong {
  font-size: 2rem;
  color: var(--accent-cyan);
  text-shadow: 0 0 12px var(--glow-cyan);
}

.dashboard-panels {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 1rem;
}

.dashboard-panel {
  padding: 1.25rem;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-secondary);
  animation: fadeInUp 0.4s ease both;
  animation-delay: 0.2s;
}

.dashboard-latest-title {
  font-weight: 700;
  margin-bottom: 0.25rem;
  color: var(--text-primary);
}

.dashboard-latest-meta {
  color: var(--text-secondary);
  margin-bottom: 1rem;
  font-size: 0.85rem;
}

.dashboard-link-button {
  width: fit-content;
  border-color: var(--accent-cyan);
  color: var(--accent-cyan);
  background: transparent;
}

.dashboard-link-button:hover {
  background: rgba(6, 182, 212, 0.1);
  box-shadow: 0 0 12px var(--glow-cyan);
}

.tag-cloud {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.project-tag {
  padding: 0.35rem 0.7rem;
  border-radius: 4px;
  background: rgba(6, 182, 212, 0.1);
  border: 1px solid rgba(6, 182, 212, 0.3);
  color: var(--accent-cyan);
  font-size: 0.8rem;
  font-weight: 600;
  transition: all 0.2s ease;
}

.project-tag:hover {
  box-shadow: 0 0 10px var(--glow-cyan);
  background: rgba(6, 182, 212, 0.15);
}
```

- [ ] **Step 2: Verify dashboard renders correctly**

Run: `cd frontend && npm run dev`
Expected: Dark KPI cards with cyan numbers that glow, tags with cyan borders, sequential fade-in animation on cards.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.css
git commit -m "feat: rewrite dashboard styles for dark tech theme"
```

---

### Task 6: Rewrite App.css — Reports view (sidebar + content + notes)

**Files:**
- Modify: `frontend/src/App.css` (reports section, replace the reports-view through report-notes styles)

- [ ] **Step 1: Replace reports view styles**

Replace all reports-related CSS (from `.reports-view` through `.notes-empty`) with:

```css
/* ===== REPORTS VIEW ===== */

.reports-view {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 1.25rem;
}

.reports-view.collapsed {
  grid-template-columns: 1fr;
}

.reports-history-panel {
  padding: 1.25rem;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-secondary);
}

.report-content {
  padding: 1.25rem;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-secondary);
}

.reports-panel-header,
.report-content-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.reports-panel-header {
  margin-bottom: 1rem;
}

.report-content-toolbar {
  margin-bottom: 1rem;
}

.panel-subtitle {
  margin: 0.25rem 0 0;
  font-size: 0.78rem;
  color: var(--text-secondary);
}

.history-toggle-button {
  width: fit-content;
  background: transparent;
}

.report-group {
  margin-top: 1rem;
}

.report-group-title {
  font-size: 0.7rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--text-secondary);
  margin-bottom: 0.5rem;
}

.report-item {
  padding: 0.85rem;
  cursor: pointer;
  border-radius: 4px;
  margin-bottom: 0.35rem;
  transition: all 0.2s ease;
  border-left: 2px solid transparent;
  animation: fadeInUp 0.3s ease both;
}

.report-item:nth-child(1) { animation-delay: 0s; }
.report-item:nth-child(2) { animation-delay: 0.05s; }
.report-item:nth-child(3) { animation-delay: 0.1s; }
.report-item:nth-child(4) { animation-delay: 0.15s; }
.report-item:nth-child(5) { animation-delay: 0.2s; }

.report-item:hover {
  background-color: var(--bg-tertiary);
}

.report-item.active {
  background-color: var(--bg-tertiary);
  border-left-color: var(--accent-cyan);
}

.report-item-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.report-item-main {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  min-width: 0;
  color: var(--text-secondary);
}

.report-item-text {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.report-item-title {
  font-size: 0.88rem;
  font-weight: 600;
  color: var(--text-primary);
}

.report-item-meta {
  font-size: 0.72rem;
  color: var(--text-secondary);
  letter-spacing: 0.04em;
}

.report-item-actions {
  position: relative;
}

.report-item-menu {
  position: absolute;
  top: calc(100% + 0.35rem);
  right: 0;
  min-width: 180px;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 0.45rem;
  border: 1px solid var(--border-glow);
  border-radius: 4px;
  background: var(--bg-secondary);
  box-shadow: 0 0 20px var(--glow-blue);
  z-index: 5;
}

.report-item-menu button {
  width: 100%;
  justify-content: flex-start;
  background: transparent;
}

.report-item-menu button:hover {
  background: var(--bg-tertiary);
}

/* ===== ACTIONS BAR ===== */

.actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1.25rem;
}

.action-buttons {
  display: flex;
  gap: 0.75rem;
}

/* ===== SUMMARY CARD ===== */

.summary-card {
  margin-bottom: 1.25rem;
  padding: 1rem 1.1rem;
  border: 1px solid rgba(59, 130, 246, 0.2);
  border-radius: 4px;
  background: rgba(59, 130, 246, 0.05);
  animation: fadeInUp 0.4s ease both;
}

.summary-card-header,
.report-notes-header,
.searches-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.summary-card-header h3,
.report-notes-header h3,
.searches-header h2 {
  margin: 0;
}

.summary-card-header svg {
  color: var(--accent-cyan);
  animation: iconGlow 3s ease-in-out infinite;
}

/* ===== MARKDOWN BODY ===== */

.markdown-body {
  text-align: left;
  color: var(--text-primary);
}

.markdown-body p,
.markdown-body li,
.markdown-body h1,
.markdown-body h2,
.markdown-body h3,
.markdown-body h4,
.markdown-body h5,
.markdown-body h6 {
  text-align: left;
}

.markdown-body a {
  color: var(--accent-cyan);
  text-decoration: none;
}

.markdown-body a:hover {
  text-decoration: underline;
  text-shadow: 0 0 8px var(--glow-cyan);
}

.markdown-body ul,
.markdown-body ol {
  padding-left: 1.5rem;
}

.markdown-body table {
  border-collapse: collapse;
  width: 100%;
  margin: 1.5rem 0;
}

.markdown-body th,
.markdown-body td {
  border: 1px solid var(--border);
  padding: 0.75rem;
  text-align: left;
}

.markdown-body th {
  background-color: var(--bg-tertiary);
  color: var(--text-primary);
  font-weight: 600;
  text-transform: uppercase;
  font-size: 0.78rem;
  letter-spacing: 0.06em;
}

.markdown-body h2 {
  border-bottom: 1px solid var(--border);
  padding-bottom: 0.5rem;
  margin-top: 2rem;
}

.markdown-body code {
  background: var(--bg-primary);
  color: var(--accent-cyan);
  border: 1px solid var(--border);
}

/* ===== NOTES ===== */

.report-notes-section {
  margin-top: 2rem;
  padding-top: 1.25rem;
  border-top: 1px solid transparent;
  border-image: linear-gradient(90deg, transparent, var(--accent-cyan), transparent) 1;
}

.report-notes-list {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}

.note-card {
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-tertiary);
  padding: 0.9rem;
  animation: fadeInUp 0.3s ease both;
}

.note-card:nth-child(1) { animation-delay: 0s; }
.note-card:nth-child(2) { animation-delay: 0.05s; }
.note-card:nth-child(3) { animation-delay: 0.1s; }

.note-card-meta {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.5rem;
  font-size: 0.72rem;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.note-card-meta span:first-child {
  background: rgba(6, 182, 212, 0.1);
  border: 1px solid rgba(6, 182, 212, 0.3);
  color: var(--accent-cyan);
  padding: 0.15rem 0.5rem;
  border-radius: 4px;
  font-weight: 600;
}

.note-card-source {
  font-weight: 600;
  margin-bottom: 0.75rem;
  color: var(--text-primary);
}

.note-card-content {
  color: var(--text-primary);
}

.note-remove {
  width: fit-content;
  background: transparent;
  color: var(--text-secondary);
  border: 1px solid transparent;
}

.note-remove:hover {
  color: var(--danger);
  border-color: rgba(239, 68, 68, 0.3);
}

.note-report-link {
  width: fit-content;
  background: transparent;
  color: var(--accent-cyan);
  border: 1px solid transparent;
}

.note-report-link:hover {
  text-decoration: underline;
  text-shadow: 0 0 8px var(--glow-cyan);
}

.notes-empty {
  font-size: 0.82rem;
  color: var(--text-secondary);
}

/* ===== EMPTY STATE ===== */

.empty-view {
  text-align: center;
  margin-top: 5rem;
  color: var(--text-secondary);
}

.empty-view svg {
  color: var(--accent-cyan);
  animation: iconGlow 3s ease-in-out infinite;
}
```

- [ ] **Step 2: Verify reports view renders correctly**

Run: `cd frontend && npm run dev`
Expected: Dark sidebar with cyan active border, dark content area, markdown with cyan links, gradient separator for notes section, glow effects on hover.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.css
git commit -m "feat: rewrite reports view, markdown body, and notes styles for dark tech theme"
```

---

### Task 7: Rewrite App.css — Chat, notes view, context menu & responsive

**Files:**
- Modify: `frontend/src/App.css` (chat, notes view, context menu, responsive — remaining sections)

- [ ] **Step 1: Replace chat, notes view, context menu and responsive styles**

Replace all remaining CSS (chat panel through responsive media query) with:

```css
/* ===== CHAT ===== */

.chat-panel {
  padding: 1.25rem;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-secondary);
}

.chat-history {
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
  max-height: 60vh;
  overflow: auto;
  margin-bottom: 1rem;
}

.chat-message {
  padding: 0.9rem 1rem;
  border-radius: 4px;
  border: 1px solid var(--border);
  background: var(--bg-tertiary);
  border-left: 2px solid var(--accent-cyan);
  animation: fadeInUp 0.3s ease both;
}

.chat-message-user {
  background: rgba(59, 130, 246, 0.08);
  border-color: var(--border);
  border-left: 2px solid var(--accent);
}

.chat-message-loading {
  background: var(--bg-tertiary);
}

.chat-message-role {
  font-size: 0.68rem;
  font-weight: 700;
  color: var(--text-secondary);
  margin-bottom: 0.5rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
}

.typing-indicator {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  min-height: 1.25rem;
}

.typing-indicator span {
  width: 0.48rem;
  height: 0.48rem;
  border-radius: 999px;
  background: var(--accent-cyan);
  box-shadow: 0 0 6px var(--glow-cyan);
  animation: chat-bounce 1.1s infinite ease-in-out;
}

.typing-indicator span:nth-child(2) {
  animation-delay: 0.15s;
}

.typing-indicator span:nth-child(3) {
  animation-delay: 0.3s;
}

@keyframes chat-bounce {
  0%,
  80%,
  100% {
    transform: translateY(0);
    opacity: 0.45;
  }
  40% {
    transform: translateY(-4px);
    opacity: 1;
  }
}

.chat-input-row {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.chat-input-row textarea {
  min-height: 120px;
  padding: 0.9rem 1rem;
  border: 1px solid var(--border);
  border-radius: 4px;
  resize: vertical;
  font-family: var(--font);
  font-size: 0.85rem;
  background: var(--bg-primary);
  color: var(--text-primary);
  transition: all 0.2s ease;
}

.chat-input-row textarea::placeholder {
  color: var(--text-secondary);
}

.chat-input-row textarea:focus {
  outline: none;
  border-color: var(--border-glow);
  box-shadow: 0 0 12px var(--glow-cyan);
}

/* ===== NOTES VIEW ===== */

.notes-view {
  animation: fadeInUp 0.4s ease both;
}

.notes-view h2 {
  margin-bottom: 1rem;
}

/* ===== SEARCHES VIEW ===== */

.searches-view {
  animation: fadeInUp 0.4s ease both;
}

.searches-header {
  margin-bottom: 1rem;
}

/* ===== CONTEXT MENU ===== */

.selection-context-menu {
  position: fixed;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-width: 200px;
  padding: 0.45rem;
  border: 1px solid var(--border-glow);
  border-radius: 4px;
  background: var(--bg-secondary);
  box-shadow: 0 0 20px var(--glow-cyan);
  z-index: 10;
  animation: contextMenuIn 0.15s ease;
}

@keyframes contextMenuIn {
  from {
    opacity: 0;
    transform: scale(0.95);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}

.selection-context-menu button {
  width: 100%;
  justify-content: flex-start;
  background: transparent;
}

.selection-context-menu button:hover {
  background: var(--bg-tertiary);
}

.selection-context-menu button svg {
  color: var(--accent-cyan);
}

/* ===== RESPONSIVE ===== */

@media (max-width: 1100px) {
  .topbar {
    grid-template-columns: 1fr;
  }

  .topbar-menu {
    justify-content: flex-start;
  }

  .reports-view {
    grid-template-columns: 1fr;
  }

  .reports-history-panel {
    position: fixed;
    top: 0;
    left: 0;
    width: 320px;
    height: 100vh;
    z-index: 20;
    overflow-y: auto;
    border-right: 1px solid var(--border-glow);
    box-shadow: 4px 0 24px rgba(0, 0, 0, 0.5);
  }

  .dashboard-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .dashboard-panels {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .app-shell {
    padding: 1rem;
  }

  .dashboard-grid {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 2: Verify all views render correctly**

Run: `cd frontend && npm run dev`
Expected: Chat messages with colored left borders, textarea with cyan glow on focus, context menu with scale animation and glow, responsive layout working at narrow widths, sidebar becomes overlay on mobile.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.css
git commit -m "feat: rewrite chat, notes view, context menu, and responsive styles for dark tech theme"
```

---

### Task 8: Final visual polish and verification

**Files:**
- Modify: `frontend/src/App.css` (minor adjustments if needed)

- [ ] **Step 1: Run the dev server and test all views**

Run: `cd frontend && npm run dev`

Verify each view:
1. **Dashboard**: 4 dark KPI cards with cyan glowing numbers, fade-in animation, tag cloud with cyan tags
2. **Reports**: Sidebar with active cyan border, markdown content with styled tables/links, summary card with pulsing sparkle icon, gradient notes separator
3. **Notes**: Note cards with cyan badge, sequential animation
4. **Searches**: Chat with colored left borders, typing indicator with cyan dots, textarea with glow focus
5. **Topbar**: Dark background, cyan bottom line, gradient primary button, nav links with cyan hover
6. **Background**: Grid pattern visible, scan line animating, cursor gradient following mouse
7. **Context menu**: Right-click on text selection shows menu with glow and scale animation
8. **Responsive**: Resize to <1100px, sidebar becomes overlay, grids collapse

- [ ] **Step 2: Run the build to verify no errors**

Run: `cd frontend && npm run build`
Expected: Build completes successfully with no errors.

- [ ] **Step 3: Commit any final adjustments**

```bash
git add -A frontend/src/
git commit -m "feat: finalize dark tech redesign — visual polish pass"
```

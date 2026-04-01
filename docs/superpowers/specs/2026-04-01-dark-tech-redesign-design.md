# Dark Tech Redesign — Veille IA Technique

## Summary

Refonte complète du design frontend de l'application "Veille IA Technique" vers un style dark mode élégant, technophile, type SaaS premium. Approche CSS-only, aucune dépendance ajoutée.

## Design Direction

- **Ambiance** : Dark mode élégant SaaS premium
- **Palette d'accents** : Bleu électrique (#3b82f6) + Cyan (#06b6d4)
- **Glassmorphism** : Subtil (fond légèrement transparent, fine bordure, léger blur)
- **Typographie** : Monospace partout (JetBrains Mono)
- **Animations** : Riches (grille animée en fond, scan lines, glow, séquences d'entrée, curseur interactif)
- **Approche technique** : CSS-only, aucune bibliothèque de particules

## Palette & Variables CSS

```css
:root {
  --bg-primary:    #0a0a0f;
  --bg-secondary:  #12121a;
  --bg-tertiary:   #1a1a2e;
  --border:        rgba(59, 130, 246, 0.15);
  --border-glow:   rgba(6, 182, 212, 0.3);
  --text-primary:  #e2e8f0;
  --text-secondary:#64748b;
  --accent:        #3b82f6;
  --accent-cyan:   #06b6d4;
  --glow-blue:     rgba(59, 130, 246, 0.4);
  --glow-cyan:     rgba(6, 182, 212, 0.3);
  --danger:        #ef4444;
  --font:          'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
}
```

## Fond animé & Effets globaux

### Grille animée

Background CSS combinant un pattern de grille (lignes fines bleutées tous les 40px) avec un gradient radial qui suit le curseur.

```css
body {
  background-color: var(--bg-primary);
  background-image:
    linear-gradient(rgba(59,130,246,0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(59,130,246,0.03) 1px, transparent 1px),
    radial-gradient(ellipse at var(--mouse-x, 50%) var(--mouse-y, 50%),
      rgba(6,182,212,0.06) 0%, transparent 60%);
  background-size: 40px 40px, 40px 40px, 100% 100%;
}
```

### Scan line

Pseudo-élément `::after` sur le body avec un gradient horizontal qui translate verticalement en boucle (~8s), opacité très faible (0.03). Effet "écran CRT" discret.

### Glow hover cartes

`box-shadow` animé qui pulse légèrement avec `var(--glow-blue)`.

### Animations d'entrée séquentielles

Cartes/items de liste : `fade-in + translateY(10px)` avec `animation-delay` incrémenté par `nth-child` (0.05s par élément).

### Gradient radial curseur

~10 lignes JS dans `App.tsx` (useEffect + mousemove) mettant à jour `--mouse-x` et `--mouse-y` sur le body.

## Topbar

- Structure identique (grille 3 colonnes : brand | nav | actions)
- Fond `var(--bg-secondary)`, bordures droites (pas de border-radius), fine ligne cyan en bas
- Brand : icône Bot en cyan avec `text-shadow` glow, sous-titre en `var(--text-secondary)`
- Nav links : fond transparent, texte monospace muted. Hover : texte cyan + glow. Actif : bordure basse cyan 2px, texte blanc
- Bouton "Lancer la veille" : gradient bleu→cyan, `box-shadow` glow bleu, glow intensifié au hover

## Dashboard

### KPI Cards (grille 4 colonnes)

- Fond `var(--bg-secondary)`, bordure `var(--border)`
- Chiffre en grande taille, couleur cyan, `text-shadow` glow
- Label : uppercase, letter-spacing large, petite taille, muted — look "instrument de bord"
- Hover : bordure `var(--border-glow)`, `box-shadow` glow subtil
- Animation d'entrée séquentielle

### Panel "Projets innovants"

- Tags : fond `rgba(6,182,212,0.1)`, bordure `rgba(6,182,212,0.3)`, texte cyan
- Hover : glow autour du tag

### Panel "Dernier rapport"

- Même style card, bouton "Ouvrir le rapport" en outline cyan

## Vue Rapports

### Sidebar historique

- Fond `var(--bg-secondary)`, bordure droite `var(--border)`
- Titres groupes (dates) : uppercase, muted, letter-spacing 0.1em — style "log timestamp"
- Items : hover → fond `var(--bg-tertiary)`. Actif → fond tertiary + bordure gauche 2px cyan
- Menu dropdown : fond secondary, bordure standard, glow bleu

### Zone contenu principal

- Fond `var(--bg-secondary)`, bordure `var(--border)`
- Summary card : fond `rgba(59,130,246,0.05)`, bordure `rgba(59,130,246,0.2)`, icône Sparkles avec glow animé (pulse)
- Markdown body : texte primary, liens cyan, tables avec header en tertiary, code blocks en fond primary
- Séparateur notes : gradient horizontal transparent→cyan→transparent

### Notes du rapport

- Cards : fond tertiary, bordure standard
- Badge "Détail"/"Note" : fond cyan transparent, texte cyan
- Bouton supprimer : texte danger au hover uniquement

### Empty state

- Icône Bot cyan avec glow pulse animé

## Vue Recherches (Chat)

- Messages user : fond `rgba(59,130,246,0.08)`, bordure gauche 2px bleue
- Messages assistant : fond tertiary, bordure gauche 2px cyan
- Labels : uppercase, letter-spacing, monospace — look "log system"
- Animation d'entrée : slide-in depuis le bas avec fade
- Typing indicator : dots cyan avec glow pulsé
- Textarea : fond primary, focus → bordure glow cyan + box-shadow
- Bouton "Envoyer" : même gradient que "Lancer la veille"

## Vue Notes

- Même style note cards que vue rapports
- Bouton lien rapport : style lien cyan, underline au hover
- Animation d'entrée séquentielle

## Menu contextuel (clic droit)

- Fond secondary, bordure glow cyan, box-shadow glow
- Items : icônes cyan, texte primary. Hover → fond tertiary
- Apparition : animation scale(0.95→1) + fade-in (0.15s)

## Responsive

- Breakpoint à 1100px (conservé)
- Dashboard grid : 4 → 2 → 1 colonnes
- Sidebar rapports : overlay sur mobile

## Implémentation technique

- **Fichiers modifiés** : `App.css`, `index.css`, `index.html` (import font), `App.tsx` (~10 lignes JS pour le curseur)
- **Fichiers ajoutés** : Aucun
- **Dépendances ajoutées** : Aucune (JetBrains Mono via Google Fonts CDN)
- **Approche** : CSS-only, remplacement des variables et styles existants

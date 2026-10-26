# Guide fonctionnel

[← Sommaire](README.md)

Veille IA produit une veille technique quotidienne sur l'IA, pensée pour l'équipe STTI d'APRIL (architecture, plateforme, sécurité, développement) : décider vite, garder les nouveautés utiles, en parler au comité de direction. L'interface est en français, au vouvoiement, aux couleurs de la charte APRIL.

## Les vues

La barre supérieure donne accès à cinq vues.

### Tableau de bord

Point d'entrée de l'application.

- **Bandeau** : TL;DR de la dernière veille, avec les boutons « Lire le rapport » et « Note CODIR » (ouvre la note CODIR du même jour si elle existe, sinon la génère). Sans aucune veille, le bandeau propose « Lancer la veille ».
- **Quatre indicateurs** : nombre de rapports (et combien cette semaine), éléments « À tester maintenant » sur 7 jours, sources et nouveautés détaillées, notes enregistrées (dont détails et définitions).
- **Radar de la semaine** : jusqu'à 6 éléments « À tester » / « À surveiller » des veilles des 7 derniers jours ; un clic ouvre le rapport concerné.
- **Projets suivis** : outils repérés dans les rapports (Cursor, Claude Code, MCP, Ollama, vLLM…). Un clic produit une synthèse en quatre points (Nouveauté, Intérêt pour APRIL, Risque ou limite, Action recommandée) à partir des rapports qui mentionnent le projet. La synthèse est gardée 24 h dans le navigateur et n'apparaît pas dans l'historique des recherches.

### Rapports

Lecture d'un rapport.

- **Historique** (colonne de gauche, repliable) avec filtre texte ; menu d'actions par rapport (exports, suppression).
- **En-tête** : type (Analyse technique ou Note CODIR), date, badges (nouveautés, sources, news sauvegardées, résumé) et actions :
  - veille : « Générer la note CODIR », « Résumé exécutif », « Exporter en PDF », « Newsletter », « Envoyer par mail », « Partager dans Teams » ;
  - note CODIR : « Exporter en Word », « Exporter en PDF », « Partager dans Teams ».
- **Résumé exécutif** repliable, s'il a été généré.
- **Lecture structurée** quand le rapport suit le format de veille : carte TL;DR, grille du radar (tester / surveiller / ignorer), une carte par nouveauté avec ses champs, badge de maturité, encadré « Action recommandée » et bouton **Sauvegarder**. Les autres sections et les rapports anciens s'affichent en markdown.
- **Colonne de droite** : sommaire cliquable et notes du rapport.
- **Barre d'outils de sélection** : sélectionner un passage (ou clic droit) propose « Ajouter aux notes », « Approfondir » et « Définir ».

### News sauvegardées

Toutes les nouveautés sauvegardées, des plus récentes aux plus anciennes : titre, maturité, date de sauvegarde, contenu et lien vers le rapport. Une news dont le rapport a été supprimé reste visible avec la mention « rapport supprimé ». « Retirer » la désauvegarde.

### Notes

Liste de toutes les notes (notes, détails, définitions) avec le rapport d'origine ; suppression possible.

### Recherches (« Interroger la veille »)

Conversation avec l'assistant sur les rapports.

- **Rapports consultés** : pastilles retirables, « + Ajouter » pour en choisir d'autres (3 au maximum). Par défaut, les 3 dernières veilles.
- **Conversation** : réponses en markdown avec citations « (Rapport 12 · Nouveautés détaillées) », sources cliquables, boutons « Enregistrer en note » et « Copier ».
- **Nouvelle conversation** : les questions suivantes ne tiennent plus compte des échanges précédents (un séparateur est ajouté).
- **Chercher aussi sur le web** : la réponse est complétée par une recherche internet, séparée en « D'après les rapports » / « Sur le web », avec liens. Grisé si le fournisseur LLM n'a pas accès au web.
- **Suggestions** en un clic ; Entrée envoie, Maj+Entrée passe à la ligne.
- **Mes notes** (colonne de droite) : notes filtrables par type (Toutes, Notes, Détails, Définitions).

## Cas d'usage

| Je veux… | Comment | Ce qui se passe |
| --- | --- | --- |
| **Lancer la veille** | « Lancer la veille » (tableau de bord), ou le cron `POST /cron/daily` | Le LLM cherche sur le web les nouveautés des dernières 24 h, vérifie les sources et rédige le rapport (plusieurs minutes, jusqu'à 10). Avec `REDDIT_ENABLED=true`, il reçoit aussi les discussions Reddit les plus votées des subreddits suivis, comme pistes à vérifier. Les nouveautés sont extraites et deviennent sauvegardables. Une seule génération à la fois. |
| **Obtenir un résumé** | « Résumé exécutif » dans un rapport | 5 points maximum tirés du rapport, terminés par « Décision suggérée ». Enregistré et réaffiché ensuite ; peut être régénéré. |
| **Approfondir un extrait** | Sélectionner un passage → « Approfondir » | Explication de 6 lignes maximum, à partir du rapport seulement ; enregistrée comme note « Détail ». |
| **Définir un terme** | Sélectionner un terme → « Définir » | Définition courte et vulgarisée ; enregistrée comme note « Définition ». |
| **Prendre une note** | Sélectionner → « Ajouter aux notes », ou « Enregistrer en note » sous une réponse de l'assistant | Note attachée au rapport ; visible dans le rapport, la vue Notes, les recherches et l'export PDF. |
| **Garder une nouveauté** | « Sauvegarder » sur une carte de nouveauté | Elle apparaît dans « News sauvegardées » et survit à la suppression du rapport. |
| **Préparer le CODIR** | « Générer la note CODIR », puis « Exporter en Word » | Note d'une page pour des directeurs non techniques (synthèse, décisions proposées, points de vigilance), construite à partir du rapport, de son résumé et des notes. Enregistrée comme rapport « Note CODIR ». |
| **Interroger la veille** | Vue Recherches | Réponse fondée sur les rapports choisis, avec citations ; option web pour compléter. |
| **Exporter** | « Exporter en PDF » (tout rapport), « Exporter en Word » (note CODIR) | PDF : résumé, rapport complet, notes. Word : note CODIR mise en page. |
| **Diffuser par email** | « Newsletter », ou « Envoyer par mail » | « Newsletter » ouvre dans un onglet la newsletter HTML, prête à coller dans un client mail. « Envoyer par mail » l'envoie, après confirmation, aux destinataires configurés (`MAIL_TO`) avec l'objet « Veille IA – <date> » ; le bouton devient « Renvoyer par mail » et son info-bulle donne la date du dernier envoi. Grisé si le mail n'est pas configuré. Avec `MAIL_AUTO_SEND=true`, le cron l'envoie automatiquement une fois par jour. |
| **Partager dans Teams** | « Partager dans Teams » | Télécharge le PDF (ou le Word pour une note CODIR) et ouvre la conversation Teams de l'équipe pour y déposer le fichier. |
| **Supprimer un rapport** | Menu du rapport dans l'historique | Supprime le rapport, son résumé, ses notes et ses news non sauvegardées. |

## Structure d'un rapport de veille

Le prompt `TECHNICAL_PROMPT` impose cette structure ; l'interface, l'extraction des news, la newsletter et le PDF s'appuient dessus.

```markdown
## TL;DR
- 3 puces maximum : l'essentiel du jour

## Radar décisionnel
### À tester maintenant
- …
### À surveiller
- …
### À ignorer
- … (bruit marketing, avec la raison)

## Nouveautés détaillées
### <Titre court de la nouveauté>
- **Ce qui sort** : …
- **Pourquoi c'est important** : …
- **Pour qui** : …
- **Type** : nouveau modèle / API / tarification / tool use / long context / multimodal / agents / sécurité / dépréciation / disponibilité / entreprise
- **Maturité** : prototype / alpha / bêta / GA / production-ready
- **Ancrage April** : … (seulement si pertinent : Dagster, Snowflake, Azure, M365, cas assurance)
- **Action recommandée** : …
- **Source** : [titre](url) — publié le AAAA-MM-JJ

## Sécurité & gouvernance
- … (toujours présente ; « Rien de notable dans la période » sinon)

## Signaux faibles & recherche
- repos qui montent, publications, discussions Reddit marquantes (si activé), sujets à recontrôler

## Note de méthode
- fenêtre couverte, éléments issus de trackers tiers, rappel bêta ≠ production
```

Règles de contenu : sources officielles en priorité, uniquement ce qui est paru dans la période (un sujet déjà couvert ne revient qu'avec un fait nouveau, titre préfixé « Mise à jour : »), maturité toujours indiquée, rapport court les jours calmes. Le périmètre couvre les labs (OpenAI, Anthropic, Google, Meta, Mistral, Microsoft, AWS, xAI, Cohere, NVIDIA, DeepSeek, Qwen…), les outils de code et agents, l'écosystème (MCP, Ollama, OpenRouter, orchestration, sécurité des agents) et la recherche à impact pratique.

**Anciens rapports.** Les rapports générés avant la refonte « décision d'abord » suivent l'ancien format (`## 1. Nouveautés majeures`, `## 2. Détail par catégorie`, `## 3. Tableau de synthèse`…). Ils restent lisibles : l'interface les affiche en markdown simple, sans cartes de nouveautés ni sauvegarde.

**Note CODIR.** Format différent, produit par `CODIR_NOTE_PROMPT` : en-tête, synthèse (4 lignes), tableau « Décisions proposées » (3 lignes maximum), 3 points de vigilance, pied de page.

## Sous-ensemble markdown supporté par le PDF

Le PDF est construit ligne à ligne (`append_markdown_pdf_elements`). Seuls ces éléments sont interprétés :

| Élément | Syntaxe | Rendu |
| --- | --- | --- |
| Titre de section | `## Titre` | Titre de niveau 2 |
| Sous-titre | `### Titre` | Titre de niveau 3 |
| Puce | `- texte` (un seul niveau) | Puce |
| Tableau | lignes commençant par `\|` | Tableau (la ligne de séparation `---` est ignorée) |
| Image | `![légende](https://…)` seule sur sa ligne | Image téléchargée et légende |
| Gras, lien | `**gras**`, `[texte](https://…)` dans une ligne | Gras, lien cliquable |
| Autre ligne | texte | Paragraphe |

Non supportés : listes imbriquées, listes numérotées (rendues comme paragraphes), `####` et au-delà, blocs de code, citations `>`. Toute évolution du format des prompts doit rester dans ce sous-ensemble ou étendre le moteur de rendu.

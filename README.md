# jeremy.chevallier.net

The source for Jérémy Chevallier’s personal website: a regenerative-design practice at the center, surrounded by side projects, art, music, tools, and a long-running body of writing.

## Local preview

This is a dependency-free static site. From the repository root:

```bash
python3 -m http.server 4173 --directory dist
```

Then open `http://localhost:4173`.

## Editing

- `dist/index.html` contains the homepage content and structure.
- `dist/styles.css` contains the visual system and responsive layout.
- `dist/script.js` contains the small navigation and reveal interactions.
- `dist/assets/` contains local site imagery.
- `dist/archive.css` and `dist/archive.js` power the preserved archive.
- Nested folders in `dist/` preserve the legacy site’s public URLs exactly.

Keep the site fast and editorial. Aim for roughly 60–70% permaculture, regenerative systems, and practical consulting, with the remaining space devoted to ventures, experiments, art, music, and thought leadership.

## Legacy archive

The migration generated a static page for every URL found in the legacy sitemap. To rebuild it from the live legacy site:

```bash
python3 -m pip install -r requirements-migration.txt
python3 scripts/migrate_archive.py
```

The script caches source pages in `.migration-cache/`, localizes and optimizes available images, and writes a coverage report to `migration-report.json`. Review homepage edits after rerunning it; the archive generator intentionally owns the nested legacy routes, not `dist/index.html`.

## Deployment

GitHub Pages deploys the contents of `dist/` on every push to `main` through `.github/workflows/deploy-pages.yml`.

The custom domain is declared in `dist/CNAME`. DNS must point `jeremy.chevallier.net` to the GitHub Pages hostname before the custom domain becomes active.

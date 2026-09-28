# jeremy.chevallier.net

The source for Jérémy Chevallier’s personal website, focused on permaculture design, regenerative systems, and consulting.

## Local preview

This is a dependency-free static site. From the repository root:

```bash
python3 -m http.server 4173 --directory dist
```

Then open `http://localhost:4173`.

## Editing

- `dist/index.html` contains the content and page structure.
- `dist/styles.css` contains the visual system and responsive layout.
- `dist/script.js` contains the small navigation and reveal interactions.
- `dist/assets/` contains local site imagery.

Keep the site fast and editorial. Permaculture, regenerative systems, and practical consulting are the primary story; other creative work should remain secondary.

## Deployment

GitHub Pages deploys the contents of `dist/` on every push to `main` through `.github/workflows/deploy-pages.yml`.

The custom domain is declared in `dist/CNAME`. DNS must point `jeremy.chevallier.net` to the GitHub Pages hostname before the custom domain becomes active.

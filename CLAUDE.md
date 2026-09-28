# Working on jeremy.chevallier.net

This is a dependency-free static website deployed from `dist/`.

## Product direction

- Lead with Jérémy’s permaculture practice and strategic consulting, while keeping the overall mix approximately 60–70% regeneration and 30–40% side projects and wider thought leadership.
- Keep the voice confident, grounded, direct, and human.
- Favor evidence, concrete work, and clear invitations over generic personal-brand language.
- Treat art, music, ventures, and older career material as meaningful parts of a multidisciplinary body of work, without letting them displace the flagship regenerative practice.
- Preserve every published legacy URL. Do not rename, consolidate, or delete archive routes without an explicit redirect plan.

## Design direction

- Editorial, minimal, tactile, and modern.
- Preserve the ink / paper / acid-green palette and the large serif display typography.
- Use generous spacing and purposeful motion. Avoid generic cards, gradients, and excessive UI decoration.
- Maintain responsive behavior, keyboard navigation, reduced-motion support, and readable text.

## Before committing

1. Preview the site at desktop and mobile widths.
2. Confirm all internal anchors and external links work.
3. Confirm there is no horizontal scrolling at narrow widths.
4. Keep generated files, credentials, and local server artifacts out of Git.
5. If archive generation changes, compare `migration-report.json` and confirm every sitemap URL has a corresponding `dist/**/index.html` file.

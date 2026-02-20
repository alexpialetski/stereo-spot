# stereo-spot-docs

Documentation for **StereoSpot**: architecture, pipeline, runbooks, testing, and AWS. Built with [Docusaurus](https://docusaurus.io/) and the single source of truth for the project (see root [AGENTS.md](../../AGENTS.md) and [.cursor/rules](../../.cursor/rules)).

## Commands

From the workspace root:

- **Preview locally:** `nx start stereo-spot-docs` — dev server (e.g. http://localhost:3000)
- **Build:** `nx build stereo-spot-docs` — output in `packages/stereo-spot-docs/build`
- **Serve built site:** `nx serve stereo-spot-docs` — serve the build output locally

CI runs `nx build stereo-spot-docs` to validate links and Mermaid; the site is deployed to GitHub Pages on push to main. The build uses `onBrokenLinks: 'throw'` to catch broken navigation links.

## Content and config

- **Content:** All docs live under `docs/`. Edit Markdown/MDX there; the sidebar is driven by `sidebars.ts`.
- **Config:** `docusaurus.config.ts` (site metadata, theme, redirects, Mermaid). Edit URL and `editUrl` there if the repo or base path changes.
- **Mermaid icons:** AWS infrastructure diagrams (e.g. `docs/aws/infrastructure.md`) use Mermaid **architecture-beta** with Iconify logos. The script `src/scripts/register-mermaid-icons.js` registers the `logos` pack so diagram nodes can use `logos:aws-s3`, etc. Use architecture-beta only for AWS infra; keep generic diagrams as flowchart/sequence.

## Search

The site uses **docusaurus-plugin-search-local** for offline search (no API key). The search index is built at build time; the search UI appears in the navbar. To switch to [Algolia DocSearch](https://docusaurus.io/docs/search) later, add the plugin and document any required env or keys here.

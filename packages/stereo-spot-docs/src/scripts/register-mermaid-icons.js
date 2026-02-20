/**
 * Register Iconify "logos" pack with Mermaid for architecture-beta diagrams.
 * Icons load on-demand from CDN when a diagram uses them (e.g. logos:aws-s3).
 * Use only in AWS infrastructure diagrams; keep generic diagrams as flowchart/sequence.
 */
(async function registerMermaidIcons() {
  const mermaid = (await import('mermaid')).default;
  if (typeof mermaid.registerIconPacks !== 'function') return;

  mermaid.registerIconPacks([
    {
      name: 'logos',
      loader: () =>
        fetch('https://unpkg.com/@iconify-json/logos/icons.json').then((r) =>
          r.json()
        ),
    },
  ]);
})();

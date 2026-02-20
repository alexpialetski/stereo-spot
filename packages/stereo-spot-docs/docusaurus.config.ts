import { themes as prismThemes } from 'prism-react-renderer';
import type { Config } from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'StereoSpot',
  tagline: 'High-throughput, cost-optimized video processing',
  favicon: 'img/favicon.svg',

  markdown: {
    mermaid: true,
  },
  themes: ['@docusaurus/theme-mermaid'],

  clientModules: [
    require.resolve('./src/scripts/register-mermaid-icons.js'),
  ],

  // Opt into Docusaurus v4 behavior for a smoother upgrade path later.
  future: {
    v4: true,
  },

  url: 'https://alexpialetski.github.io',
  baseUrl: '/stereo-spot/',

  organizationName: 'alexpialetski',
  projectName: 'stereo-spot',

  onBrokenLinks: 'throw',

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  plugins: [
    [
      '@docusaurus/plugin-client-redirects',
      {
        redirects: [
          { from: '/docs/shared-types', to: '/docs/architecture/shared-types' },
          { from: '/docs/getting-started/overview', to: '/docs/intro' },
        ],
      },
    ],
    [
      require.resolve('docusaurus-plugin-search-local'),
      { hashed: true, indexBlog: false },
    ],
  ],

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          editUrl:
            'https://github.com/alexpialetski/stereo-spot/tree/main/packages/stereo-spot-docs/',
        },
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    colorMode: {
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: '', // Logo SVG already contains "StereoSpot" text; avoid duplicate/truncation
      logo: {
        alt: 'StereoSpot',
        src: 'img/logo.svg',
      },
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'docsSidebar',
          position: 'left',
          label: 'Docs',
        },
        {
          href: 'https://github.com/alexpialetski/stereo-spot',
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Docs',
          items: [
            { label: 'Introduction', to: '/docs/intro' },
            { label: 'Architecture', to: '/docs/architecture/overview' },
            { label: 'Packages', to: '/docs/packages/overview' },
            { label: 'Testing', to: '/docs/testing' },
            { label: 'Runbooks', to: '/docs/runbooks' },
            { label: 'AWS', to: '/docs/aws/infrastructure' },
          ],
        },
        {
          title: 'More',
          items: [
            { label: 'GitHub', href: 'https://github.com/alexpialetski/stereo-spot' },
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} StereoSpot. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
    mermaid: {
      theme: { light: 'neutral', dark: 'forest' },
    },
  } satisfies Preset.ThemeConfig,
};

export default config;

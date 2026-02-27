import type { SidebarsConfig } from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  docsSidebar: [
    'intro',
    'viewing-3d',
    {
      type: 'category',
      label: 'Architecture',
      items: [
        'architecture/overview',
        'architecture/pipeline',
        'architecture/shared-types',
        'architecture/platform-adapters',
        'architecture/inference',
      ],
    },
    {
      type: 'category',
      label: 'Packages',
      items: ['packages/overview'],
    },
    'streaming-capture',
    'testing',
    'runbooks',
    'operations',
    'migration',
    {
      type: 'category',
      label: 'AWS',
      items: [
        'aws/bring-up',
        'aws/why-aws',
        'aws/services-and-requirements',
        'aws/infrastructure',
        'aws/runbooks',
        'aws/build-and-deploy',
      ],
    },
  ],
};

export default sidebars;

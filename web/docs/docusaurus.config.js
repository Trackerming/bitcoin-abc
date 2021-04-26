module.exports = {
    title: 'Cashtab Docs',
    tagline: 'Add cash payments to your website',
    url: 'https://docs.cashtabapp.com',
    baseUrl: '/',
    onBrokenLinks: 'throw',
    onBrokenMarkdownLinks: 'warn',
    favicon: 'img/favicon.ico',
    organizationName: 'bitcoin-abc',
    projectName: 'cashtab',
    themeConfig: {
        colorMode: {
            // "light" | "dark"
            defaultMode: 'dark',
        },
        googleAnalytics: {
            trackingID: 'UA-183678810-2',
        },
        image: 'img/twitter-card.jpg',
        navbar: {
            title: 'Cashtab',
            logo: {
                alt: 'Cashtab Logo',
                src: 'img/logo.svg',
            },
            items: [
                {
                    to: 'docs/',
                    activeBasePath: 'docs',
                    label: 'Docs',
                    position: 'left',
                },
                {
                    href: 'https://github.com/bitcoin-abc/bitcoin-abc/',
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
                        {
                            label: 'Overview',
                            to: 'docs/',
                        },
                        {
                            label: 'cashtab-components',
                            to: 'docs/components-overview/',
                        },
                    ],
                },
                {
                    title: 'Community',
                    items: [
                        {
                            label: 'Twitter',
                            href: 'https://twitter.com/Bitcoin_ABC',
                        },
                    ],
                },
                {
                    title: 'More',
                    items: [
                        {
                            label: 'BCHA',
                            href: 'https://bitcoinabc.org/bcha/',
                        },
                    ],
                },
            ],
            copyright: `Copyright © ${new Date().getFullYear()} Bitcoin ABC.`,
        },
    },
    presets: [
        [
            '@docusaurus/preset-classic',
            {
                docs: {
                    sidebarPath: require.resolve('./sidebars.js'),
                    editUrl:
                        'https://github.com/Bitcoin-ABC/bitcoin-abc/tree/master/web/docs/',
                },
                theme: {
                    customCss: require.resolve('./src/css/custom.css'),
                },
            },
        ],
    ],
};

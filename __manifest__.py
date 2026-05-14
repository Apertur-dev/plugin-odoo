{
    'name': 'Apertur - Photo Collection',
    'version': '16.0.1.1.0',
    'category': 'Tools',
    'summary': 'Collect photos from mobile devices via QR code',
    'description': 'Integrate Apertur photo collection into Odoo. '
                   'Add QR-based photo capture to contacts, tasks, and tickets. '
                   'Supports multi-mode sessions (contact/internal/public), '
                   'dark mode, sandbox indicator, delivery status tracking, '
                   'and English/French/Spanish translations.',
    'author': 'Apertur',
    'website': 'https://apertur.ca',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'contacts'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/apertur_session_views.xml',
        'views/res_partner_views.xml',
        'data/ir_cron.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'apertur_connect/static/src/js/apertur_widget.js',
            'apertur_connect/static/src/xml/apertur_widget.xml',
        ],
    },
    'installable': True,
    'application': False,
}

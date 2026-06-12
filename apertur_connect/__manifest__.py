{
    'name': 'Apertur Photo Collection',
    'version': '16.0.1.1.6',
    'category': 'Tools',
    'summary': 'Collect photos from mobile devices via QR code (Apertur).',
    'description': """
Apertur Photo Collection
========================

Integrate Apertur (https://apertur.ca) photo collection into Odoo CRM/ERP.
Generate a QR code from any contact, task or ticket and let the recipient
upload photos from a mobile device. Received images are attached to the
record and posted to the chatter automatically.

Apertur is a SaaS service. A free tier is available (5 sessions per month,
10 images per session, 5 MB per image, 12-hour session expiry). Paid plans
unlock higher limits, password-protected sessions, custom branding and
end-to-end encryption.

This module communicates with the Apertur API at https://api.apertur.ca
using an API key that you configure in Odoo. Image events are received via
an HMAC-signed webhook posted to /apertur/webhook on your Odoo instance.
No data is sent to Apertur outside of the records you explicitly attach to
a session. Your data remains yours and can be deleted at any time from
your Apertur dashboard.
""",
    'author': 'Apertur',
    'maintainer': 'Apertur',
    'website': 'https://apertur.ca',
    'support': 'support@apertur.ca',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'contacts'],
    'external_dependencies': {
        'python': ['requests'],
    },
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/apertur_session_views.xml',
        'views/apertur_menus.xml',
        'views/res_partner_views.xml',
        'data/ir_cron.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'apertur_connect/static/src/js/apertur_widget.js',
            'apertur_connect/static/src/xml/apertur_widget.xml',
        ],
    },
    'images': [
        'static/description/main_screenshot.png',
        'static/description/screenshot_session.png',
        'static/description/screenshot_widget.png',
        'static/description/screenshot_settings.png',
    ],
    'live_test_url': 'https://apertur.ca/demo',
    'installable': True,
    'application': False,
}

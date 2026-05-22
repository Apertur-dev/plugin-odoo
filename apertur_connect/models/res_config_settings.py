from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    apertur_webhook_url = fields.Char(
        string='Webhook URL',
        compute='_compute_apertur_webhook_url',
    )
    apertur_api_key = fields.Char(
        string='API Key',
        help='Your Apertur API key (starts with aptr_live_ or aptr_test_).',
        config_parameter='apertur.api_key',
    )
    apertur_base_url = fields.Char(
        string='API Base URL',
        help='Override the Apertur API base URL. '
             'Leave empty to auto-detect from key prefix.',
        config_parameter='apertur.base_url',
    )
    apertur_webhook_secret = fields.Char(
        string='Webhook Secret',
        help='Secret used to verify incoming webhook signatures.',
        config_parameter='apertur.webhook_secret',
    )
    apertur_default_max_images = fields.Integer(
        string='Default Max Images',
        help='Default maximum number of images per session.',
        config_parameter='apertur.default_max_images',
        default=10,
    )
    apertur_enabled_models = fields.Char(
        string='Enabled Models',
        help='Comma-separated list of Odoo models where Apertur '
             'capture is available (e.g. res.partner,project.task).',
        config_parameter='apertur.enabled_models',
        default='res.partner',
    )
    apertur_is_sandbox = fields.Boolean(
        string='Sandbox Mode',
        compute='_compute_apertur_is_sandbox',
        help='True when the configured API key is a test/sandbox key '
             '(starts with aptr_test_).',
    )

    @api.depends('apertur_api_key')
    def _compute_apertur_webhook_url(self):
        base = self.env['ir.config_parameter'].sudo().get_param(
            'web.base.url', default='https://your-odoo.com'
        )
        for record in self:
            record.apertur_webhook_url = '%s/apertur/webhook' % base.rstrip('/')

    @api.depends('apertur_api_key')
    def _compute_apertur_is_sandbox(self):
        for record in self:
            key = record.apertur_api_key or ''
            record.apertur_is_sandbox = key.startswith('aptr_test_')

    @api.model
    def get_apertur_base_url(self):
        """Return the resolved Apertur API base URL.

        If a custom base URL is configured it is returned as-is.
        Otherwise the URL is derived from the API key prefix:
        keys starting with ``aptr_test_`` target the sandbox environment.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        base_url = ICP.get_param('apertur.base_url', default='')
        if base_url:
            return base_url.rstrip('/')

        api_key = ICP.get_param('apertur.api_key', default='')
        if api_key.startswith('aptr_test_'):
            return 'https://sandbox.api.aptr.ca'
        return 'https://api.aptr.ca'

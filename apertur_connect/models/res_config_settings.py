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
    apertur_destination_id = fields.Char(
        string='Destination ID',
        help='Required. UUID of the Apertur destination of type \'odoo\' that '
             'will receive uploaded photos. Create the destination from the '
             'Apertur dashboard (Destinations > Add destination > Odoo) and '
             'paste its ID here.',
        config_parameter='apertur.destination_id',
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
    # Stored as a comma-separated list of model technical names under the
    # ``apertur.enabled_models`` config parameter (kept as the source of
    # truth for backward compatibility). The Many2many here is only a UI
    # convenience rendered as checkboxes; get_values/set_values translate
    # between the two. The domain limits the choices to models that have a
    # chatter (mail thread), since that is where captured photos are posted.
    apertur_enabled_model_ids = fields.Many2many(
        comodel_name='ir.model',
        relation='apertur_config_enabled_model_rel',
        column1='config_id',
        column2='model_id',
        string='Enabled Models',
        domain=[('is_mail_thread', '=', True)],
        help='Models where Apertur capture is available. Only models that '
             'have a chatter (mail thread) are listed.',
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
    def get_values(self):
        res = super().get_values()
        ICP = self.env['ir.config_parameter'].sudo()
        # Fresh installs (key absent) default to res.partner; an explicit
        # empty string (user unchecked everything) stays empty.
        raw = ICP.get_param('apertur.enabled_models', default='res.partner')
        names = [n.strip() for n in (raw or '').split(',') if n.strip()]
        models = (
            self.env['ir.model'].search([('model', 'in', names)])
            if names else self.env['ir.model']
        )
        res['apertur_enabled_model_ids'] = [(6, 0, models.ids)]
        return res

    def set_values(self):
        super().set_values()
        names = ','.join(sorted(self.apertur_enabled_model_ids.mapped('model')))
        self.env['ir.config_parameter'].sudo().set_param(
            'apertur.enabled_models', names,
        )

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

import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


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
        model_names = sorted(self.apertur_enabled_model_ids.mapped('model'))
        self.env['ir.config_parameter'].sudo().set_param(
            'apertur.enabled_models', ','.join(model_names),
        )
        self._sync_apertur_capture_bindings(model_names)
        self._sync_apertur_capture_views(model_names)

    # Marker stored in the generated server actions' code, so we can find and
    # refresh exactly the ones we own without touching user-made actions.
    _APERTUR_BINDING_SENTINEL = '# apertur:capture-binding'
    # Name prefix for the dynamically generated inherited form views.
    _APERTUR_VIEW_PREFIX = 'apertur.capture.dyn.'

    def _sync_apertur_capture_bindings(self, model_names):
        """Generate one "Action menu" entry per mode on every enabled model,
        so capturing photos works on any *installed* model the admin checks —
        without adding a hard dependency on those modules.

        Implementation: model-bound ``ir.actions.server`` (binding_type
        ``action``) appear in the cog/Action dropdown of the model's list &
        form views. We regenerate them on every save (drop ours, recreate the
        desired set). ``res.partner`` is skipped — it keeps its dedicated form
        buttons.
        """
        Server = self.env['ir.actions.server'].sudo()
        sentinel = self._APERTUR_BINDING_SENTINEL

        # Drop the previously generated bindings.
        Server.search([
            ('state', '=', 'code'), ('code', 'like', sentinel),
        ]).unlink()

        # Only bind to installed models (present in ir.model) that carry a
        # chatter; res.partner is handled by its native buttons.
        models = self.env['ir.model'].sudo().search([
            ('model', 'in', model_names),
            ('is_mail_thread', '=', True),
            ('model', '!=', 'res.partner'),
        ])
        modes = [
            ('contact', _('Apertur: Request from Contact')),
            ('internal', _('Apertur: Upload as Internal Note')),
            ('public', _('Apertur: Upload as Public Message')),
        ]
        for model in models:
            for mode, name in modes:
                code = (
                    "%(sentinel)s\n"
                    "if records:\n"
                    "    _r = records[:1]\n"
                    "    action = env['apertur.session'].action_capture_for("
                    "_r._name, _r.id, '%(mode)s')\n"
                ) % {'sentinel': sentinel, 'mode': mode}
                Server.create({
                    'name': name,
                    'model_id': model.id,
                    'binding_model_id': model.id,
                    'binding_type': 'action',
                    'state': 'code',
                    'code': code,
                })

    def _apertur_capture_page_arch(self):
        """Inherited-view arch adding an "Apertur" notebook page, mirroring
        the res.partner tab. The session list uses apertur.session's own
        list view (no inline tree/list) so the arch is Odoo-version agnostic.
        """
        return (
            '<xpath expr="//notebook" position="inside">'
            '<page string="Apertur" name="apertur_capture">'
            '<div class="oe_button_box mb16">'
            '<button name="action_apertur_capture_contact"'
            ' string="Request from Contact" type="object"'
            ' class="btn-primary" icon="fa-paper-plane"/>'
            '<button name="action_apertur_capture_internal"'
            ' string="Upload as Internal Note" type="object"'
            ' class="btn-secondary" icon="fa-lock"/>'
            '<button name="action_apertur_capture_public"'
            ' string="Upload as Public Message" type="object"'
            ' class="btn-secondary" icon="fa-camera"/>'
            '</div>'
            '<group string="Active Sessions">'
            '<field name="apertur_session_ids" nolabel="1" readonly="1"/>'
            '</group>'
            '<group string="Photos">'
            '<field name="apertur_image_count"'
            ' string="Total photos received"/>'
            '</group>'
            '</page>'
            '</xpath>'
        )

    def _sync_apertur_capture_views(self, model_names):
        """Inject an "Apertur" notebook page into each enabled model's form,
        like the native res.partner tab. Regenerated on every save.

        Robust by design: we inherit the model's actually-rendered form view
        and target ``//notebook``; models whose main form has no notebook (or
        can't be resolved) are skipped with a warning — their Action-menu
        entries still work.
        """
        View = self.env['ir.ui.view'].sudo()
        prefix = self._APERTUR_VIEW_PREFIX

        # Drop previously generated pages.
        View.search([('name', '=like', prefix + '%')]).unlink()

        models = self.env['ir.model'].sudo().search([
            ('model', 'in', model_names),
            ('is_mail_thread', '=', True),
            ('model', '!=', 'res.partner'),
        ])
        arch = self._apertur_capture_page_arch()
        for model in models:
            # Inherit the model's main (lowest-priority primary) form view.
            form = View.search([
                ('model', '=', model.model),
                ('type', '=', 'form'),
                ('mode', '=', 'primary'),
            ], order='priority, id', limit=1)
            if not form:
                _logger.warning(
                    'Apertur: no primary form view for %s, skipping tab',
                    model.model,
                )
                continue
            parent_id = form.id
            try:
                with self.env.cr.savepoint():
                    View.create({
                        'name': '%s%s' % (prefix, model.model),
                        'model': model.model,
                        'inherit_id': parent_id,
                        'priority': 99,
                        'arch': arch,
                    })
            except Exception as exc:  # noqa: BLE001 - usually no <notebook>
                _logger.warning(
                    'Apertur: could not add tab to %s (%s)',
                    model.model, exc,
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

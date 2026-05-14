import json
import logging

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AperturSession(models.Model):
    _name = 'apertur.session'
    _description = 'Apertur Photo Session'
    _order = 'create_date desc'
    _rec_name = 'name'

    name = fields.Char(
        string='Session UUID',
        readonly=True,
        copy=False,
        index=True,
    )
    upload_url = fields.Char(
        string='Upload URL',
        readonly=True,
        copy=False,
    )
    qr_url = fields.Char(
        string='QR Code URL',
        readonly=True,
        copy=False,
    )
    entity_ref = fields.Char(
        string='Entity Ref',
        readonly=True,
        index=True,
        help='Apertur entity reference (e.g. odoo:res.partner:42).',
    )
    res_model = fields.Char(
        string='Related Model',
        readonly=True,
        index=True,
    )
    res_id = fields.Integer(
        string='Related Record ID',
        readonly=True,
        index=True,
    )
    mode = fields.Selection(
        selection=[
            ('contact', 'Send to Contact'),
            ('internal', 'Internal Attachment'),
            ('public', 'Public Message'),
        ],
        string='Mode',
        default='contact',
        required=True,
        help='Controls how incoming images are posted on the related '
             'record:\n'
             ' - Send to Contact: notify the contact and post publicly\n'
             ' - Internal Attachment: attach as internal note\n'
             ' - Public Message: attach as a public chatter message',
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('active', 'Active'),
            ('completed', 'Completed'),
            ('expired', 'Expired'),
            ('closed', 'Closed'),
        ],
        string='Status',
        default='draft',
        readonly=True,
    )
    max_images = fields.Integer(
        string='Max Images',
        default=10,
    )
    image_count = fields.Integer(
        string='Images Received',
        default=0,
        readonly=True,
    )
    created_by = fields.Many2one(
        comodel_name='res.users',
        string='Created By',
        default=lambda self: self.env.uid,
        readonly=True,
    )
    expire_date = fields.Datetime(
        string='Expires At',
        readonly=True,
    )
    delivery_status = fields.Char(
        string='Last Delivery Status',
        readonly=True,
        help='Last known delivery status returned by the Apertur API.',
    )
    delivery_details = fields.Text(
        string='Delivery Details',
        readonly=True,
        help='Per-image delivery status (JSON).',
    )
    is_sandbox = fields.Boolean(
        string='Sandbox',
        compute='_compute_is_sandbox',
        help='True when the configured API key is a test/sandbox key.',
    )
    attachment_ids = fields.One2many(
        comodel_name='ir.attachment',
        compute='_compute_attachment_ids',
        string='Attachments',
    )

    def _compute_is_sandbox(self):
        api_key = self.env['ir.config_parameter'].sudo().get_param(
            'apertur.api_key', default=''
        )
        sandbox = api_key.startswith('aptr_test_')
        for record in self:
            record.is_sandbox = sandbox

    def _compute_attachment_ids(self):
        Attachment = self.env['ir.attachment']
        for record in self:
            if not record.res_model or not record.res_id:
                record.attachment_ids = Attachment
                continue
            record.attachment_ids = Attachment.search([
                ('res_model', '=', record.res_model),
                ('res_id', '=', record.res_id),
                ('description', '=like', 'apertur:%'),
            ])

    # ------------------------------------------------------------------
    # API helpers
    # ------------------------------------------------------------------

    def _get_api_headers(self):
        """Return the HTTP headers for Apertur API requests."""
        ICP = self.env['ir.config_parameter'].sudo()
        api_key = ICP.get_param('apertur.api_key', default='')
        if not api_key:
            raise UserError(_(
                'Apertur API key is not configured. '
                'Go to Settings > Apertur to set it up.'
            ))
        return {
            'Authorization': 'Bearer %s' % api_key,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

    def _get_base_url(self):
        """Return the resolved Apertur API base URL."""
        return self.env['res.config.settings'].get_apertur_base_url()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_create_session(self, res_model, res_id, max_images=None,
                              mode='contact'):
        """Call the Apertur API to create a new upload session.

        :param str res_model: Odoo model name (e.g. ``res.partner``).
        :param int res_id: record ID in *res_model*.
        :param int max_images: optional cap on the number of images.
        :param str mode: one of ``contact``, ``internal``, ``public``.
        :returns: the newly-created ``apertur.session`` record.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        if max_images is None:
            max_images = int(
                ICP.get_param('apertur.default_max_images', default='10')
            )

        if mode not in ('contact', 'internal', 'public'):
            mode = 'contact'

        entity_ref = 'odoo:%s:%s' % (res_model, res_id)
        base_url = self._get_base_url()
        headers = self._get_api_headers()

        payload = {
            'max_images': max_images,
            'tags': [entity_ref],
            'metadata': {
                'odoo': {
                    'model': res_model,
                    'res_id': res_id,
                    'mode': mode,
                },
            },
        }

        try:
            resp = requests.post(
                '%s/api/v1/upload-sessions' % base_url,
                headers=headers,
                data=json.dumps(payload),
                timeout=15,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            _logger.error('Apertur API error: %s', exc)
            raise UserError(_(
                'Failed to create Apertur session. '
                'Please check your API key and network connection.\n\n%s'
            ) % exc) from exc

        data = resp.json()

        session = self.create({
            'name': data.get('uuid', '') or data.get('id', ''),
            'upload_url': data.get('upload_url', ''),
            'qr_url': data.get('qr_url', ''),
            'entity_ref': entity_ref,
            'res_model': res_model,
            'res_id': res_id,
            'state': 'active',
            'mode': mode,
            'max_images': max_images,
            'expire_date': data.get('expires_at'),
        })

        return session

    def action_send_link(self, partner_id=None):
        """Send the upload link to a partner via a chatter message.

        :param int partner_id: ``res.partner`` ID that should receive the
            message.  When *None*, the method attempts to use the linked
            record if it is a ``res.partner``.
        """
        self.ensure_one()
        if not self.upload_url:
            raise UserError(_('This session has no upload URL.'))

        if partner_id is None and self.res_model == 'res.partner':
            partner_id = self.res_id

        if not partner_id:
            raise UserError(_(
                'No partner specified to receive the upload link.'
            ))

        partner = self.env['res.partner'].browse(partner_id)
        if not partner.exists():
            raise UserError(_('The specified partner does not exist.'))

        # Post the link on the related record's chatter
        target_record = self.env[self.res_model].browse(self.res_id)
        if hasattr(target_record, 'message_post'):
            target_record.message_post(
                body=_(
                    '<p>Upload photos here: '
                    '<a href="%(url)s" target="_blank">%(url)s</a></p>'
                ) % {'url': self.upload_url},
                partner_ids=[partner_id],
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )

    def action_expire(self):
        """Mark sessions as expired."""
        self.filtered(lambda s: s.state == 'active').write({
            'state': 'expired',
        })

    def action_close_session(self):
        """Close the session manually.

        This is the user-facing counterpart of :meth:`action_expire`.
        Form-view buttons should call this method with a confirmation
        dialog to prevent accidental closures.
        """
        for record in self:
            if record.state in ('active', 'draft'):
                record.write({'state': 'closed'})
        return True

    def action_refresh_delivery_status(self):
        """Poll the Apertur API for the delivery status of this session.

        Updates ``delivery_status`` (summary) and ``delivery_details``
        (JSON) on the record.
        """
        self.ensure_one()
        if not self.name:
            raise UserError(_('This session has no UUID yet.'))

        base_url = self._get_base_url()
        headers = self._get_api_headers()
        try:
            resp = requests.get(
                '%s/api/v1/upload-sessions/%s/delivery-status' % (
                    base_url, self.name,
                ),
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            _logger.error('Apertur API error (delivery-status): %s', exc)
            raise UserError(_(
                'Failed to refresh delivery status.\n\n%s'
            ) % exc) from exc

        records = resp.json() or []
        # Summarize: "<delivered>/<total>" and worst status wins
        total = len(records)
        delivered = 0
        failed = 0
        pending = 0
        for rec in records:
            dests = rec.get('destinations') or []
            status = dests[0].get('status', 'pending') if dests else 'pending'
            if status == 'delivered':
                delivered += 1
            elif status == 'failed':
                failed += 1
            else:
                pending += 1

        if failed:
            summary = _('%(failed)s failed, %(delivered)s delivered, '
                        '%(pending)s pending (of %(total)s)') % {
                'failed': failed, 'delivered': delivered,
                'pending': pending, 'total': total,
            }
        elif pending:
            summary = _('%(delivered)s delivered, %(pending)s pending '
                        '(of %(total)s)') % {
                'delivered': delivered, 'pending': pending, 'total': total,
            }
        elif total:
            summary = _('%(delivered)s delivered') % {
                'delivered': delivered,
            }
        else:
            summary = _('No images yet')

        self.write({
            'delivery_status': summary,
            'delivery_details': json.dumps(records, ensure_ascii=False),
        })
        return True

    # ------------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------------

    @api.model
    def _cron_expire_sessions(self):
        """Expire sessions that are past their expiration date."""
        expired = self.search([
            ('state', '=', 'active'),
            ('expire_date', '!=', False),
            ('expire_date', '<', fields.Datetime.now()),
        ])
        if expired:
            expired.write({'state': 'expired'})
            _logger.info(
                'Apertur: expired %d session(s).', len(expired)
            )

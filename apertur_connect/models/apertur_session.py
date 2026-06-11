import base64
import json
import logging
from datetime import datetime, timezone

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

        destination_id = ICP.get_param('apertur.destination_id', default='')
        if not destination_id:
            raise UserError(_(
                'Apertur Destination ID is not configured. '
                'Go to Settings > Apertur, create a destination of type '
                '"odoo" in the Apertur dashboard, and paste its ID.'
            ))

        payload = {
            'max_images': max_images,
            'tags': [entity_ref],
            'destination_ids': [destination_id],
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
        except requests.HTTPError as exc:
            self._raise_session_api_error(exc, destination_id)
        except requests.RequestException as exc:
            _logger.error('Apertur API error: %s', exc)
            raise UserError(_(
                'Could not reach Apertur. Please check your network '
                'connection and the API base URL.\n\n%s'
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
            'expire_date': self._parse_api_datetime(data.get('expires_at')),
        })

        return session

    @staticmethod
    def _parse_api_datetime(value):
        """Parse an ISO-8601 timestamp from the Apertur API (e.g.
        ``2026-06-12T09:44:41.919Z``) into a naive UTC ``datetime`` suitable
        for an Odoo Datetime field, which expects ``%Y-%m-%d %H:%M:%S`` with
        no timezone. Returns ``False`` when empty or unparseable.
        """
        if not value:
            return False
        text = value.strip()
        try:
            # fromisoformat handles fractional seconds and offsets; it does
            # not accept a trailing "Z" before Python 3.11, so normalise it.
            dt = datetime.fromisoformat(text.replace('Z', '+00:00'))
        except ValueError:
            # Best-effort fallback: drop the "T", fractional seconds and any
            # offset, then parse as a naive (UTC) datetime.
            base = text.replace('T', ' ').rstrip('Z')
            base = base.split('.', 1)[0].split('+', 1)[0].strip()
            try:
                return datetime.strptime(base, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                _logger.warning(
                    'Apertur: could not parse expires_at %r', value,
                )
                return False
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt

    @staticmethod
    def _raise_session_api_error(exc, destination_id):
        """Translate an HTTP error from the session-creation API into a
        specific :class:`UserError`, distinguishing API-key problems from
        destination problems (mirrors how delivery destinations surface
        auth vs. config errors separately).
        """
        response = exc.response
        status = response.status_code if response is not None else None

        message = ''
        try:
            message = (response.json() or {}).get('message', '') if response is not None else ''
        except (ValueError, AttributeError):
            message = response.text if response is not None else ''

        _logger.error(
            'Apertur session API error (HTTP %s): %s', status, message or exc,
        )

        # 401/403 → the API key is missing, revoked, or for the wrong
        # environment.
        if status in (401, 403):
            raise UserError(_(
                'Apertur rejected your API key (HTTP %(status)s). Check the '
                'API key in Settings > Apertur — make sure it is active and '
                'matches the right environment (live vs. test).\n\n%(message)s'
            ) % {'status': status, 'message': message}) from exc

        # A validation error mentioning the destination → the configured
        # Destination ID is wrong, inactive, or not of type "odoo".
        if status in (400, 404, 422) and 'destination' in (message or '').lower():
            raise UserError(_(
                'Apertur rejected the Destination ID (HTTP %(status)s). Open '
                'Settings > Apertur and verify the Destination ID matches an '
                'active destination of type "odoo" in your Apertur dashboard '
                '(currently configured: %(dest)s).\n\n%(message)s'
            ) % {
                'status': status,
                'dest': destination_id or _('not set'),
                'message': message,
            }) from exc

        raise UserError(_(
            'Failed to create Apertur session (HTTP %(status)s).\n\n%(message)s'
        ) % {'status': status, 'message': message or str(exc)}) from exc

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

        # The endpoint returns a snapshot object:
        #   {"status": ..., "lastChanged": ..., "files": [
        #       {"record_id": ..., "filename": ...,
        #        "destinations": [{"status": "sent|pending|sending|
        #                          retrying|failed", ...}]}]}
        payload = resp.json() or {}
        files = payload.get('files', []) if isinstance(payload, dict) else []

        # Summarize per uploaded file. A file counts as delivered as soon as
        # any of its destinations reports "sent" (the API's success status);
        # failed only when every destination failed; otherwise pending.
        total = len(files)
        delivered = 0
        failed = 0
        pending = 0
        delivered_files = []  # (record_id, filename) to attach
        for f in files:
            f = f or {}
            dests = f.get('destinations') or []
            statuses = [
                d.get('status') for d in dests if isinstance(d, dict)
            ]
            if 'sent' in statuses:
                delivered += 1
                if f.get('record_id'):
                    delivered_files.append(
                        (f['record_id'], f.get('filename')),
                    )
            elif statuses and all(s == 'failed' for s in statuses):
                failed += 1
            else:
                pending += 1

        # Reconcile: download + attach any delivered image that is not yet on
        # the linked record. This covers webhook pushes that never landed
        # (e.g. a transient download failure on the plugin side), making the
        # button a "re-sync everything" action.
        attached = 0
        download_error = None
        for record_id, filename in delivered_files:
            result = self._ingest_delivered_image(record_id, filename)
            if result in ('created', 'exists'):
                attached += 1
            elif download_error is None:
                download_error = result  # remember the first error

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

        # Surface a download problem so the user understands why images are
        # reported as delivered but not visible on the record.
        if delivered and attached < delivered and download_error:
            summary = _(
                '%(summary)s — %(missing)s image(s) could not be downloaded '
                '(%(error)s). Check the API Base URL and API key in '
                'Settings > Apertur.'
            ) % {
                'summary': summary,
                'missing': delivered - attached,
                'error': download_error,
            }

        vals = {
            'delivery_status': summary,
            'delivery_details': json.dumps(payload, ensure_ascii=False),
            # Reflect what is actually attached on the record.
            'image_count': attached,
        }
        if self.max_images and attached >= self.max_images \
                and self.state == 'active':
            vals['state'] = 'completed'
        self.write(vals)
        return True

    def _ingest_delivered_image(self, record_id, filename=None):
        """Download a delivered image from Apertur and attach it to this
        session's linked record, unless it is already attached.

        :returns: ``'created'`` when a new attachment was made, ``'exists'``
            when one was already present, or an error message string when the
            download/attach failed.
        """
        self.ensure_one()
        if not record_id:
            return _('missing record id')
        if not self.res_model or not self.res_id:
            return _('session has no linked record')

        Attachment = self.env['ir.attachment'].sudo()
        desc = 'apertur:%s' % record_id
        existing = Attachment.search([
            ('res_model', '=', self.res_model),
            ('res_id', '=', self.res_id),
            ('description', '=', desc),
        ], limit=1)
        if existing:
            return 'exists'

        base_url = self._get_base_url()
        api_key = self.env['ir.config_parameter'].sudo().get_param(
            'apertur.api_key', default='',
        )
        try:
            resp = requests.get(
                '%s/api/v1/uploads/%s/download' % (base_url, record_id),
                headers={'Authorization': 'Bearer %s' % api_key},
                timeout=30,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            status = getattr(
                getattr(exc, 'response', None), 'status_code', None,
            )
            _logger.warning(
                'Apertur: download failed for %s: %s', record_id, exc,
            )
            return _('HTTP %s') % status if status else str(exc)

        target = self.env[self.res_model].sudo().browse(self.res_id)
        if not target.exists():
            return _('linked record not found')

        mimetype = (resp.headers.get('Content-Type') or '').split(';')[0].strip()
        attachment = Attachment.create({
            'name': filename or ('%s.jpg' % record_id),
            'datas': base64.b64encode(resp.content).decode('ascii'),
            'res_model': self.res_model,
            'res_id': self.res_id,
            'mimetype': mimetype or 'image/jpeg',
            'description': desc,
        })
        if hasattr(target, 'message_post'):
            self._post_image_to_record(target, attachment)
        return 'created'

    @api.model
    def _apertur_contact_partner_id(self, target):
        """Resolve the partner to credit as the chatter author in
        "contact" mode: the record itself when it is a ``res.partner``,
        otherwise its ``partner_id`` if any. Returns an int id or False.
        """
        if target._name == 'res.partner':
            return target.id
        partner = getattr(target, 'partner_id', False)
        return partner.id if partner else False

    def _post_image_to_record(self, target, attachment):
        """Post *attachment* to *target*'s chatter according to ``mode``
        (mirrors the webhook controller's behaviour).
        """
        self.ensure_one()
        body = _('<p>Photo received via Apertur</p>')
        mode = self.mode or 'contact'
        if mode == 'internal':
            target.message_post(
                body=body, attachment_ids=[attachment.id],
                message_type='comment', subtype_xmlid='mail.mt_note',
            )
            return
        if mode == 'public':
            target.message_post(
                body=body, attachment_ids=[attachment.id],
                message_type='comment', subtype_xmlid='mail.mt_comment',
            )
            return
        # mode == 'contact': credit the contact as the message author.
        kwargs = {
            'body': body,
            'attachment_ids': [attachment.id],
            'message_type': 'comment',
            'subtype_xmlid': 'mail.mt_comment',
        }
        author_id = self._apertur_contact_partner_id(target)
        if author_id:
            kwargs['author_id'] = author_id
        target.message_post(**kwargs)

    # ------------------------------------------------------------------
    # Capture entry point (shared by res.partner buttons + bound actions)
    # ------------------------------------------------------------------

    @api.model
    def action_capture_for(self, res_model, res_id, mode='contact'):
        """Create a capture session for an arbitrary record and return an
        action that opens the session form (with its upload widget).

        Used both by the res.partner form buttons and by the model-bound
        server actions generated from the "Enabled Models" setting, so any
        installed model can drive a capture without a code change.
        """
        if mode not in ('contact', 'internal', 'public'):
            mode = 'contact'
        session = self.action_create_session(res_model, int(res_id), mode=mode)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Apertur Session'),
            'res_model': 'apertur.session',
            'res_id': session.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    @api.model
    def action_open_sessions(self):
        """Open the Apertur sessions list.

        When no Apertur API key has been configured yet, redirect the
        user to the Apertur configuration instead: sessions cannot be
        created or delivered without a key, so landing on an empty list
        would be a dead end.
        """
        api_key = self.env['ir.config_parameter'].sudo().get_param(
            'apertur.api_key'
        )
        if not api_key:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Apertur Configuration'),
                'res_model': 'res.config.settings',
                'view_mode': 'form',
                'target': 'inline',
                'context': {'module': 'apertur_connect'},
            }
        return self.env['ir.actions.act_window']._for_xml_id(
            'apertur_connect.apertur_session_action'
        )

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

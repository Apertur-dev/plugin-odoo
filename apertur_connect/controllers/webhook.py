import base64
import hashlib
import hmac
import json
import logging

import requests

from odoo import _, http
from odoo.http import request

_logger = logging.getLogger(__name__)

# Webhook event topics that contain image data we should attach.
_IMAGE_TOPICS = {
    'project.upload.image.uploaded',
    'project.upload.image.delivered',
    'image.uploaded',
    'image.delivered',
}


class AperturWebhookController(http.Controller):

    @http.route(
        '/apertur/webhook',
        type='json',
        auth='none',
        methods=['POST'],
        csrf=False,
    )
    def webhook(self):
        """Receive and process Apertur webhook events.

        Expected payload structure::

            {
                "topic": "image.delivered",
                "data": {
                    "id": "img_abc123",
                    "filename": "photo.jpg",
                    "size_bytes": 123456,
                    "mime_type": "image/jpeg",
                    "session_id": "sess_...",
                    "download_url": "https://...",
                    "tags": ["odoo:res.partner:42"],
                    "metadata": {
                        "odoo": {
                            "model": "res.partner",
                            "res_id": 42,
                            "mode": "contact"
                        }
                    }
                }
            }
        """
        # 1. Read raw body and signature header --------------------------
        raw_body = request.httprequest.get_data(as_text=True)
        signature_header = request.httprequest.headers.get(
            'X-Apertur-Signature', ''
        )

        # 2. Verify HMAC-SHA256 signature --------------------------------
        ICP = request.env['ir.config_parameter'].sudo()
        secret = ICP.get_param('apertur.webhook_secret', default='')

        if secret:
            if not self._verify_signature(raw_body, signature_header, secret):
                _logger.warning(
                    'Apertur webhook: invalid signature — rejecting request.'
                )
                return {'status': 'error', 'message': 'Invalid signature'}

        # 3. Parse event --------------------------------------------------
        try:
            payload = json.loads(raw_body)
        except (json.JSONDecodeError, TypeError):
            _logger.warning('Apertur webhook: malformed JSON body.')
            return {'status': 'error', 'message': 'Invalid JSON'}

        topic = payload.get('topic', '')
        data = payload.get('data', {})

        _logger.info('Apertur webhook received: topic=%s', topic)

        if topic not in _IMAGE_TOPICS:
            # Acknowledge but do nothing for topics we don't handle.
            return {'status': 'ok', 'message': 'Event ignored'}

        # 4. Resolve the related session (to read mode/metadata) ----------
        session_uuid = data.get('session_id', '')
        session = None
        if session_uuid:
            session = (
                request.env['apertur.session']
                .sudo()
                .search([('name', '=', session_uuid)], limit=1)
            )

        # 5. Resolve entity ref (prefer session → metadata → tags) --------
        res_model = None
        res_id = None

        if session and session.res_model and session.res_id:
            res_model = session.res_model
            res_id = session.res_id

        if not res_model:
            meta = (data.get('metadata') or {}).get('odoo') or {}
            if meta.get('model') and meta.get('res_id'):
                try:
                    res_model = meta['model']
                    res_id = int(meta['res_id'])
                except (TypeError, ValueError):
                    res_model, res_id = None, None

        if not res_model:
            tag_ref = self._extract_entity_ref(data.get('tags', []))
            if tag_ref:
                res_model, res_id = tag_ref

        if not res_model or not res_id:
            _logger.info(
                'Apertur webhook: no odoo entity ref found — skipping.'
            )
            return {'status': 'ok', 'message': 'No entity ref'}

        # 6. Determine mode (from session, metadata, or default) ----------
        mode = 'contact'
        if session and session.mode:
            mode = session.mode
        else:
            meta_mode = (
                (data.get('metadata') or {}).get('odoo') or {}
            ).get('mode')
            if meta_mode in ('contact', 'internal', 'public'):
                mode = meta_mode

        # 7. Download image from Apertur ---------------------------------
        download_url = data.get('download_url', '')
        filename = data.get('filename', 'photo.jpg')
        mime_type = data.get('mime_type', 'image/jpeg')

        image_data = None
        if download_url:
            image_data = self._download_image(download_url)

        if not image_data:
            # If no direct download URL, try to build one from the image ID.
            image_id = data.get('id', '')
            if image_id:
                base_url = (
                    request.env['res.config.settings']
                    .get_apertur_base_url()
                )
                api_key = ICP.get_param('apertur.api_key', default='')
                image_data = self._download_image(
                    '%s/api/v1/uploads/%s/download' % (base_url, image_id),
                    api_key=api_key,
                )

        if not image_data:
            _logger.warning(
                'Apertur webhook: could not download image for event %s.',
                data.get('id', '?'),
            )
            if session:
                session.write({
                    'delivery_status': _('Download failed for %s') % filename,
                })
            return {'status': 'error', 'message': 'Image download failed'}

        # 8. Create ir.attachment ----------------------------------------
        target = request.env[res_model].sudo().browse(res_id)
        if not target.exists():
            _logger.warning(
                'Apertur webhook: record %s(%s) does not exist.',
                res_model, res_id,
            )
            return {'status': 'error', 'message': 'Record not found'}

        attachment = request.env['ir.attachment'].sudo().create({
            'name': filename,
            'datas': base64.b64encode(image_data).decode('ascii'),
            'res_model': res_model,
            'res_id': res_id,
            'mimetype': mime_type,
            'description': 'apertur:%s' % data.get('id', ''),
        })

        # 9. Post chatter message based on mode --------------------------
        if hasattr(target, 'message_post'):
            self._post_message_for_mode(target, attachment, mode, session)

        # 10. Update session counters / status ---------------------------
        if session:
            new_count = (session.image_count or 0) + 1
            vals = {
                'image_count': new_count,
                'delivery_status': _('Last image delivered: %s') % filename,
            }
            if session.max_images and new_count >= session.max_images:
                vals['state'] = 'completed'
            session.write(vals)

        return {'status': 'ok'}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _post_message_for_mode(target, attachment, mode, session=None):
        """Post the image to the target's chatter according to *mode*.

        - ``contact``: public comment that notifies the related partner
          (the target itself when it is a ``res.partner``).
        - ``internal``: internal note (``mail.mt_note``) visible only to
          followers with internal access.
        - ``public``: public comment (``mail.mt_comment``) without
          explicit partner notification.
        """
        body = _('<p>Photo received via Apertur</p>')

        if mode == 'internal':
            target.message_post(
                body=body,
                attachment_ids=[attachment.id],
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )
            return

        if mode == 'public':
            target.message_post(
                body=body,
                attachment_ids=[attachment.id],
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )
            return

        # mode == 'contact' (default)
        partner_ids = []
        # If target is a partner, notify them directly. Otherwise
        # Odoo will notify the record's followers as usual.
        if target._name == 'res.partner':
            partner_ids = [target.id]

        target.message_post(
            body=body,
            attachment_ids=[attachment.id],
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
            partner_ids=partner_ids,
        )

    @staticmethod
    def _verify_signature(raw_body, signature_header, secret):
        """Verify the HMAC-SHA256 signature.

        The header format is ``sha256=<hex_digest>``.
        """
        expected = hmac.new(
            secret.encode('utf-8'),
            raw_body.encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()

        provided = signature_header
        if provided.startswith('sha256='):
            provided = provided[7:]

        return hmac.compare_digest(expected, provided)

    @staticmethod
    def _extract_entity_ref(tags):
        """Find and parse the first ``odoo:<model>:<id>`` tag.

        :returns: ``(model, id)`` tuple or *None*.
        """
        for tag in tags:
            if tag.startswith('odoo:'):
                parts = tag.split(':')
                if len(parts) == 3:
                    try:
                        return (parts[1], int(parts[2]))
                    except (ValueError, IndexError):
                        continue
        return None

    @staticmethod
    def _download_image(url, api_key=None):
        """Download an image from *url* and return the raw bytes."""
        headers = {}
        if api_key:
            headers['Authorization'] = 'Bearer %s' % api_key

        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as exc:
            _logger.error('Apertur: failed to download image: %s', exc)
            return None

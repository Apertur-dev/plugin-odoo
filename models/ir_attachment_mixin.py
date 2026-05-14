from odoo import _, fields, models


class AperturCaptureMixin(models.AbstractModel):
    """Mixin that adds Apertur photo-capture capabilities to any model.

    Inherit this mixin on models where you want the "Collect photos"
    button to appear::

        class ProjectTask(models.Model):
            _inherit = ['project.task', 'apertur.capture.mixin']
    """

    _name = 'apertur.capture.mixin'
    _description = 'Apertur Capture Mixin'

    apertur_session_ids = fields.One2many(
        comodel_name='apertur.session',
        compute='_compute_apertur_session_ids',
        string='Apertur Sessions',
    )
    apertur_image_count = fields.Integer(
        compute='_compute_apertur_image_count',
        string='Apertur Photos',
    )

    def _compute_apertur_session_ids(self):
        Session = self.env['apertur.session']
        for record in self:
            record.apertur_session_ids = Session.search([
                ('res_model', '=', record._name),
                ('res_id', '=', record.id),
            ])

    def _compute_apertur_image_count(self):
        Attachment = self.env['ir.attachment']
        for record in self:
            record.apertur_image_count = Attachment.search_count([
                ('res_model', '=', record._name),
                ('res_id', '=', record.id),
                ('description', '=like', 'apertur:%'),
            ])

    def action_apertur_capture(self, mode='contact'):
        """Create an Apertur session linked to this record and return
        a form action that displays the session (with its upload widget).

        :param str mode: one of ``contact``, ``internal``, ``public``.
        """
        self.ensure_one()
        if mode not in ('contact', 'internal', 'public'):
            mode = 'contact'
        session = self.env['apertur.session'].action_create_session(
            res_model=self._name,
            res_id=self.id,
            mode=mode,
        )
        return {
            'type': 'ir.actions.act_window',
            'name': _('Apertur Session'),
            'res_model': 'apertur.session',
            'res_id': session.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_apertur_capture_contact(self):
        return self.action_apertur_capture(mode='contact')

    def action_apertur_capture_internal(self):
        return self.action_apertur_capture(mode='internal')

    def action_apertur_capture_public(self):
        return self.action_apertur_capture(mode='public')


class ResPartner(models.Model):
    """Extend res.partner with Apertur capture capabilities."""

    _name = 'res.partner'
    _inherit = ['res.partner', 'apertur.capture.mixin']

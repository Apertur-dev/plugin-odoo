from odoo import fields, models


class MailThread(models.AbstractModel):
    """Add Apertur photo-capture capability to every chatter-enabled model.

    By extending ``mail.thread`` (rather than a standalone mixin inherited on
    one model), any model that has a chatter — res.partner, crm.lead,
    project.task, … — gains the capture fields and actions. The "Enabled
    Models" setting then surfaces them (Action-menu entries + a notebook tab)
    without a code change per model.
    """

    _inherit = 'mail.thread'

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
            # New (unsaved) records have a NewId — nothing to look up yet.
            if isinstance(record.id, int):
                record.apertur_session_ids = Session.search([
                    ('res_model', '=', record._name),
                    ('res_id', '=', record.id),
                ])
            else:
                record.apertur_session_ids = Session

    def _compute_apertur_image_count(self):
        Attachment = self.env['ir.attachment']
        for record in self:
            if isinstance(record.id, int):
                record.apertur_image_count = Attachment.search_count([
                    ('res_model', '=', record._name),
                    ('res_id', '=', record.id),
                    ('description', '=like', 'apertur:%'),
                ])
            else:
                record.apertur_image_count = 0

    def action_apertur_capture(self, mode='contact'):
        """Create an Apertur session for this record and open it (widget)."""
        self.ensure_one()
        return self.env['apertur.session'].action_capture_for(
            self._name, self.id, mode,
        )

    def action_apertur_capture_contact(self):
        return self.action_apertur_capture(mode='contact')

    def action_apertur_capture_internal(self):
        return self.action_apertur_capture(mode='internal')

    def action_apertur_capture_public(self):
        return self.action_apertur_capture(mode='public')

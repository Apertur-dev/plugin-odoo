==========================
Apertur Photo Collection
==========================

Integrate Apertur (https://apertur.ca) photo collection into Odoo.
Generate a QR code from any contact, task or ticket and let the
recipient upload photos from a mobile device. Received images are
attached to the record and posted to the chatter automatically.

.. contents::
   :local:

Requirements
============

* Odoo 16, 17, 18 or 19 (one matching branch of this module per version)
* Python package ``requests`` (declared in ``external_dependencies``)
* An Apertur account at https://apertur.ca

A free tier is available: 5 sessions per month, 10 images per session,
5 MB per image, 12-hour session expiry, 1 active destination. Paid
plans (Starter, Pro, Business, Unlimited) unlock higher limits,
password-protected sessions, custom branding and end-to-end encryption.

Installation
============

1. Copy the ``apertur_connect`` folder into your Odoo addons path.
2. Restart Odoo and update the apps list.
3. Install **Apertur Photo Collection** from the Apps menu.

Configuration
=============

1. Create an Apertur account at https://apertur.ca.
2. In Odoo, go to **Settings > Apertur**.
3. Enter your API key (``aptr_live_*`` or ``aptr_test_*``).
4. Set a webhook secret.
5. Copy the webhook URL shown in settings and register it as a
   destination in your Apertur dashboard.

Usage
=====

Collecting photos from a contact
--------------------------------

1. Open a contact form.
2. Go to the **Apertur** tab.
3. Click **Collect Photos** to create a session.
4. Share the QR code or link with the contact.
5. Received photos are automatically attached to the record.

Webhook
-------

The module exposes ``/apertur/webhook`` for image delivery events.
Each request is verified using HMAC-SHA256 with the webhook secret
configured in Settings. Verified images are downloaded, attached to
the linked record as ``ir.attachment``, and a chatter notification
is posted.

Data and privacy
================

This module is a thin integration with Apertur's SaaS API. The
module sends the entity reference (model + record id) and your API
key to ``https://api.apertur.ca`` when creating a session. Uploaded
photos are stored on Apertur's infrastructure and delivered back to
your Odoo instance via signed webhook. You retain full ownership of
your data and can delete it from your Apertur dashboard at any time.
No analytics or telemetry are sent from this module.

Support
=======

* Email: support@apertur.ca
* Documentation: https://apertur.ca/docs/plugins/odoo

License
=======

LGPL-3 (see the ``LICENSE`` file in this module).

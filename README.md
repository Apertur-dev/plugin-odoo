# Apertur Connect for Odoo

Odoo module that integrates [Apertur](https://apertur.ca) photo collection into Odoo CRM/ERP.

Collect photos from mobile devices via QR code directly from contact, task, or ticket records.

## Requirements

- Odoo 16, 17, or 18
- An Apertur account with an API key

## Installation

1. Copy the `apertur_connect` folder (this directory) into your Odoo addons path.
2. Restart Odoo and update the apps list.
3. Install **Apertur - Photo Collection** from the Apps menu.

## Configuration

1. Go to **Settings > Apertur**.
2. Enter your API key (starts with `aptr_live_` or `aptr_test_`).
3. Set a webhook secret.
4. Configure the webhook URL shown in settings as a destination in your Apertur dashboard.

## Usage

### Collecting photos from a contact

1. Open a contact form.
2. Go to the **Apertur** tab.
3. Click **Collect Photos** to create a session.
4. Share the QR code or link with the contact.
5. Received photos are automatically attached to the record.

### Webhook integration

When configured, Apertur sends image events to `/apertur/webhook`. The module:

- Verifies the HMAC-SHA256 signature
- Downloads the image
- Creates an `ir.attachment` on the linked record
- Posts a chatter notification

## License

MIT

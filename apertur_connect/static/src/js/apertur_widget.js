/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * AperturCaptureWidget -- OWL component that renders the Apertur upload
 * widget inside an iframe. It reads the session UUID from the current
 * record and constructs the appropriate widget URL.
 *
 * The component communicates with the iframe via `window.postMessage` to
 * receive image-received events and updates the Odoo UI accordingly.
 */
export class AperturCaptureWidget extends Component {
    static template = "apertur_connect.AperturCaptureWidget";
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.rpc = useService("rpc");
        this.notification = useService("notification");
        this.iframeRef = useRef("aperturIframe");

        // Expose translatable labels for the XML template
        this.labels = {
            loading: _t("Loading Apertur widget..."),
            header: _t("Apertur Photo Collection"),
            sandbox: _t("Sandbox mode"),
            photosReceived: _t("photo(s) received"),
            photoReceivedToast: _t("Photo received"),
            sessionComplete: _t("Photo collection complete!"),
            genericError: _t("Apertur widget error"),
            loadFailed: _t("Failed to load widget"),
            noSession: _t("No session UUID available."),
        };

        this.state = useState({
            iframeUrl: "",
            imageCount: 0,
            loading: true,
            error: null,
            isSandbox: false,
        });

        this._onMessage = this._onMessage.bind(this);

        onMounted(async () => {
            window.addEventListener("message", this._onMessage);
            await this._buildIframeUrl();
        });

        onWillUnmount(() => {
            window.removeEventListener("message", this._onMessage);
        });
    }

    /**
     * Return the Odoo UI color scheme, either "dark" or "light".
     * Odoo 17+ toggles the ``o_dark_mode`` class on ``document.body``.
     * Falls back to the ``prefers-color-scheme`` media query.
     */
    _getColorScheme() {
        try {
            if (document.body.classList.contains("o_dark_mode")) {
                return "dark";
            }
            if (
                window.matchMedia &&
                window.matchMedia("(prefers-color-scheme: dark)").matches
            ) {
                return "dark";
            }
        } catch (err) {
            // Ignore – default to light.
        }
        return "light";
    }

    /**
     * Build the iframe URL pointing to the Apertur upload page for the
     * current session.
     */
    async _buildIframeUrl() {
        try {
            const sessionUuid = this.props.record.data[this.props.name];
            if (!sessionUuid) {
                this.state.loading = false;
                this.state.error = this.labels.noSession;
                return;
            }

            // Fetch config parameters
            const result = await this.rpc("/web/dataset/call_kw", {
                model: "ir.config_parameter",
                method: "get_param",
                args: ["apertur.api_key"],
                kwargs: {},
            });

            const apiKey = result || "";
            this.state.isSandbox = apiKey.startsWith("aptr_test_");

            // Determine base upload URL from the key prefix
            let widgetBaseUrl;
            if (this.state.isSandbox) {
                widgetBaseUrl = "https://sandbox.apertur.ca";
            } else {
                widgetBaseUrl = "https://apertur.ca";
            }

            const colorScheme = this._getColorScheme();

            // Detect the user's language from the browser / Odoo UI.
            const lang = (
                document.documentElement.getAttribute("lang") ||
                (navigator.language || "en").split(/[-_]/)[0]
            ).toLowerCase();
            const supportedLangs = ["en", "fr", "es"];
            const effectiveLang = supportedLangs.includes(lang) ? lang : "en";

            const params = new URLSearchParams();
            params.set("colorScheme", colorScheme);
            if (effectiveLang !== "en") {
                params.set("lang", effectiveLang);
            }

            // The upload URL follows the pattern: https://apertur.ca/u/<uuid>
            this.state.iframeUrl =
                `${widgetBaseUrl}/u/${sessionUuid}?${params.toString()}`;
            this.state.loading = false;
        } catch (err) {
            this.state.loading = false;
            this.state.error =
                `${this.labels.loadFailed}: ${err.message || err}`;
        }
    }

    /**
     * Handle postMessage events from the Apertur iframe.
     *
     * The widget emits events with the structure:
     *   { type: "apertur:image:received", data: { ... } }
     *   { type: "apertur:session:complete", data: { ... } }
     */
    _onMessage(event) {
        // Only accept messages from known Apertur origins
        const trustedOrigins = [
            "https://apertur.ca",
            "https://sandbox.apertur.ca",
        ];
        if (!trustedOrigins.includes(event.origin)) {
            return;
        }

        const msg = event.data;
        if (!msg || typeof msg !== "object" || !msg.type) {
            return;
        }

        switch (msg.type) {
            case "apertur:image:received":
                this.state.imageCount += 1;
                this.notification.add(
                    `${this.labels.photoReceivedToast} (${this.state.imageCount})`,
                    { type: "success", sticky: false }
                );
                break;

            case "apertur:session:complete":
                this.notification.add(this.labels.sessionComplete, {
                    type: "info",
                    sticky: false,
                });
                // Reload the form to reflect the new attachments
                if (this.props.record && this.props.record.load) {
                    this.props.record.load();
                }
                break;

            case "apertur:error":
                this.notification.add(
                    msg.data?.message || this.labels.genericError,
                    { type: "warning", sticky: false }
                );
                break;
        }
    }
}

// Register as a field widget so it can be used with widget="apertur_capture"
registry.category("fields").add("apertur_capture", {
    component: AperturCaptureWidget,
    supportedTypes: ["char"],
});

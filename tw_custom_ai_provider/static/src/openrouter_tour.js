import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { stepUtils } from "@web_tour/tour_utils";

registry.category("web_tour.tours").add("tw_custom_ai_provider_openrouter", {
    steps: () => [
        stepUtils.showAppsMenuItem(),
        {
            isActive: ["enterprise", ".o_menu_toggle:not(.o_hidden):not(.o_menu_toggle_back)"],
            trigger: ".o_menu_toggle:not(.o_hidden):not(.o_menu_toggle_back)",
            content: _t("Open the apps menu to configure OpenRouter."),
            run: "click",
        },
        {
            trigger: '.o_app[data-menu-xmlid="ai_agentic.ai_menu_root"]',
            content: _t("Let's connect your OpenRouter account. Open the AI app."),
            run: "click",
        },
        {
            trigger: '[data-menu-xmlid="ai_agentic.ai_config_menu"]',
            content: _t("Open Configuration to manage your providers."),
            run: "click",
        },
        {
            trigger: '[data-menu-xmlid="tw_custom_ai_provider.ai_provider_menu_action"]',
            content: _t("Open AI Providers."),
            run: "click",
        },
        {
            trigger: '.o_data_row:has(td[name="technical_name"]:contains("openrouter")) td[name="name"]',
            content: _t("Open the preconfigured OpenRouter provider."),
            run: "click",
        },
        {
            trigger: '.o_field_widget[name="api_key"] input',
            content: _t("Create an API key in your OpenRouter account and paste it here. Requests can send conversation content, images and audio to that provider and may incur charges. Continue only if you are authorized to share this data."),
            run: "edit tour-test-key",
        },
        {
            trigger: 'button[name="action_test_connection"]',
            content: _t("Click Test Connection to save your API key and check access to OpenRouter. If it fails, correct your key and try again."),
            run: "click",
        },
        {
            trigger: '.o_notification_manager:has(.tw_ai_connection_result .bg-success)',
            content: _t("The connection succeeded. Click this confirmation to finish. You can replay the guide from AI > Configuration > OpenRouter Setup Tour."),
            run: "click",
        },
    ],
});

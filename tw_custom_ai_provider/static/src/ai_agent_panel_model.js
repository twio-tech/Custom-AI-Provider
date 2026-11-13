/** @odoo-module */

import { AiAgentPanel } from "@ai_agentic/discuss/core/web/ai_agent_panel/ai_agent_panel";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

patch(AiAgentPanel.prototype, {
    setup() {
        super.setup();
        if (!this.tabs.some((tab) => tab.id === "model")) {
            this.tabs.push({ id: "model", label: _t("Model") });
        }
    },
});

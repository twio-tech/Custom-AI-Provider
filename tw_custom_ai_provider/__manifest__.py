# Copyright 2026 twio.tech AG. See COPYRIGHT for licensing details.
{
    'name': 'AI Custom Providers',
    'version': '20.0.1.5.0',
    'author': "twio.tech AG",
    'website': "https://www.twio.tech",
    'license': 'OPL-1',
    'category': 'Productivity/AI',
    'summary': "Choose your own AI provider: OpenRouter, OpenAI, Gemini",
    'description': """
    AI Custom Providers for Odoo
    =============================
    Connect Odoo AI agents to OpenRouter or a supported OpenAI-compatible
    endpoint using your own provider account. Select a global model or
    individual agent models, with compatible image and transcription models.
    Available features depend on the selected model and endpoint; native
    connectors for individual model vendors are not included.

    Requests send conversation messages, agent instructions, tool definitions,
    tool results and relevant attachments to the configured provider. Image
    and transcription requests may also send images, documents or audio.
    Provider processing and retention terms apply, and usage may incur charges.
    An administrator must authorize data sharing for each provider before
    any connection test or AI request. Agents without an assigned model
    keep using Odoo AI when global routing is disabled.
    """,
    'images': ['static/description/banner.gif'],
    'depends': ['ai', 'ai_agentic', 'web_tour'],
    'data': [
        'data/ai_provider_data.xml',
        'security/ir.access.csv',
        'views/ai_provider_views.xml',
        'views/ai_model_views.xml',
        'views/ai_agent_views.xml',
        'views/menus.xml',
        'views/res_config_settings_views.xml',
        'data/openrouter_tour.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'tw_custom_ai_provider/static/src/**/*',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'application': False,
    'auto_install': False,
    'installable': True,
}

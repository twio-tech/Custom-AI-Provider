# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    'name': 'AI Custom Providers (OpenRouter)',
    'version': '20.0.1.4.1',
    'author': "twio.tech AG",
    'website': "https://www.twio.tech",
    'license': 'OPL-1',
    'category': 'Hidden',
    'summary': "Use OpenRouter or other custom providers with global or per-agent models",
    'description': """
    AI Custom Providers for Odoo
    =============================
    Assign a model from a custom provider to AI agents. Agents with an
    assigned model call the provider directly through the OpenAI-compatible
    API instead of going through the Odoo AI In-App Purchase service, so
    any OpenAI-compatible provider (OpenAI, Anthropic, Gemini, Mistral,
    Groq, OpenRouter, LiteLLM, vLLM, Ollama) can be used. Agents without an
    assigned model keep using Odoo AI when global routing is disabled.
    """,
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

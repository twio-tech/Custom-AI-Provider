# Initialize OpenRouter defaults and offer setup to administrators.
def post_init_hook(env):
    # Step 1: preserve any existing routing settings.
    parameters = env['ir.config_parameter'].sudo()
    if not parameters.search_count([('key', '=', 'tw_custom_ai_provider.use_global_model')]):
        parameters.set_bool('tw_custom_ai_provider.use_global_model', True)
    if not parameters.search_count([('key', '=', 'tw_custom_ai_provider.global_model_id')]):
        parameters.set_int('tw_custom_ai_provider.global_model_id', env.ref('tw_custom_ai_provider.ai_model_openrouter_default').id)
    # Step 2: offer native onboarding even when installation runs as the system user.
    env['res.users'].search([('all_group_ids', 'in', env.ref('base.group_system').ids)]).tour_enabled = True

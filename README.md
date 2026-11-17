# Custom AI Provider for Odoo

Connect Odoo AI agents to OpenRouter and other OpenAI-compatible providers, with global or per-agent model selection, image generation, and audio transcription.

## Features

- Use your own provider account and API credentials.
- Select one global model for all agents or configure models per agent.
- Configure compatible models for image generation and audio transcription.

Claude models are supported through OpenRouter or an OpenAI-compatible gateway. The native Anthropic API is not supported. Its legacy provider example is archived on fresh installations; configure a compatible gateway before activating it. Existing provider settings are preserved on upgrade.

## Requirements

- Odoo 20 Enterprise with the `ai` and `ai_agentic` modules.
- Odoo.sh or a self-hosted Odoo installation.
- Access to a compatible provider and its required credentials.

The module is intended for free distribution. Provider usage and Odoo Enterprise subscriptions may incur separate costs. Odoo Online does not support this Python module.

## Data processing

Requests send conversation messages, agent instructions, tool definitions, tool results and relevant attachments to the configured provider. Image and transcription requests may also send images, documents or audio. Provider processing and retention terms apply, and usage may incur charges.

An administrator must review these terms and explicitly enable **Authorize data sharing** on each provider before connection tests or AI requests. Authorization is off by default, can be revoked at any time, and is not copied with a provider. Changing the API URL or provider identifier clears authorization: save the new endpoint, then authorize again. Existing installations also require authorization after upgrading.

## Publisher

[twio.tech AG](https://www.twio.tech)

## OpenRouter setup tour

After installation, administrators are offered an onboarding tour on the next backend load. It opens AI > Configuration > AI Providers, guides entry of an OpenRouter API key, saves the provider and tests the connection.

Replay it from AI > Configuration > OpenRouter Setup Tour. The tour is restricted to administrators. Enter your own API key; the automated browser test uses a dummy key and mocks the connection check.

Test Connection saves pending provider changes and displays the result in the form and a notification. Changing the API key, URL, provider identifier or active status clears the previous result.

## Database neutralization

Odoo's native neutralization runs `tw_custom_ai_provider/data/neutralize.sql` on a copied database. It clears every provider API key and data-sharing authorization, archives all providers (including keyless endpoints), and resets connection results. Model definitions, URLs and routing selections remain in place. Requests using an archived provider fail; neutralization does not switch them to Odoo IAP credits.

To use AI in the neutralized copy, reactivate the provider and enter a dedicated test API key. Installing or upgrading the module does not execute this script. Existing staging databases need neutralization to be run again or their credentials cleared manually. This script is discovered by Odoo and must not be added to the manifest's `data` list.

## Translations

Source code and source UI text are in English. German translations are provided in `tw_custom_ai_provider/i18n/de.po`, with the export template alongside it. The catalog includes settings, provider forms, onboarding and provider error messages. Third-party provider responses are displayed as received.

Install German in Odoo and select it under your user preferences to use the translation.

## Odoo Apps

The `tw_custom_ai_provider` module is located at the repository root. The branch for Odoo 20 is `20.0`.

Register this repository URL in Odoo Apps after pushing the branch:

```text
ssh://git@github.com/twio-tech/Custom-AI-Provider.git#20.0
```

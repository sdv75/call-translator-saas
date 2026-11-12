"""Report only configuration presence, never values, tokens, hashes or lengths."""

import json

from server.config import PROJECT_ENV, Settings


def summary(settings: Settings):
    return {'project_env_present': PROJECT_ENV.is_file(),
            'google_oidc_configured': bool(settings.google_client_id and settings.google_client_secret),
            'deepgram_configured': bool(settings.deepgram_key),
            'groq_configured': bool(settings.groq_key),
            'experimental_audio_enabled': settings.experimental_audio,
            'sales_enabled': False}


def main():
    try:
        result = summary(Settings.from_env())
    except Exception:
        # A malformed value must not be echoed in exception text/tracebacks.
        print(json.dumps({'configuration_valid': False, 'error': 'invalid_configuration'}))
        return 1
    print(json.dumps({'configuration_valid': True, **result}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

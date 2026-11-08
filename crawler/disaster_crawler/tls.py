"""Verified TLS, including macOS Python installs without a default CA bundle."""
import os
from pathlib import Path
import ssl


def tls_context():
    context = ssl.create_default_context()
    if not context.get_ca_certs() and not any(os.getenv(k) for k in ('SSL_CERT_FILE', 'SSL_CERT_DIR')):
        system_bundle = Path('/etc/ssl/cert.pem')
        if system_bundle.is_file():
            context.load_verify_locations(cafile=str(system_bundle))
        else:
            try:
                import certifi
            except ImportError:
                pass
            else:
                context.load_verify_locations(cafile=certifi.where())
    return context

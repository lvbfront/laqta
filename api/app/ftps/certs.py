from __future__ import annotations

import datetime
import os


def ensure_dev_cert(cert_path: str, key_path: str) -> None:
    """Generates a self-signed cert/key pair at the given paths if neither
    exists yet -- dev/local convenience so `docker compose up` works with
    zero manual cert setup. A real deployment should point
    settings.ftps_cert_file/ftps_key_file at a real cert instead (this
    function is a no-op once files already exist at those paths, so
    swapping in a real cert there is enough).

    Uses the `cryptography` package -- already a transitive dependency via
    python-jose[cryptography] in requirements.txt, so this adds no new
    dependency.
    """
    if os.path.exists(cert_path) and os.path.exists(key_path):
        return

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "laqta-ftps-dev")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .sign(key, hashes.SHA256())
    )

    os.makedirs(os.path.dirname(cert_path) or ".", exist_ok=True)
    os.makedirs(os.path.dirname(key_path) or ".", exist_ok=True)

    with open(key_path, "wb") as f:
        f.write(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

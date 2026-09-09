from __future__ import annotations

import logging
import os

from pyftpdlib.servers import FTPServer

from app.config import settings
from app.ftps.authorizer import EventCredentialAuthorizer
from app.ftps.certs import ensure_dev_cert
from app.ftps.handler import LaqtaFTPSHandler

logger = logging.getLogger(__name__)


def build_server(bind_port: int | None = None) -> FTPServer:
    """Factory, not a module-level singleton -- tests build a second
    server bound to an ephemeral port against the same DB, independent of
    whatever's configured for the "real" docker-compose ftps service.
    """
    ensure_dev_cert(settings.ftps_cert_file, settings.ftps_key_file)
    os.makedirs(settings.ftps_upload_root, exist_ok=True)

    handler_cls = LaqtaFTPSHandler
    handler_cls.certfile = settings.ftps_cert_file
    handler_cls.keyfile = settings.ftps_key_file
    # Explicit TLS (AUTH TLS over the plain control port), not implicit --
    # docs/plan.md allows either; explicit needs no separate listening
    # port for the TLS handshake, which keeps this single-port simple.
    handler_cls.tls_control_required = True
    handler_cls.tls_data_required = True
    handler_cls.authorizer = EventCredentialAuthorizer()
    handler_cls.passive_ports = range(settings.ftps_passive_port_start, settings.ftps_passive_port_end + 1)
    if settings.ftps_masquerade_address:
        handler_cls.masquerade_address = settings.ftps_masquerade_address

    port = bind_port if bind_port is not None else settings.ftps_port
    return FTPServer((settings.ftps_host, port), handler_cls)


def run_server() -> None:
    server = build_server()
    logger.info(
        "FTPS server listening on %s:%s (passive %s-%s)",
        settings.ftps_host,
        settings.ftps_port,
        settings.ftps_passive_port_start,
        settings.ftps_passive_port_end,
    )
    server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_server()

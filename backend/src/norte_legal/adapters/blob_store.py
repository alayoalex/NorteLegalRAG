"""Almacén de bytes en un volumen compartido entre la API y el worker, direccionado por contenido.

La clave es el `sha256`: subir dos veces el mismo archivo no duplica bytes y la escritura es
idempotente. Se escribe en un temporal y se renombra, así un lector nunca ve un archivo a medias.
"""

import os
import tempfile
from pathlib import Path


class LocalBlobStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    @staticmethod
    def key_for(sha256: str) -> str:
        return f"sha256/{sha256[:2]}/{sha256}"

    def put(self, sha256: str, content: bytes) -> str:
        key = self.key_for(sha256)
        path = self._root / key
        if path.exists():
            return key
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, path)
        return key

    def get(self, key: str) -> bytes:
        return (self._root / key).read_bytes()

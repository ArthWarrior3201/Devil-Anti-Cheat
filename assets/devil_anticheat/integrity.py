"""Publisher-signed, streaming file checks. This is not remote attestation."""
import base64
import hashlib
import json
import os
from pathlib import Path
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


class IntegrityError(Exception):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def encode(raw):
    return base64.b64encode(raw).decode("ascii")


def read_json(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise IntegrityError("Manifest/key file exceeds size limit")
    return json.loads(raw)


def create_keys(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False, mode=0o700)
    key = Ed25519PrivateKey.generate()
    for name, data in (("developer-private.json", {"private": encode(key.private_bytes_raw())}),
                       ("developer-public.json", {"public": encode(key.public_key().public_bytes_raw())})):
        with os.fdopen(os.open(folder / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
            stream.write(canonical(data))


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inventory(root):
    root = Path(root).resolve()
    if not root.is_dir():
        raise IntegrityError("Game code folder does not exist")
    files = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise IntegrityError("Symlinks are not allowed in the checked folder")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = file_hash(path)
            if len(files) > 10000:
                raise IntegrityError("Reference manifest limit: 10,000 files")
    return files


def seal(root, private_key_file, output, build="1"):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.is_relative_to(root) or Path(private_key_file).resolve().is_relative_to(root):
        raise IntegrityError("Keep the manifest and developer private key outside the checked folder")
    files = inventory(root)
    if not files:
        raise IntegrityError("Cannot seal an empty folder")
    private = base64.b64decode(read_json(private_key_file)["private"], validate=True)
    key = Ed25519PrivateKey.from_private_bytes(private)
    payload = canonical({"purpose": "devil-anti-cheat-files-v1", "build": str(build), "files": files})
    encoded = canonical({"payload": encode(payload), "signature": encode(key.sign(payload))})
    if len(encoded) > 2 * 1024 * 1024:
        raise IntegrityError("Manifest exceeds size limit")
    with output.open("xb") as stream:
        stream.write(encoded)


class FileGuard:
    def __init__(self, root, manifest_path, public_key):
        self.root = Path(root)
        try:
            envelope = read_json(manifest_path)
            payload = base64.b64decode(envelope["payload"], validate=True)
            Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key, validate=True)).verify(
                base64.b64decode(envelope["signature"], validate=True), payload)
            manifest = json.loads(payload)
            if manifest["purpose"] != "devil-anti-cheat-files-v1" or not isinstance(manifest["files"], dict):
                raise IntegrityError("Wrong manifest type")
            self.expected = manifest["files"]
            self.build = manifest["build"]
        except (InvalidSignature, ValueError, KeyError, TypeError) as exc:
            raise IntegrityError("Manifest signature/format is invalid") from exc

    def check(self):
        actual = inventory(self.root)
        changed = sorted(name for name in self.expected.keys() & actual.keys()
                         if self.expected[name] != actual[name])
        missing = sorted(self.expected.keys() - actual.keys())
        unexpected = sorted(actual.keys() - self.expected.keys())
        return {"ok": not (changed or missing or unexpected), "changed": changed,
                "missing": missing, "unexpected": unexpected, "build": self.build}

    def require_clean(self):
        report = self.check()
        if not report["ok"]:
            raise IntegrityError("Game files differ from the signed build. Repair files before playing.")
        return report

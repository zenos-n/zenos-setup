"""Descriptor-relative publication and conservative rollback of Setup user sources."""

import hashlib
import json
import os
import stat
import sys


def _identity(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def _open_config(record, *, create=False):
    username = record["username"]
    if not username or username in {".", ".."} or "/" in username:
        raise ValueError("invalid canonical username")
    root = os.path.abspath(record["root"])
    parts = [part for part in root.split("/") if part]
    root_depth = len(parts)
    parts += ["Users", username, ".private", "Config"]
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    parents = []
    try:
        for index, part in enumerate(parts):
            made = False
            if create and index >= root_depth:
                try:
                    os.mkdir(part, 0o755 if index == root_depth else 0o700, dir_fd=fd)
                    made = True
                except FileExistsError:
                    pass
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
            )
            os.close(fd)
            fd = child
            if made and index > root_depth and record.get("owner"):
                os.fchown(fd, *record["owner"])
            info = os.fstat(fd)
            parents.append([info.st_dev, info.st_ino])
        if not create and parents != record["parents"]:
            raise ValueError("canonical parent directory changed")
        return fd, parents
    except BaseException:
        os.close(fd)
        raise


def publish(record):
    with open(record["source"], "rb") as original:
        contents = original.read()
    fd, parents = _open_config(record, create=True)
    try:
        out = os.open(
            "main.zcfg",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=fd,
        )
        # On an incomplete write, preserve the file rather than risk deleting a
        # concurrently replaced entry without a completed publication identity.
        with os.fdopen(out, "wb") as target:
            target.write(contents)
            target.flush()
            if record.get("owner"):
                os.fchown(target.fileno(), *record["owner"])
            os.fsync(target.fileno())
            identity = _identity(os.fstat(target.fileno()))
        return {
            "root": os.path.abspath(record["root"]),
            "username": record["username"],
            "parents": parents,
            "identity": identity,
            "sha256": hashlib.sha256(contents).hexdigest(),
        }
    finally:
        os.close(fd)


def remove(record):
    fd = None
    try:
        fd, _ = _open_config(record)
        source = os.open(
            "main.zcfg", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd
        )
        with os.fdopen(source, "rb") as original:
            info = os.fstat(original.fileno())
            if not stat.S_ISREG(info.st_mode) or _identity(info) != record["identity"]:
                return False
            digest = hashlib.file_digest(original, "sha256").hexdigest()
            if digest != record["sha256"]:
                return False
            # Recheck after reading, including the name relative to the held
            # directory, so edits and replacements observed during hashing survive.
            if _identity(os.fstat(original.fileno())) != record["identity"]:
                return False
            if (
                _identity(os.stat("main.zcfg", dir_fd=fd, follow_symlinks=False))
                != record["identity"]
            ):
                return False
            os.unlink("main.zcfg", dir_fd=fd)
        return True
    except (OSError, ValueError):
        return False
    finally:
        if fd is not None:
            os.close(fd)


if __name__ == "__main__":
    operation, encoded = sys.argv[1:]
    result = {"publish": publish, "remove": remove}[operation](json.loads(encoded))
    print(json.dumps(result))

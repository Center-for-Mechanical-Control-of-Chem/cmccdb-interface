"""Persist multipart attachments and bind them to the dataset's Data.url fields."""

from contextlib import contextmanager
from pathlib import Path, PurePosixPath
import re
import shutil
from urllib.parse import quote, unquote, urlsplit

from google.protobuf import text_format

from . import backups

MAX_AUXILIARY_FILES = 5
MAX_FILE_BYTES = 5 * 1024 * 1024


def read_upload(file):
    """Enforce the per-file limit even when the browser is bypassed."""
    body = file.read(MAX_FILE_BYTES + 1)
    if len(body) > MAX_FILE_BYTES:
        raise ValueError(f'"{file.filename}" exceeds the 5 MB file size limit')
    return body


def collect_uploads(files):
    if len(files) > MAX_AUXILIARY_FILES:
        raise ValueError(f"You may attach at most {MAX_AUXILIARY_FILES} auxiliary files")
    uploads = {}
    for file in files:
        name = file.filename or ""
        if (not name or name.startswith(".") or "/" in name or "\\" in name
                or ":" in name or any(ord(char) < 32 for char in name)
                or len(name.encode("utf-8")) > 255):
            raise ValueError("Auxiliary files must have plain filenames without directory paths")
        if name in uploads:
            raise ValueError(f'Duplicate auxiliary filename: "{name}"')
        uploads[name] = read_upload(file)
    return uploads


def _data_messages(message):
    if message.DESCRIPTOR.full_name == "cmccdb.Data":
        yield message
        return
    for field, value in message.ListFields():
        if field.message_type is None:
            continue
        if field.message_type.GetOptions().map_entry:
            for item in value.values():
                if hasattr(item, "ListFields"):
                    yield from _data_messages(item)
        elif field.label == field.LABEL_REPEATED:
            for item in value:
                yield from _data_messages(item)
        else:
            yield from _data_messages(value)


def _uploaded_name(url, dataset_id, names):
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    path = unquote(parts.path)
    if parts.scheme or parts.netloc or not path or path.startswith("/") or "\\" in path:
        return None
    relative = PurePosixPath(path)
    if any(part.startswith(".") for part in relative.parts):
        return None
    # Spreadsheet construction prefixes url(filename) with the dataset UUID.
    name = relative.name
    token = dataset_id.removeprefix("cmcc_dataset-")
    if name in names:
        return name
    if token and name.startswith(token + "_") and name[len(token) + 1:] in names:
        return name[len(token) + 1:]
    return None


@contextmanager
def saved_uploads(dataset, uploads, perform_backup):
    """Create a dataset-scoped directory; remove it if database insertion fails."""
    if not uploads:
        yield
        return
    if not re.fullmatch(r"[A-Za-z0-9_-]+", dataset.dataset_id):
        raise ValueError("A dataset ID is required to store auxiliary files")
    references = []
    linked_names = set()
    for data in _data_messages(dataset):
        if data.WhichOneof("kind") == "url":
            name = _uploaded_name(data.url, dataset.dataset_id, uploads)
            if name:
                references.append((data, name))
                linked_names.add(name)
    unlinked = uploads.keys() - linked_names
    if unlinked:
        raise ValueError("Auxiliary files must be referenced by a Data.url in the dataset: "
                         + ", ".join(sorted(unlinked))
                         + ". In a spreadsheet, use url(filename) in the appropriate data field.")

    root = Path(backups.BACKUP_DIR if perform_backup else backups.TEMPORARY_DIR) / "aux"
    root.mkdir(parents=True, exist_ok=True)
    directory = root / dataset.dataset_id
    # Never overwrite files belonging to an earlier submission of the same dataset.
    directory.mkdir()
    try:
        for name, body in uploads.items():
            (directory / name).write_bytes(body)
        for data, name in references:
            data.url = f"aux/{dataset.dataset_id}/{quote(name, safe='')}"
        # Keep a restorable copy with the same file references as the database.
        (directory / ".dataset.pbtxt").write_text(text_format.MessageToString(dataset), encoding="utf-8")
        yield
    except BaseException:
        shutil.rmtree(directory)
        raise

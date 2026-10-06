"""Serve local Data.url attachments referenced by a reaction record."""

import mimetypes
import os
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

import flask

from ..database import backups

bp = flask.Blueprint("auxiliary", __name__, url_prefix="/client")


def _fetch_reaction(reaction_id, database_name):
    from ..database import query

    results = query.QueryHandler(database_name).run_query(query.ReactionIdQuery([reaction_id]))
    return results[0] if len(results) == 1 else None


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


def _data_urls(message):
    return (data.url for data in _data_messages(message) if data.WhichOneof("kind") == "url")


def _local_path(url):
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    path = unquote(parts.path)
    if parts.scheme or parts.netloc or not path or path.startswith("/") or "\\" in path or "\x00" in path:
        return None
    relative = PurePosixPath(path)
    if any(part.startswith(".") for part in relative.parts):
        return None
    return relative


def _attachment_file(relative, dataset_id):
    roots = [
        Path(os.environ.get("CMCCDB_AUXILIARY_DIR", str(Path(backups.BACKUP_DIR) / "aux"))),
        Path(backups.BACKUP_DIR),
        Path(backups.TEMPORARY_DIR),
    ]
    candidates = {relative}
    # Older records prefix the original filename with the dataset UUID.
    dataset_token = (dataset_id or "").removeprefix("cmcc_dataset-")
    if dataset_token and relative.name.startswith(dataset_token + "_"):
        candidates.add(relative.with_name(relative.name[len(dataset_token) + 1:]))

    matches = set()
    for root in roots:
        root = root.resolve()
        if not root.is_dir():
            continue
        for candidate in candidates:
            paths = [root.joinpath(*candidate.parts)]
            if len(candidate.parts) == 1:
                # Uploads are stored in per-uploader subdirectories.
                paths.extend(directory / candidate.name for directory in root.iterdir()
                             if directory.is_dir() and not directory.name.startswith("."))
            for path in paths:
                resolved = path.resolve()
                if resolved.is_relative_to(root) and resolved.is_file():
                    if not any(part.startswith(".") for part in path.relative_to(root).parts):
                        matches.add(resolved)
    # Refuse ambiguous filenames instead of choosing another uploader's file.
    return next(iter(matches)) if len(matches) == 1 else None


@bp.route("/api/auxiliary/<reaction_id>")
def get_auxiliary_file(reaction_id):
    url = flask.request.args.get("url", "")
    relative = _local_path(url)
    if relative is None:
        flask.abort(404)
    record = _fetch_reaction(reaction_id, flask.request.args.get("database"))
    if record is None:
        flask.abort(404)
    data = next((data for data in _data_messages(record.reaction)
                 if data.WhichOneof("kind") == "url" and data.url == url), None)
    if data is None:
        flask.abort(404)
    path = _attachment_file(relative, record.dataset_id)
    if path is None:
        flask.abort(404)
    mimetype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    image_formats = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
                     "webp": "image/webp", "svg": "image/svg+xml", "avif": "image/avif", "bmp": "image/bmp",
                     "ico": "image/x-icon", "tif": "image/tiff", "tiff": "image/tiff"}
    image_format = data.format.strip().lower().removeprefix(".")
    if image_format in image_formats:
        mimetype = image_formats[image_format]
    elif image_format in image_formats.values():
        mimetype = image_format
    response = flask.send_file(path, mimetype=mimetype, as_attachment=not mimetype.startswith("image/"))
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'; style-src 'unsafe-inline'"
    return response

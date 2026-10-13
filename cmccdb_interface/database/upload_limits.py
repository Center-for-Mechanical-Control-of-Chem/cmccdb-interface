"""Bounded audit attachments shared by HTTP preparation and batch compilation."""

MAX_AUXILIARY_FILES = 64
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_REQUEST_BYTES = 31 * 1024 * 1024


def check_auxiliary_count(count):
    if count > MAX_AUXILIARY_FILES:
        raise ValueError(f'You may attach at most {MAX_AUXILIARY_FILES} auxiliary files')


def check_upload_budget(dataset_bytes, files):
    """Reject a whole contribution; never truncate an attachment collection."""
    check_auxiliary_count(len(files))
    if dataset_bytes > MAX_FILE_BYTES:
        raise ValueError('Dataset file exceeds 5 MB')
    for name, body in files.items():
        if len(body) > MAX_FILE_BYTES:
            raise ValueError(f'Auxiliary file {name} exceeds 5 MB')
    if dataset_bytes + sum(map(len, files.values())) > MAX_REQUEST_BYTES:
        raise ValueError('Dataset and complete auxiliary files exceed the 31 MiB request limit')

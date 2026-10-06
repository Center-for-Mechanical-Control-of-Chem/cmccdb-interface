import os
import datetime
from pathlib import Path
from urllib.parse import urlsplit
from . import backups

from google.protobuf import text_format  # pytype: disable=import-error
from cmccdb_schema.proto import dataset_pb2
from cmccdb_schema import message_helpers
from cmccdb_schema.proto import reaction_pb2

DATASET_EXTENSIONS = ('.pbtxt.gz', '.json.gz', '.pb.gz', '.pbtxt', '.json', '.pb', '.xlsx', '.csv')
MAX_AUXILIARY_FILES = 5
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

def split_dataset_filename(filename):
    name = os.path.basename(filename)
    for extension in DATASET_EXTENSIONS:
        if name.lower().endswith(extension):
            return name[:-len(extension)], extension
    raise ValueError('Dataset must be XLSX, CSV, protobuf text/binary, or JSON (optionally gzipped)')

def iter_data(message):
    """Visit Data messages in every schema location, including maps."""
    if isinstance(message, reaction_pb2.Data):
        yield message
        return
    for field, value in message.ListFields():
        if field.message_type is None:
            continue
        if field.message_type.GetOptions().map_entry:
            for item in value.values():
                yield from iter_data(item)
        elif field.label == field.LABEL_REPEATED:
            for item in value:
                yield from iter_data(item)
        else:
            yield from iter_data(value)

def attach_auxiliary_files(dataset, files):
    """Store attachments in protobuf Data so database exports retain their bytes."""
    if not files:
        return
    if len(files) > MAX_AUXILIARY_FILES:
        raise ValueError('At most five auxiliary files are allowed')
    if not dataset.reactions:
        raise ValueError('Auxiliary files require an embedded-reaction dataset')
    for name, body in files.items():
        if not name or name in {'.', '..'} or Path(name).name != name or '\\' in name:
            raise ValueError('Auxiliary file names must be basenames')
        if len(body) > MAX_UPLOAD_BYTES:
            raise ValueError(f'Auxiliary file {name} exceeds 5 MB')
    # Older templates prefixed file references with the spreadsheet MD5.
    prefix = dataset.dataset_id.removeprefix('cmcc_dataset-') + '_'
    for data in list(iter_data(dataset)):
        if data.WhichOneof('kind') != 'url' or urlsplit(data.url).scheme:
            continue
        name = data.url.removeprefix(prefix)
        if name in files:
            data.bytes_value = files[name]
            data.format = data.format or Path(name).suffix.lstrip('.') or 'bin'
    metadata = dataset.reactions[0].provenance.reaction_metadata
    for name, body in files.items():
        key = 'attachment:' + name
        if key in metadata:
            raise ValueError(f'Attachment {name} already exists')
        metadata[key].CopyFrom(reaction_pb2.Data(
            bytes_value=body, format=Path(name).suffix.lstrip('.') or 'bin', description=name))

def write_datafile(file_name, data, perform_backup=True, backup_dir=None, username=None, mode='w+',
                   file_id=None
                   ):
    if file_name is None:
        file_name = "Untitled.pbtxt"

    if file_id is None:
        file_id = datetime.datetime.now().isoformat()
    try:
        file_name, ext = split_dataset_filename(file_name)
    except ValueError:
        file_name, ext = os.path.splitext(os.path.basename(file_name))
    file_name = f"{file_name}-{file_id}{ext}"
    
    if backup_dir is None:
        if perform_backup:
            backup_dir = backups.BACKUP_DIR
        else:
            backup_dir = backups.TEMPORARY_DIR
    if username is not None:
        if os.path.basename(username) != username or username in {'.', '..'}:
            raise ValueError('Invalid backup user name')
        backup_dir = os.path.join(backup_dir, username)

    proper_file = os.path.join(backup_dir, file_name)
    os.makedirs(backup_dir, exist_ok=True)
    with open(proper_file, mode) as dataset_file:
        dataset_file.write(data)

    return proper_file


def prep_pbtxt_file(
    file_name, data, 
    perform_backup=True,
    uploader_username=None,
    uploader_name=None, 
    uploader_email=None
    ):
    base_name, ext = split_dataset_filename(file_name)
    serialized = ext in {'.pb', '.pb.gz'}
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError('Dataset file exceeds 5 MB')
    
    proper_file = write_datafile(
        file_name, data, 
        perform_backup=perform_backup,
        username=uploader_username, 
        mode="w+b"
        )
    if ext in {".xlsx", ".csv"}:
        import cmccdb_schema.scripts.construct_dataset as constructor

        constructor.main({
            "--data":proper_file,
            "--dataset-name":base_name,
            "--name":uploader_name,
            "--email":uploader_email
        })

        proper_file = os.path.splitext(proper_file)[0] + ".pbtxt"
    return proper_file, serialized
    

def create_pb_dataset(file, serialized=False):
    return message_helpers.load_message(str(file), dataset_pb2.Dataset)

def prep_and_create_pb_dataset(
    file_name,
    body,
    perform_backup=True,
    uploader_username=None,
    uploader_name=None, 
    uploader_email=None,
    auxiliary_files=None
):
    file, serialized = prep_pbtxt_file(
        file_name,
        body,
        perform_backup=perform_backup,
        uploader_username=uploader_username,
        uploader_name=uploader_name, 
        uploader_email=uploader_email
        )
    dataset = create_pb_dataset(file, serialized=serialized)
    attach_auxiliary_files(dataset, auxiliary_files)
    if auxiliary_files:
        stem, _ = split_dataset_filename(file)
        message_helpers.write_message(dataset, os.path.join(os.path.dirname(file), stem + '.pbtxt'))
    return dataset

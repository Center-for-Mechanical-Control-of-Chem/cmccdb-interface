import os
import datetime
from . import backups

from google.protobuf import text_format  # pytype: disable=import-error
from cmccdb_schema.proto import dataset_pb2

def write_datafile(file_name, data, mode='w+'):
    if file_name is None:
        file_name = "Untitled.pbtxt"

    file_id = datetime.datetime.now().isoformat()
    file_name, ext = os.path.splitext(os.path.basename(file_name))
    file_name = f"{file_name}-{file_id}{ext}"

    proper_file = os.path.join(backups.BACKUP_DIR, file_name)
    os.makedirs(backups.BACKUP_DIR, exist_ok=True)
    with open(proper_file, mode) as dataset_file:
        dataset_file.write(data)

    return proper_file


def prep_pbtxt_file(file_name, data, uploader_name=None, uploader_email=None):
    base_name, ext = os.path.splitext(os.path.basename(file_name))
    serialized = ext == ".pb"
        
    proper_file = write_datafile(file_name, data, mode="w+b")
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
    if serialized:
        with open(file, 'rb') as stream:
            data = steam.read()
        dataset = dataset_pb2.Dataset.FromString(data)
    else:
        with open(file, 'r') as stream:
            data = stream.read()
        dataset = dataset_pb2.Dataset()
        text_format.Parse(data, dataset)
    return dataset

def prep_and_create_pb_dataset(
    file_name,
    body,
    uploader_name=None, 
    uploader_email=None
):
    file, serialized = prep_pbtxt_file(
        file_name,
        body,
        uploader_name=uploader_name, 
        uploader_email=uploader_email
        )
    return create_pb_dataset(file, serialized=serialized)

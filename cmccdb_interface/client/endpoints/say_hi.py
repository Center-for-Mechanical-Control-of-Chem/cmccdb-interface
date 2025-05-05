

# pylint: disable=too-many-locals

# import dataclasses
# import gzip
# import io
# import os
# import uuid
# import subprocess
# from typing import List, Optional, Tuple

# import flask
# from rdkit import Chem

# import sqlalchemy
# from sqlalchemy import orm

# import google.protobuf.message  # pytype: disable=import-error
# from ord_schema.orm import database
# from google.protobuf import text_format  # pytype: disable=import-error
# from ord_schema.proto import dataset_pb2, reaction_pb2

import flask

def say_hi():
    return flask.jsonify({"response":"hi, how are you"})

def flask_info():
    return flask.jsonify(flask.request.args)

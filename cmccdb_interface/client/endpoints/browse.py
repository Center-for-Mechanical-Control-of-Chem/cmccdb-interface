

import flask
import os
import sys
import psycopg2
from cmccdb_interface.database import manage, query


def detele_database(database_name=None, **conn_args):
    database_name = manage.get_database_name(database_name)
    conn = manage.connect(isolated=True, **conn_args)
    with conn, conn.cursor() as cur:
        conn.autocommit = True
        cur.execute(f"DROP DATABASE IF EXISTS {database_name};")

def fetch_datasets():
    """Fetches info about the current datasets."""
    database_name = manage.get_database_name(flask.request.args.get("database"))

    rows = [
        {
            "Dataset ID": row["dataset_id"],
            "Name": row["name"],
            "Description": row["description"],
            "Size": row["size"]
        }
        for row in query.fetch_datasets(database_name=database_name, get_sizes=True, undefined_means_empty=True)
    ]
    if len(rows) == 0:
        return {
            "response":f"No datasets found for database {database_name}, are you sure you spelled it right?"
        }
    else:
        return rows

# def fetch_datasets():
#     empty_datasets = [
#         {"Dataset ID":"cmcc_dataset-658edfc0f9c84484acd5109674f3665d","Description":None,"Name":"Halogenation","Size":46}
#         ]
#     return flask.jsonify(empty_datasets)

# def fetch_datasets():
#     """Fetches info about the current datasets."""
#     database_name = flask.request.args.get("database")

#     # return [{
#     #             "Dataset ID": "dataset_id",
#     #             "Name": database_name,
#     #             "Description": "description",
#     #             "Size": 0,
#     #         }]

#     try:
#         engine = connect(database_name)
#     except Exception as e:
#         return [{
#                 "Dataset ID": "Error",
#                 "Name": "Database doesn't exist",
#                 "Description": str(e),
#                 "Size": 0,
#             }]
#     else:
#         rows = {}
#         with engine.connection, engine.cursor() as cursor:
#             cursor.execute("SELECT id, dataset_id, name, description FROM dataset")
#             for row_id, dataset_id, name, description in cursor:
#                 rows[row_id] = {
#                     "Dataset ID": dataset_id,
#                     "Name": name,
#                     "Description": description,
#                     "Size": 0,
#                 }
#             # Get dataset sizes.
#             cursor.execute("SELECT dataset_id, COUNT(reaction_id) FROM reaction GROUP BY dataset_id")
#             for row_id, count in cursor:
#                 rows[row_id]["Size"] = count
#             return list(rows.values())

import os

import psycopg2
import sqlalchemy
from sqlalchemy import orm
from cmccdb_schema.orm import database as orm_db
import html

from . import constants

def get_host(host=None): return host or os.getenv("POSTGRES_HOST") or constants.POSTGRES_HOST
def get_port(port=None): return int(port or os.getenv("POSTGRES_PORT") or constants.POSTGRES_PORT)
def get_user(user=None): return user or os.getenv("POSTGRES_USER") or constants.POSTGRES_USER
def get_password(password=None): return password or os.getenv("POSTGRES_PASSWORD") or constants.POSTGRES_PASSWORD
def get_database_name(database_name=None): 
    return html.escape(database_name or os.getenv("POSTGRES_DATABASE") or constants.POSTGRES_DATABASE)

def create_raw_connection(
    database_name=None, 
    user=None, password=None, 
    host=None, 
    port=None, 
    options=None,
    search_path=None,
    isolated=False,
    readonly=True,
    **postgres_opts
):  
    if options is None:
        if search_path is None:
            search_path = ["public", constants.SCHEMA_NAME]
        if not isinstance(search_path, str):
            search_path = ",".join(search_path)
        options=f"-c search_path={search_path}"
    if isolated:
        connection = psycopg2.connect(
            # dbname=get_database_name(database_name), 
            user=get_user(user), 
            password=get_password(password), 
            host=get_host(host), 
            port=get_port(port), 
            options=options,
            **postgres_opts
        )
    else:
        connection = psycopg2.connect(
                dbname=get_database_name(database_name), 
                user=get_user(user), 
                password=get_password(password), 
                host=get_host(host), 
                port=get_port(port), 
                options=options,
                **postgres_opts
            )
        if readonly:
            connection.set_session(readonly=True)
    return connection
def connect(database_name=None, **conn_args):
    database_name = get_database_name(database_name)
    try:
        connection = create_raw_connection(database_name=database_name, **conn_args)
    except psycopg2.OperationalError as err:
        if str(err).strip().endswith(f'database "{database_name}" does not exist'):
            create_database(database_name, **conn_args)
            configure_database(database_name)
            connection = create_raw_connection(database_name=database_name, **conn_args)
        else:
            raise
    return connection
    

def get_engine(database_name=None, user=None, password=None, host=None, port=None):
    connection_string = orm_db.get_connection_string(
        database=get_database_name(database_name),
        username=get_user(user), 
        password=get_password(password),
        host=get_host(host),
        port=get_port(port)
    )
    engine = sqlalchemy.create_engine(connection_string, future=True)
    return engine

def configure_database(database_name=None, **conn_args):
    engine = get_engine(database_name=database_name, **conn_args)
    orm_db.prepare_database(engine)
def get_session(database_name=None, **conn_args):
    engine = get_engine(database_name=database_name, **conn_args)
    orm_db.prepare_database(engine)
    return orm.Session(engine)

def create_database(database_name=None, **conn_args):
    database_name = get_database_name(database_name)
    conn = create_raw_connection(isolated=True, **conn_args)
    with conn.cursor() as cur:
        conn.autocommit = True
        cur.execute(f"CREATE DATABASE {database_name};")
def delete_database(database_name=None, force_quit=False, **conn_args):
    database_name = manage.get_database_name(database_name)
    conn = manage.connect(isolated=True, **conn_args)
    with conn, conn.cursor() as cur:
        conn.autocommit = True
        if force_quit:
            cur.execute(
                f"""
REVOKE CONNECT ON DATABASE {database_name} FROM PUBLIC;
SELECT 
    pg_terminate_backend(pid) 
FROM 
    pg_stat_activity 
WHERE 
    pid <> pg_backend_pid()
    AND datname = %(dbname)s
    ;
    """,
                {"dbname": database_name}
                )
        cur.execute(f"DROP DATABASE IF EXISTS {database_name}")
def reset_database(database_name=None, force_quit=False, **conn_args):
    database_name = get_database_name(database_name)
    conn = connect(isolated=True, **conn_args)
    with conn.cursor() as cur:
        conn.autocommit = True
        if force_quit:
            cur.execute(
                f"""
REVOKE CONNECT ON DATABASE {database_name} FROM PUBLIC;
SELECT 
    pg_terminate_backend(pid) 
FROM 
    pg_stat_activity 
WHERE 
    pid <> pg_backend_pid()
    AND datname = %(dbname)s
    ;
    """,
                {"dbname": database_name}
                )
        cur.execute(f"DROP DATABASE IF EXISTS {database_name}")
        cur.execute(f"CREATE DATABASE {database_name}", {"dbname":database_name})
def delete_dataset(dataset_id, database_name=None, **conn_args):
    with get_session(database_name=database_name, **conn_args) as session:
        orm_db.delete_dataset(dataset_id, session)
        session.flush()
        session.commit()
def add_dataset(data, database_name=None, **conn_args):
    with get_session(database_name=database_name, **conn_args) as session:
        orm_db.add_dataset(data, session)
        session.flush()
        session.commit()
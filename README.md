# cmccdb-interface
Web interface and api for the CMCC Reaction Database

To spin up a new developer instance, we'll serve from `/home` by default and clone down the packages.
You may need to clone them in `/tmp` and use `sudo` to move them to `/home`.
We use a container workflow, so `podman` (or `docker`) is required.
We will also need to use `podman compose`/`docker compose` so that needs to be installed as well.

The basic installation looks like

```commandline
cd /home
git clone git@github.com:Center-for-Mechanical-Control-of-Chem/cmccdb-schema.git
git clone git@github.com:Center-for-Mechanical-Control-of-Chem/cmccdb-interface.git
```

and then to build the original ORD container that we patch into, we first create a conda environment 
that will be used when building the necessary components

```commandline
conda create --name=ord python=3.10
conda activate ord
cd /home/cmccdb-interface
pip install -e .
```

You may run into issues with `psycopg2`. In that case, install run `pip install psycopg2-binary`.

Next we have to set up the base container that will hold the original interface implementation that we patch.

```commandline
cd ord_interface
sudo podman build --file Dockerfile -t openreactiondatabase/ord-interface ..
```

We also need to configure the POSTGRES database which will run within the container. 
To do that we take from `ord_interface/build_test_databse.sh` and set up the database to expose port `5432`

```commandline
export PGPASSWORD=postgres
# Use a non-standard PGDATA so the database persists; see
# https://nickjanetakis.com/blog/docker-tip-79-saving-a-postgres-database-in-a-docker-image.
CONTAINER="$(sudo podman run --rm -d -p 5432:5432 -e POSTGRES_PASSWORD=${PGPASSWORD} -e PGDATA=/data mcs07/postgres-rdkit)"
```

However, we won't run the rest of that script, as we will use API endpoints to configure the database.
So now we just save the container for later use

```
sudo podman commit "${CONTAINER}" "openreactiondatabase/ord-postgres:test"
sudo podman stop "${CONTAINER}"
```

Now that we've configured the original interface, all of the patches we have constructed are applied by `docker-compose.yml`
which will take local directories and inject them into the container at runtime.
This gives us the flexibility to develop on the existing infrastructure.
In the future, we will compile the entire flow into a new `Dockerfile` so that it can be served without patches.

To start the app, we run

```commandline
cd /home/cmccdb-interface/ord_interface
# clean up the existing interface for saftey
sudo podman container stop ord_interface_web_1
sudo podman rm ord_interface_web_1
# restart the container
sudo podman compose up
```

Now, the database hasn't been configured, so we need to send a `POST` request to the `reconfigure` endpoint, i.e.
we will run e.g.

```commandline
curl -X POST http://mechanochemistry-db-01.chem.tamu.edu/api/reconfigure
```

This endpoint will be changed upon public release to simply create the database.

## Front-End

This is how the app interface is structured

- **/app** - Contains the Vue single page application
  - **/public** - Static SPA assets such as index.html
  - **/src** - Vue source code that gets compiled
    - **/assets** - Images and other static assets
    - **/components** - Reusable Vue components that can be included elsewhere
    - **/router** - Routing files
    - **/styles** - Static .sass files that can be reused throughout the project
    - **/utils** - Static helper .js files
    - **/views** - Routed Vue components, aka "pages"
      - **/browse** - Main browse page of the different reaction sets
      - **/reaction-view** - Display of a single reaction from search results
      - **/search** - Search interface and results

To rebuild the front end, `npm` must be installed, and we run

- **/ord_interface** - Contains the Flask app API
  - **/client** - endpoints for the browse, search, and submissions functionality
  - **/visualization** - helper functions for reaction and molecule visuals

## Adding End Points

A specific `api/register/<name>` endpoint is configured that will look for a python script in `/tmp/name` to

## Modifying the schema

When rebuilding the proto, new versions of `protobuf` insert information about the `runtime` that the container version
doesn't have. This may need to be commented out.
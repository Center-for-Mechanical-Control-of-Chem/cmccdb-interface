
cd /home/cmccdb-interface/cmccdb_interface
sudo podman build --file Dockerfile -t centerformechanochemistry/cmccdb-interface ../..
export PGPASSWORD=postgres
# Use a non-standard PGDATA so the database persists; see
# https://nickjanetakis.com/blog/docker-tip-79-saving-a-postgres-database-in-a-docker-image.
CONTAINER="$(sudo podman run --rm -d -p 5432:5432 -e POSTGRES_PASSWORD=${PGPASSWORD} -e PGDATA=/data mcs07/postgres-rdkit)"
sudo podman commit "${CONTAINER}" "centerformechanochemistry/cmccdb-postgres:test"
sudo podman stop "${CONTAINER}"
cd /home/cmccdb-interface/cmccdb_interface
# clean up the existing interface for saftey
# sudo podman container stop cmccdb_interface_web_1
# sudo podman rm cmccdb_interface_web_1

. /home/cmccdb-interface/restart_containers.sh
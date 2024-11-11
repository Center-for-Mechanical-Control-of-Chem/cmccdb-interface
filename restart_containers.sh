# sudo podman stop cmccdb_interface_web_1 
# sudo podman stop cmccdb_interface_database_1
# sudo podman container rm cmccdb_interface_web_1
# sudo podman container rm cmccdb_interface_database_1
cd /home/cmccdb-interface/cmccdb_interface
# restart the container
sudo podman compose --podman-run-args='--replace' up --detach
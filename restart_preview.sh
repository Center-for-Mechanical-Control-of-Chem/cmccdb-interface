# sudo podman stop cmccdb_interface_web_1 
# sudo podman stop cmccdb_interface_database_1
# sudo podman container rm cmccdb_interface_web_1
# sudo podman container rm cmccdb_interface_database_1
cd /home/cmccdb-interface/
cp -r ../cmccdb-schema/js/cmccdb-schema app/node_modules/
cp -r ../cmccdb-dependencies/google-protobuf app/node_modules/

cd /home/cmccdb-interface/cmccdb_interface
# restart the container
sudo podman compose --file='docker-compose-preview.yml' --podman-run-args='--replace' up --detach
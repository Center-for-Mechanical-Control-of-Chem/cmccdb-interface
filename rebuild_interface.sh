cd /home/cmccdb-interface

cp -r ../cmccdb-schema/js/ord-schema app/node_modules/cmccdb-schema
cd app
bash build_patch.sh

cd ..
bash restart_containers.sh
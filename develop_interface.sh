cp -r ../cmccdb-schema/js/ord-schema app/node_modules/cmccdb-schema
cd app
pm2 start "npm run serve -- --port=8070" --name dev-interface
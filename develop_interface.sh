cp -r ../cmccdb-schema/js/ord-schema app/node_modules/cmccdb-schema
cd app
#configured PM2 according to https://sobus-piotr.medium.com/pm2-share-the-same-daemon-process-between-multiple-users-dd7ecae6197a
PM2_HOME=/etc/pm2daemon pm2 start "npm run serve -- --port=8070" --name dev-interface
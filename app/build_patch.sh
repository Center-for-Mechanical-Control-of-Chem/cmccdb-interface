
rm -rf node_modules/ord-schema
cp -r ../../ord-schema/js/ord-schema node_modules/ord-schema

npm run build
rm -rf ../patch
mv dist ../patch
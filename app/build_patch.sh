
rm -rf node_modules/cmccdb-schema
cp -r ../../cmccdb-schema/js/cmccdb-schema node_modules/cmccdb-schema

cd src
if [ ! -d ketcher ]; then
    if [ ! -d standalone ]; then
        wget https://github.com/epam/ketcher/releases/download/v2.5.1/ketcher-standalone-2.5.1.zip \
            && unzip ketcher-standalone-2.5.1.zip
    fi
    mv standalone ketcher
fi

cd ..
npm run build
rm -rf ../patch
mv dist ../patch
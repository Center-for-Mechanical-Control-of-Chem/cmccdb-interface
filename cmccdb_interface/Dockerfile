# Copyright 2020 Open Reaction Database Project Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# To build the interface using the current state of ord-interface:
# $ cd path/to/ord-interface/ord_interface
# $ docker build --file=Dockerfile -t openreactiondatabase/ord-interface ..

FROM python:3.10

# default-jre is required for running the closure compiler linter.
# For this next line, see:
# https://github.com/geerlingguy/ansible-role-java/issues/64#issuecomment-597132394
RUN mkdir -p /usr/share/man/man1/
RUN apt-get update \
   && apt-get install -y \
   build-essential \
   default-jre \
   nginx \
   npm \
   procps \
   unzip \
   && apt-get clean \
   && rm -rf /var/lib/apt/lists/*

# Fetch and build editor dependencies.
# NOTE(kearnes): Do this before COPYing the local state so it can be cached.
WORKDIR /app/cmccdb-interface/cmccdb_interface
RUN wget https://github.com/epam/ketcher/releases/download/v2.5.1/ketcher-standalone-2.5.1.zip \
   && unzip ketcher-standalone-2.5.1.zip
# WORKDIR /app/ord-interface/ord_interface/editor
# RUN wget https://github.com/google/closure-library/archive/v20200517.tar.gz \
#    && tar -xzf v20200517.tar.gz \
#    && rm v20200517.tar.gz
# RUN wget https://github.com/protocolbuffers/protobuf/releases/download/v3.14.0/protobuf-js-3.14.0.tar.gz \
#    && tar -xzf protobuf-js-3.14.0.tar.gz \
#    && rm protobuf-js-3.14.0.tar.gz
# RUN wget https://github.com/protocolbuffers/protobuf/releases/download/v3.14.0/protoc-3.14.0-linux-x86_64.zip \
#    && unzip protoc-3.14.0-linux-x86_64.zip
# ENV PATH="/app/ord-interface/ord_interface/editor/bin:${PATH}"
# RUN wget https://raw.githubusercontent.com/google/closure-compiler/master/contrib/externs/jquery-3.3.js \
#    && mkdir -p externs \
#    && mv jquery-3.3.js externs
# RUN npm install google-closure-compiler@20220803
WORKDIR /app

# Install dependencies.
WORKDIR /app/cmccdb-interface
COPY cmccdb-interface/setup.py cmccdb-interface/README.md ./
RUN pip install --upgrade pip \
   && pip install gunicorn wheel
# https://stackoverflow.com/a/60511098.
RUN python setup.py egg_info \
   && pip install $(grep -v '^\[' *.egg-info/requires.txt) \
   && rm -rf *.egg-info/

# Copy the local state.
# COPY ord_interface/editor/js/ ord_interface/editor/js/
# COPY ord_interface/editor/build.sh ord_interface/editor
# WORKDIR /app/ord-interface/ord_interface/editor
# RUN ./build.sh
WORKDIR /app
COPY cmccdb-schema cmccdb-schema
WORKDIR /app/cmccdb-interface
# Build the Vue app.
COPY cmccdb-interface/app/ app/
WORKDIR /app/cmccdb-interface/app
RUN cp -r /app/cmccdb-interface/cmccdb_interface/standalone/ /app/cmccdb-interface/app/src/ketcher \
   && npm install \
   && npm run build \
   && mv dist/ /app/cmccdb-interface/vue
WORKDIR /app/cmccdb-interface
COPY cmccdb-interface/cmccdb_interface/about.html cmccdb_interface/
COPY cmccdb-interface/cmccdb_interface/interface.py cmccdb_interface/
COPY cmccdb-interface/cmccdb_interface/client/ cmccdb_interface/client/
COPY cmccdb-interface/cmccdb_interface/visualization/ cmccdb_interface/visualization/
RUN pip install .

# Build and launch the interface.
COPY cmccdb-interface/cmccdb_interface/start_app.sh .
COPY cmccdb-interface/cmccdb_interface/nginx.conf /etc/nginx/nginx.conf

ENV PYTHONPATH=/app/cmccdb-interface:/app/cmccdb-schema
RUN ln -sf /dev/stderr /var/log/nginx.log \
   && chmod +x start_app.sh
ENTRYPOINT ["/app/cmccdb-interface/start_app.sh"]
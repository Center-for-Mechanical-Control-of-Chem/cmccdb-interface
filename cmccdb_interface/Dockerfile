# syntax=docker/dockerfile:1
# Context is the directory containing cmccdb-interface and cmccdb-schema.
FROM node:22-bookworm-slim AS frontend-deps
WORKDIR /app/cmccdb-interface/app
# Keep installation cached across Vue and Python source changes.
COPY cmccdb-schema/js/cmccdb-schema/package.json /app/cmccdb-schema/js/cmccdb-schema/package.json
COPY cmccdb-interface/app/package.json cmccdb-interface/app/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund \
    && sha256sum package.json package-lock.json /app/cmccdb-schema/js/cmccdb-schema/package.json \
    | sha256sum | cut -d ' ' -f 1 > node_modules/.cmccdb-dependencies.sha256

FROM debian:bookworm-slim AS ketcher
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/*
ARG KETCHER_SHA256=38ba0411e5c7190eb9f0fcc8e5904de45ac99e02a3707781f342af6e0997a1f0
RUN curl -fsSL --retry 3 https://github.com/epam/ketcher/releases/download/v2.5.1/ketcher-standalone-2.5.1.zip -o /ketcher.zip \
    && test -n "${KETCHER_SHA256}" \
    && echo "${KETCHER_SHA256}  /ketcher.zip" | sha256sum -c - \
    && unzip -q /ketcher.zip -d /ketcher && rm /ketcher.zip

FROM frontend-deps AS frontend
COPY cmccdb-schema/js/cmccdb-schema/ /app/cmccdb-schema/js/cmccdb-schema/
COPY cmccdb-interface/app/ ./
COPY --from=ketcher /ketcher/standalone/ ./src/ketcher/
RUN npm run build

FROM python:3.11-slim-bookworm AS python-deps
WORKDIR /app
COPY cmccdb-interface/requirements-runtime.txt /app/requirements-runtime.txt
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --only-binary=rdkit,numpy,pandas,psycopg2-binary -r requirements-runtime.txt

FROM python-deps AS python-code
COPY cmccdb-schema/setup.py cmccdb-schema/pyproject.toml cmccdb-schema/README.md /app/cmccdb-schema/
COPY cmccdb-schema/cmccdb_schema/ /app/cmccdb-schema/cmccdb_schema/
COPY cmccdb-interface/setup.py cmccdb-interface/pyproject.toml cmccdb-interface/README.md /app/cmccdb-interface/
# Copy the complete backend, including database/, util.py and endpoints.
COPY cmccdb-interface/cmccdb_interface/ /app/cmccdb-interface/cmccdb_interface/
RUN pip install --no-deps --no-build-isolation ./cmccdb-schema ./cmccdb-interface && pip check \
    && python -c "from cmccdb_schema.proto import dataset_pb2, reaction_pb2, test_pb2; from rdkit import Chem; assert Chem.MolFromSmiles('CCO')"

FROM python:3.11-slim-bookworm AS runtime
ARG PG_CLIENT_MAJOR=16
# The RDKit wheel's Cairo/fontconfig libraries require these system libraries.
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx git ca-certificates curl libstdc++6 libxrender1 libxext6 libexpat1 \
    && mkdir -p /usr/share/postgresql-common/pgdg \
    && curl -fsSL --retry 3 https://www.postgresql.org/media/keys/ACCC4CF8.asc \
       -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
       > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends postgresql-client-${PG_CLIENT_MAJOR} \
    && rm -rf /var/lib/apt/lists/*
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app/cmccdb-interface:/app/cmccdb-schema \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY --from=python-code /opt/venv /opt/venv
COPY --from=python-code /app/cmccdb-schema /app/cmccdb-schema
COPY --from=python-code /app/cmccdb-interface /app/cmccdb-interface
COPY --from=frontend /app/cmccdb-interface/app/dist/ /app/cmccdb-interface/vue/
COPY --from=ketcher /ketcher/standalone/ /app/cmccdb-interface/cmccdb_interface/standalone/
COPY cmccdb-interface/cmccdb_interface/nginx.conf /etc/nginx/nginx.conf
COPY cmccdb-interface/cmccdb_interface/start_app.sh /app/cmccdb-interface/start_app.sh
RUN ln -sf /dev/stderr /var/log/nginx.log && chmod +x /app/cmccdb-interface/start_app.sh
# Check drawing in the final runtime, where system libraries must be present.
RUN python -c "import base64; from rdkit import Chem; from cmccdb_interface.visualization import drawing; molecule = Chem.MolFromSmiles('CCO'); assert molecule is not None; svg = drawing.mol_to_svg(molecule); assert svg is not None and '<svg' in svg; png = base64.b64decode(drawing.mol_to_png(molecule)); assert png.startswith(bytes((137, 80, 78, 71, 13, 10, 26, 10))); print('RDKit SVG and PNG rendering: OK')"
WORKDIR /app/cmccdb-interface
EXPOSE 80
ENTRYPOINT ["/app/cmccdb-interface/start_app.sh"]

# Optional preview retains Node and the development server dependencies.
FROM runtime AS preview
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=frontend /usr/local/bin/node /usr/local/bin/node
COPY --from=frontend /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm
COPY --from=frontend /app/cmccdb-schema/js/ /app/cmccdb-schema/js/
COPY --from=frontend /app/cmccdb-interface/app/ /app/cmccdb-interface/dev/
ENV CMCCDB_LAUNCH_DEV_INTERFACE=true \
    CMCCDB_KETCHER_DIR=/app/cmccdb-interface/vue/ketcher
# start_app.sh's CMCCDB_DEV_FRONTEND and CMCCDB_DEV_BACKEND (docker-compose-dev.yml) work in this image
LABEL org.cmccdb.dev-support="frontend backend"
EXPOSE 95

# Make the small production image the default build target.
FROM runtime AS production

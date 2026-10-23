# syntax=docker/dockerfile:1.7
# Staff UI: built with Vite, served by unprivileged nginx on :8080.
ARG NODE_IMAGE=node:20-alpine
ARG NGINX_IMAGE=nginxinc/nginx-unprivileged:1.27-alpine

FROM ${NODE_IMAGE} AS build
WORKDIR /app
COPY package.json package-lock.json* ./
# Optional corporate CA bundle: docker build --secret id=ca_bundle,src=/path/ca.pem ...
RUN --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/ca_bundle ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/ca_bundle; fi \
 && npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM ${NGINX_IMAGE}
COPY --from=build /app/dist /usr/share/nginx/html
COPY docker/nginx.conf /etc/nginx/templates/default.conf.template
COPY --chmod=0755 docker/40-runtime-config.sh /docker-entrypoint.d/40-runtime-config.sh
ENV CSP_CONNECT_SRC="" CSP_FRAME_SRC="" NGINX_ENVSUBST_FILTER="CSP_"
USER 101
EXPOSE 8080

# ---- Etap 1: build aplikacji React (CRA + craco) ----
FROM node:20-alpine AS build

WORKDIR /app

# Najpierw zależności — lepsze cache'owanie warstw
COPY package.json yarn.lock ./
RUN yarn install --frozen-lockfile --network-timeout 600000

COPY . .

# CRA wkleja REACT_APP_* w czasie builda. Domyślnie ścieżka relatywna — ruch idzie przez proxy Nginx.
ARG REACT_APP_INVESTWATCH_API_URL=/api/v1
ARG REACT_APP_ALERT_THRESHOLD=0.7
ENV REACT_APP_INVESTWATCH_API_URL=$REACT_APP_INVESTWATCH_API_URL \
    REACT_APP_ALERT_THRESHOLD=$REACT_APP_ALERT_THRESHOLD \
    GENERATE_SOURCEMAP=false

RUN yarn build

# ---- Etap 2: serwowanie statyki + reverse proxy do backendu ----
FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY nginx-security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --from=build /app/build /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1

FROM node:22-slim AS build
WORKDIR /app
COPY package.json ./
# Two Emergent-platform packages (not used by the app) are hosted on assets.emergent.sh; drop them so the
# build does not depend on that host.
RUN sed -i '/@emergentbase\//d' package.json && yarn install --network-timeout 600000
COPY . .
# Empty = same origin: nginx below proxies /api to the backend.
ARG REACT_APP_BACKEND_URL=""
ENV REACT_APP_BACKEND_URL=$REACT_APP_BACKEND_URL
RUN CI=true yarn build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/build /usr/share/nginx/html
EXPOSE 80

# Gateway image = nginx + the built frontend. Proposed for the `gateway` service in
# docker-compose.yml (build context: ./frontend). nginx's site config stays the compose
# owner's deploy/gateway/nginx.conf, mounted as today; this image only adds the app files.
#
#   gateway:
#     build: ./frontend            # instead of image: nginx:1.27-alpine
#     volumes:
#       - ./deploy/gateway/nginx.conf:/etc/nginx/conf.d/default.conf:ro
#
# Build args: VITE_USE_MOCK=false (default) talks to the backend; set it to true to ship demo data.
# VITE_LIVE=agent,assets,... keeps demo data but makes only those features live (see README).

FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_USE_MOCK=false
ARG VITE_LIVE=""
ENV VITE_USE_MOCK=$VITE_USE_MOCK     VITE_LIVE=$VITE_LIVE
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html

FROM node:24.19.0-bookworm-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json vite.config.ts index.html eslint.config.js .prettierrc.json .prettierignore ./
COPY src ./src
RUN npm run build

FROM build AS test
RUN npm run check

FROM nginx:1.29.4-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080

FROM node:24.19.0-bookworm-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json vite.config.ts index.html eslint.config.js .prettierrc.json .prettierignore ./
COPY scripts ./scripts
COPY src ./src
RUN npm run build

FROM build AS test
RUN npm run check

FROM node:24.19.0-bookworm-slim AS browser-test
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
RUN rm -f /etc/apt/apt.conf.d/docker-clean \
    && printf 'Acquire::Retries "10";\nAcquire::http::Timeout "30";\nBinary::apt-get::APT::Keep-Downloaded-Packages "true";\n' \
    > /etc/apt/apt.conf.d/80-playwright-retries
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    for attempt in 1 2 3 4 5; do \
      npx playwright install-deps chromium \
        && apt-get install -y --no-install-recommends postgresql-client \
        && exit 0; \
      echo "Playwright system dependency attempt ${attempt} failed"; \
    done; \
    exit 1
ENV PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=120000
RUN for attempt in 1 2 3; do \
      npx playwright install chromium && exit 0; \
      echo "Playwright Chromium download attempt ${attempt} failed"; \
    done; \
    exit 1
COPY playwright.config.ts ./
COPY e2e ./e2e
COPY src/sensitive-content-patterns.json ./src/sensitive-content-patterns.json
COPY src/test-support/issue215-intake-diagnostic.ts ./src/test-support/issue215-intake-diagnostic.ts
ENTRYPOINT ["npm", "run", "test:browser", "--"]

FROM nginx:1.29.4-alpine AS browser-server
RUN apk add --no-cache openssl \
    && mkdir -p /etc/nginx/tls \
    && openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
       -subj '/CN=browser-frontend' \
       -addext 'subjectAltName=DNS:browser-frontend' \
       -keyout /etc/nginx/tls/key.pem \
       -out /etc/nginx/tls/cert.pem
COPY nginx.browser.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8443

FROM nginx:1.29.4-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080

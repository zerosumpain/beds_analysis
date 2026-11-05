# Stage 1: generate the CSV/zip downloads from site/data (kept out of git).
FROM python:3.13-alpine AS downloads
WORKDIR /app
COPY site/data ./site/data
COPY scripts/build_downloads.py ./scripts/
RUN python3 scripts/build_downloads.py /app

FROM node:22-alpine
WORKDIR /app
COPY server.mjs ./
COPY site ./site
COPY --from=downloads /app/site/data/downloads ./site/data/downloads
ARG VERSION=dev
# Stamp asset URLs so a deploy is never hidden behind Cloudflare's 4-hour edge cache.
RUN sed -i "s/__V__/${VERSION}/g" site/index.html
USER node
ENV PORT=5660 HOST=0.0.0.0
EXPOSE 5660
CMD ["node", "server.mjs"]

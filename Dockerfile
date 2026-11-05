FROM node:22-alpine
WORKDIR /app
COPY server.mjs ./
COPY site ./site
ARG VERSION=dev
# Stamp asset URLs so a deploy is never hidden behind Cloudflare's 4-hour edge cache.
RUN sed -i "s/__V__/${VERSION}/g" site/index.html
USER node
ENV PORT=5660 HOST=0.0.0.0
EXPOSE 5660
CMD ["node", "server.mjs"]

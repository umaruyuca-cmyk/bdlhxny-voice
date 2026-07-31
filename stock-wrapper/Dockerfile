FROM node:lts-bookworm-slim AS skill-package

WORKDIR /build/stock-analysis-skill
COPY skills/stock-analysis-skill/package*.json ./
RUN npm ci
COPY skills/stock-analysis-skill/ ./
RUN mkdir -p /dist \
    && npm pack --pack-destination /dist

FROM node:lts-bookworm-slim

WORKDIR /app/stock-wrapper
COPY StockWise/stock-wrapper/package.json ./
COPY StockWise/stock-wrapper/src ./src

COPY --from=skill-package /dist/*.tgz /tmp/stock-analysis-skill.tgz
RUN npm install --omit=dev --prefix /app/stock-skill-runtime /tmp/stock-analysis-skill.tgz \
    && rm /tmp/stock-analysis-skill.tgz

WORKDIR /app/stock-wrapper
ENV NODE_ENV=production
ENV PORT=3001
ENV STOCK_SKILL_PATH=/app/stock-skill-runtime/node_modules/@stockwise/stock-analysis-skill
ENV STOCK_SKILL_CLI=/app/stock-skill-runtime/node_modules/@stockwise/stock-analysis-skill/bin/stock-analysis.js
EXPOSE 3001

CMD ["node", "src/server.js"]

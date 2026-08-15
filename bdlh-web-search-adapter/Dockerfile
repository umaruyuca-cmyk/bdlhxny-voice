FROM node:20-alpine

WORKDIR /app

COPY package.json ./
COPY src ./src

ENV NODE_ENV=production
ENV PORT=3002

EXPOSE 3002

USER node

CMD ["node", "src/server.js"]

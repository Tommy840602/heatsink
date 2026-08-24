FROM node:20-slim AS build
WORKDIR /app
ARG NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
ARG NPM_CONFIG_REGISTRY=https://registry.npmjs.org
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm install --global --force node@22.22.0 --registry "${NPM_CONFIG_REGISTRY}" \
    && node --version
COPY package.json package-lock.json ./
RUN npm ci --registry "${NPM_CONFIG_REGISTRY}"
COPY . .
RUN npm run build

FROM build AS runtime
ENV NODE_ENV=production
EXPOSE 3000
CMD ["npm", "run", "start"]

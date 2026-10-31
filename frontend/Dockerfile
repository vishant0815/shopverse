# Three stages: install dependencies, build, then a small image that only runs the app.

FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:22-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
# The API routes are compiled into the build, so service addresses are needed here.
ARG USERS_API_URL=http://users:8000
ARG PRODUCTS_API_URL=http://products:8000
ARG ORDERS_API_URL=http://orders:8000
ARG PAYMENTS_API_URL=http://payments:8000
ARG NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=
ENV USERS_API_URL=$USERS_API_URL \
    PRODUCTS_API_URL=$PRODUCTS_API_URL \
    ORDERS_API_URL=$ORDERS_API_URL \
    PAYMENTS_API_URL=$PAYMENTS_API_URL \
    NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=$NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
# Run as the unprivileged "node" user that ships with the image.
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]

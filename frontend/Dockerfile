# Stage 1: Build the React app
FROM node:18-alpine AS build

WORKDIR /app

# Add node_modules/.bin to PATH so vite is found
ENV PATH="/app/node_modules/.bin:$PATH"

# Copy package files first for better layer caching
COPY package.json package-lock.json ./

# Install deps — npm ci is faster (clean install from lockfile)
RUN --mount=type=cache,target=/root/.npm \
    npm ci

# Copy source code
COPY . .

# Build for production (Vite reads ARGs via import.meta.env)
RUN vite build

# Stage 2: Serve with Nginx
FROM nginx:alpine

# Copy custom nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built files from build stage
COPY --from=build /app/dist /usr/share/nginx/html

# Expose port 80
EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]

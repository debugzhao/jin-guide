FROM node:20-alpine
WORKDIR /app
COPY package*.json .
RUN npm ci --registry=https://registry.npmmirror.com --no-audit --no-fund
COPY . .
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_BASE_PATH=
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV NEXT_BASE_PATH=${NEXT_BASE_PATH}
RUN npm run build
CMD ["npm", "run", "start"]

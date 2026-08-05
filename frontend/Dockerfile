FROM node:20-alpine AS build
WORKDIR /app

COPY package*.json ./

# ✅ 强制安装 devDependencies（vite 在 devDependencies 里）
RUN npm ci --include=dev

COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80

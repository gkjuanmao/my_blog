FROM node:22-alpine

WORKDIR /app

# 国内镜像源（容器内无宿主 .npmrc）
RUN npm config set registry https://registry.npmmirror.com

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .

# apiBase 必须在构建期固化（客户端 bundle 经 SSR payload 读取；缺 env 会静默回落 localhost）
ENV NUXT_PUBLIC_API_BASE=/api/v1/

RUN npm run build

EXPOSE 3000

CMD ["node", ".output/server/index.mjs"]

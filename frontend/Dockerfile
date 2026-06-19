FROM node:22-alpine

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

EXPOSE 5173

CMD ["sh", "-c", "env | grep ^VITE_ > .env.local && npm run dev -- --host 0.0.0.0"]

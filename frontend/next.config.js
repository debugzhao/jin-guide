/** @type {import('next').NextConfig} */
const basePath = process.env.NEXT_BASE_PATH || ''

const nextConfig = {
  reactStrictMode: true,
  basePath,
  // nginx 的 `location /wenjin/` 前缀规则会把不带斜杠的 /wenjin 301 到 /wenjin/；
  // Next 默认又会把 /wenjin/ 308 回 /wenjin，两边互相重定向成死循环。
  // 只在挂了 basePath（即子路径部署）时开启 trailingSlash 让两边斜杠语义一致；
  // 本地开发 basePath 为空，不受影响。
  trailingSlash: !!basePath,
}

module.exports = nextConfig

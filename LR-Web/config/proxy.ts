/**
 * @name 代理的配置
 * @see 在生产环境 代理是无法生效的，所以这里没有生产环境的配置
 * -------------------------------
 * The agent cannot take effect in the production environment
 * so there is no configuration of the production environment
 * For details, please see
 * https://pro.ant.design/docs/deploy
 *
 * @doc https://umijs.org/docs/guides/proxy
 */
const takeoutViaStaticProxy = process.env.LR_TAKEOUT_VIA_STATIC === 'true';

export default {
  dev: {
    '/api/': {
      target: process.env.LR_API_URL || 'http://127.0.0.1:8080',
      changeOrigin: true,
      ws: true,
    },
    '/health': {
      target: process.env.LR_API_URL || 'http://127.0.0.1:8080',
      changeOrigin: true,
    },
    // 机器人本机 BookArm 服务。受管部署使用私有 Unix socket；Umi
    // 开发服务器不能直接代理 Unix socket。可将请求交给本机静态服务
    // （LR_TAKEOUT_VIA_STATIC=true），由它转发到受管 socket；也可显式
    // 设置 LR_TAKEOUT_URL 使用兼容的 TCP 服务。
    // 生产环境代理不生效，使用 Nginx 同源反向代理。
    '/bookarm-api/': {
      target:
        process.env.LR_TAKEOUT_URL ||
        (takeoutViaStaticProxy
          ? 'http://127.0.0.1:8000'
          : 'http://127.0.0.1:9'),
      changeOrigin: true,
      pathRewrite: takeoutViaStaticProxy
        ? { '^/bookarm-api/': '/bookarm-api/' }
        : { '^/bookarm-api/': '/api/' },
    },
  },
  /**
   * @name 详细的代理配置
   * @doc https://github.com/chimurai/http-proxy-middleware
   */
  test: {},
  pre: {
    '/api/': {
      target: 'your pre url',
      changeOrigin: true,
    },
    '/bookarm-api/': {
      target: 'your pre url',
      changeOrigin: true,
      pathRewrite: { '^/bookarm-api/': '/api/' },
    },
  },
};

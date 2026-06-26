module.exports = {
  apps: [
    {
      name: "quant-backend",
      script: "server.js",
      cwd: "./",
      watch: false,
      autorestart: true,
      max_restarts: 10,
      restart_delay: 2000,
      log_date_format: "YYYY-MM-DD HH:mm Z",
      error_file: "logs/pm2-error.log",
      out_file: "logs/pm2-out.log",
      env: {
        PYTHONUNBUFFERED: "1"
      }
    }
  ]
};

module.exports = {
  apps: [{
    name: "quant-engine",
    script: "start_all.py",
    interpreter: "python3",
    watch: false,
    autorestart: true,
    max_restarts: 10,
    restart_delay: 5000,
    time: true,
    kill_timeout: 15000,
    env: {
      POLARS_IGNORE_TIMEZONE_PARSE_ERROR: "1"
    }
  }]
};

module.exports = {
  apps: [{
    name: "quant-engine",
    script: "start_all.py",
    interpreter: "venv/Scripts/python.exe",
    cwd: "C:/Users/Amarjeet Singh/quant_algo_test",
    watch: false,
    autorestart: true,
    max_restarts: 10,
    restart_delay: 5000,
    time: true,
    env: {
      POLARS_IGNORE_TIMEZONE_PARSE_ERROR: "1"
    }
  }]
};

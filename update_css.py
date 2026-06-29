import re

with open('src/web/templates/intelligence_lab.html', 'r', encoding='utf-8') as f:
    content = f.read()

new_css = """
        :root {
            --bg: #020617;
            --bg2: rgba(15, 23, 42, 0.6);
            --card: rgba(30, 41, 59, 0.4);
            --card2: rgba(15, 23, 42, 0.4);
            --border: rgba(255,255,255,0.06);
            --border2: rgba(255,255,255,0.12);
            --text: #f8fafc;
            --text2: #94a3b8;
            --text3: #64748b;
            --primary: #3b82f6;
            --success: #10b981;
            --success-glow: rgba(16,185,129,0.4);
            --danger: #ef4444;
            --danger-glow: rgba(239,68,68,0.4);
            --warning: #f59e0b;
            --accent: #8b5cf6;
            --cyan: #06b6d4;
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: 'Outfit', sans-serif;
            background: var(--bg);
            background-image: 
                radial-gradient(circle at 15% 50%, rgba(59, 130, 246, 0.08), transparent 25%),
                radial-gradient(circle at 85% 30%, rgba(139, 92, 246, 0.08), transparent 25%);
            background-attachment: fixed;
            color: var(--text);
            min-height: 100vh;
        }

        .mono { font-family: 'JetBrains Mono', monospace; }

        /* NAV */
        .top-nav {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 16px 32px;
            background: rgba(15, 23, 42, 0.6);
            backdrop-filter: blur(16px);
            border-bottom: 1px solid var(--border);
            position: sticky;
            top: 0;
            z-index: 100;
        }
        .nav-brand {
            display: flex;
            align-items: center;
            gap: 12px;
            font-size: 20px;
            font-weight: 800;
            letter-spacing: -0.5px;
        }
        .nav-brand span { 
            background: linear-gradient(135deg, #3b82f6, #8b5cf6);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .nav-brand ion-icon { color: var(--primary); font-size: 24px; filter: drop-shadow(0 0 8px var(--primary)); }
        .nav-controls { display: flex; align-items: center; gap: 12px; }
        .nav-btn {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 16px;
            border-radius: 8px;
            border: 1px solid var(--border2);
            background: rgba(255,255,255,0.03);
            color: var(--text);
            font-family: 'Outfit', sans-serif;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            text-decoration: none;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .nav-btn:hover { 
            background: rgba(255,255,255,0.08); 
            border-color: var(--primary);
            box-shadow: 0 0 12px rgba(59,130,246,0.3);
            transform: translateY(-1px);
        }

        /* LAYOUT */
        .lab-body {
            padding: 32px;
            max-width: 1600px;
            margin: 0 auto;
            display: flex;
            flex-direction: column;
            gap: 24px;
        }

        /* SCORE BANNER */
        .health-banner {
            display: grid;
            grid-template-columns: auto 1fr 1fr 1fr 1fr 1fr;
            gap: 24px;
            background: var(--card);
            backdrop-filter: blur(12px);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 24px 32px;
            align-items: center;
            box-shadow: 0 4px 24px -4px rgba(0,0,0,0.5);
            transition: transform 0.3s ease;
        }
        .health-banner:hover { transform: translateY(-2px); }
        .health-score-box {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            width: 96px;
            height: 96px;
            border-radius: 50%;
            border: 3px solid var(--success);
            box-shadow: 0 0 16px var(--success-glow), inset 0 0 16px var(--success-glow);
            position: relative;
        }
        .health-score-val { font-size: 32px; font-weight: 800; line-height: 1; text-shadow: 0 0 10px rgba(255,255,255,0.3); }
        .health-score-lbl { font-size: 9px; font-weight: 700; letter-spacing: 1.5px; color: var(--text2); text-transform: uppercase; margin-top: 4px; }
        
        .health-stat { display: flex; flex-direction: column; gap: 6px; border-left: 1px solid var(--border); padding-left: 20px; }
        .health-stat-label { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; color: var(--text3); }
        .health-stat-val { font-size: 16px; font-weight: 700; color: var(--text); }
        .health-stat-sub { font-size: 12px; color: var(--text2); font-family: 'JetBrains Mono', monospace; opacity: 0.8; }
        
        .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
        .dot-green { background: var(--success); box-shadow: 0 0 8px var(--success); animation: pulse 2s infinite; }
        .dot-red { background: var(--danger); box-shadow: 0 0 8px var(--danger); }
        .dot-yellow { background: var(--warning); box-shadow: 0 0 8px var(--warning); }

        /* GRID */
        .panel-grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
        .panel-grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 24px; }

        /* CARD */
        .card {
            background: var(--card);
            backdrop-filter: blur(12px);
            border: 1px solid var(--border);
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 4px 20px -4px rgba(0,0,0,0.3);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .card:hover { border-color: var(--border2); transform: translateY(-2px); box-shadow: 0 8px 30px -4px rgba(0,0,0,0.4); }
        
        .card-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 18px 24px;
            border-bottom: 1px solid var(--border);
            background: rgba(0,0,0,0.2);
        }
        .card-title {
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 13px;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text2);
        }
        .card-title ion-icon { color: var(--primary); font-size: 18px; }
        .card-body { padding: 24px; }

        /* METRIC ROWS */
        .metric-row { display: flex; justify-content: space-between; align-items: center; padding: 12px 0; border-bottom: 1px solid var(--border); transition: background 0.2s; }
        .metric-row:hover { background: rgba(255,255,255,0.02); padding-left: 8px; padding-right: 8px; border-radius: 6px; }
        .metric-row:last-child { border-bottom: none; }
        .metric-key { font-size: 12px; color: var(--text2); font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
        .metric-val { font-size: 14px; font-weight: 700; font-family: 'JetBrains Mono', monospace; }

        /* BIG STAT */
        .big-stat-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; padding: 24px; }
        .big-stat {
            text-align: center;
            background: linear-gradient(180deg, rgba(255,255,255,0.03) 0%, rgba(255,255,255,0) 100%);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 24px 16px;
            transition: all 0.3s;
        }
        .big-stat:hover { border-color: rgba(255,255,255,0.1); background: rgba(255,255,255,0.05); }
        .big-stat-num { font-size: 36px; font-weight: 800; line-height: 1; font-family: 'JetBrains Mono', monospace; background: linear-gradient(135deg, #fff, #94a3b8); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .big-stat-label { font-size: 11px; color: var(--text3); text-transform: uppercase; letter-spacing: 1px; margin-top: 10px; font-weight: 700; }

        /* DECISION STREAM */
        .decision-feed { display: flex; flex-direction: column; gap: 8px; padding: 16px; max-height: 360px; overflow-y: auto; }
        .decision-feed::-webkit-scrollbar { width: 6px; }
        .decision-feed::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 6px; }
        .decision-item {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 10px 14px;
            border-radius: 10px;
            background: rgba(0,0,0,0.2);
            border: 1px solid var(--border);
            font-size: 12px;
            transition: all 0.2s;
        }
        .decision-item:hover { transform: translateX(4px); background: rgba(255,255,255,0.03); }
        .decision-item.accepted { border-left: 4px solid var(--success); box-shadow: -2px 0 10px var(--success-glow); }
        .decision-item.rejected { border-left: 4px solid var(--text3); }
        .decision-time { color: var(--text3); font-family: 'JetBrains Mono', monospace; min-width: 65px; font-size: 11px; }
        .decision-action { font-weight: 800; min-width: 45px; }
        .decision-reason { color: var(--text2); font-size: 12px; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        
        .badge { padding: 4px 10px; border-radius: 6px; font-size: 10px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.5px; }
        .badge-green { background: rgba(16,185,129,0.15); color: var(--success); box-shadow: 0 0 10px rgba(16,185,129,0.1); }
        .badge-gray { background: rgba(100,116,139,0.15); color: var(--text3); }
        .badge-blue { background: rgba(59,130,246,0.15); color: var(--primary); }
        .badge-red { background: rgba(239,68,68,0.15); color: var(--danger); box-shadow: 0 0 10px rgba(239,68,68,0.1); }
        .badge-yellow { background: rgba(245,158,11,0.15); color: var(--warning); box-shadow: 0 0 10px rgba(245,158,11,0.1); }
        .badge-purple { background: rgba(139,92,246,0.15); color: var(--accent); }

        /* REASON BARS */
        .reason-bars { padding: 20px 24px; display: flex; flex-direction: column; gap: 14px; }
        .reason-bar-item { display: flex; flex-direction: column; gap: 6px; }
        .reason-bar-label { font-size: 12px; color: var(--text2); display: flex; justify-content: space-between; font-weight: 600; }
        .reason-bar-track { height: 6px; background: rgba(0,0,0,0.3); border-radius: 6px; overflow: hidden; box-shadow: inset 0 1px 3px rgba(0,0,0,0.5); }
        .reason-bar-fill { height: 100%; background: linear-gradient(90deg, #3b82f6, #06b6d4); border-radius: 6px; transition: width 1s cubic-bezier(0.4, 0, 0.2, 1); }

        /* LIVE STATE GRID */
        .live-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; padding: 24px; }
        .live-tile {
            background: linear-gradient(135deg, rgba(255,255,255,0.03) 0%, rgba(255,255,255,0) 100%);
            border-radius: 12px;
            padding: 16px 20px;
            border: 1px solid var(--border);
            transition: all 0.3s;
            position: relative;
            overflow: hidden;
        }
        .live-tile::before { content: ""; position: absolute; top: 0; left: 0; width: 100%; height: 2px; background: linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent); opacity: 0; transition: opacity 0.3s; }
        .live-tile:hover { transform: translateY(-2px); border-color: rgba(255,255,255,0.15); background: rgba(255,255,255,0.05); }
        .live-tile:hover::before { opacity: 1; }
        .live-tile-label { font-size: 11px; color: var(--text3); text-transform: uppercase; letter-spacing: 1px; font-weight: 700; }
        .live-tile-val { font-size: 24px; font-weight: 800; margin-top: 6px; font-family: 'JetBrains Mono', monospace; text-shadow: 0 2px 10px rgba(0,0,0,0.5); }
        .live-tile-sub { font-size: 12px; color: var(--text2); margin-top: 4px; font-weight: 500; }

        /* ORDER FLOW */
        .flow-gauge { padding: 24px; display: flex; flex-direction: column; gap: 18px; }
        .flow-row { display: flex; align-items: center; gap: 16px; }
        .flow-label { font-size: 12px; color: var(--text2); min-width: 90px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; }
        .flow-bar-track { flex: 1; height: 10px; background: rgba(0,0,0,0.3); border-radius: 10px; overflow: hidden; box-shadow: inset 0 2px 4px rgba(0,0,0,0.5); }
        .flow-bar-fill-buy { height: 100%; background: linear-gradient(90deg, #059669, #10b981); border-radius: 10px; transition: width 0.5s cubic-bezier(0.4, 0, 0.2, 1); box-shadow: 0 0 10px var(--success-glow); }
        .flow-bar-fill-sell { height: 100%; background: linear-gradient(90deg, #dc2626, #ef4444); border-radius: 10px; transition: width 0.5s cubic-bezier(0.4, 0, 0.2, 1); box-shadow: 0 0 10px var(--danger-glow); }
        .flow-val { font-size: 14px; font-weight: 800; min-width: 70px; text-align: right; font-family: 'JetBrains Mono', monospace; }
        .delta-display {
            text-align: center;
            padding: 20px;
            border-radius: 12px;
            background: rgba(0,0,0,0.2);
            border: 1px solid var(--border);
            margin-top: 10px;
            box-shadow: inset 0 2px 10px rgba(0,0,0,0.2);
        }
        .delta-val { font-size: 42px; font-weight: 800; font-family: 'JetBrains Mono', monospace; text-shadow: 0 0 20px rgba(0,0,0,0.5); }
        .delta-label { font-size: 11px; color: var(--text3); text-transform: uppercase; letter-spacing: 1.5px; margin-top: 6px; font-weight: 700; }

        /* TRADE TABLE */
        .trade-table-wrap { padding: 0 8px 8px; overflow-x: auto; }
        table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 13px; }
        th {
            padding: 14px 16px;
            text-align: left;
            font-size: 11px;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text3);
            border-bottom: 1px solid var(--border2);
            background: rgba(0,0,0,0.2);
        }
        th:first-child { border-top-left-radius: 8px; }
        th:last-child { border-top-right-radius: 8px; }
        td {
            padding: 14px 16px;
            border-bottom: 1px solid var(--border);
            color: var(--text);
            font-family: 'JetBrains Mono', monospace;
            transition: background 0.2s;
        }
        tr:last-child td { border-bottom: none; }
        tr:hover td { background: rgba(255,255,255,0.03); }

        /* SYSTEM PROCESS CARDS */
        .proc-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; padding: 24px; }
        .proc-card {
            background: linear-gradient(180deg, rgba(255,255,255,0.03) 0%, rgba(255,255,255,0) 100%);
            border-radius: 12px;
            padding: 18px;
            border: 1px solid var(--border);
            border-top: 4px solid var(--text3);
            transition: transform 0.3s, box-shadow 0.3s;
        }
        .proc-card:hover { transform: translateY(-4px); box-shadow: 0 10px 20px -5px rgba(0,0,0,0.4); }
        .proc-card.healthy { border-top-color: var(--success); box-shadow: 0 4px 20px -10px var(--success-glow); }
        .proc-card.healthy:hover { box-shadow: 0 10px 30px -10px var(--success-glow); }
        .proc-card.warning { border-top-color: var(--warning); box-shadow: 0 4px 20px -10px rgba(245,158,11,0.3); }
        .proc-card.critical { border-top-color: var(--danger); box-shadow: 0 4px 20px -10px var(--danger-glow); }
        .proc-name { font-size: 13px; font-weight: 800; text-transform: uppercase; letter-spacing: 1px; color: var(--text); }
        .proc-pid { font-size: 11px; color: var(--text3); font-family: 'JetBrains Mono', monospace; background: rgba(0,0,0,0.3); padding: 2px 6px; border-radius: 4px; margin-left: 8px; }
        .proc-stats { display: flex; gap: 10px; margin-top: 14px; flex-wrap: wrap; }
        .proc-stat { background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.05); border-radius: 6px; padding: 4px 10px; font-size: 11px; font-family: 'JetBrains Mono', monospace; color: var(--text2); }

        /* PULSE ANIMATION */
        @keyframes pulse { 0%, 100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.1); opacity: 0.6; } }
        .pulse { animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite; }

        /* EMPTY STATE */
        .empty-state { text-align: center; padding: 60px 20px; color: var(--text3); font-size: 14px; font-weight: 500; }
        .empty-state ion-icon { font-size: 48px; display: block; margin-bottom: 16px; opacity: 0.3; filter: drop-shadow(0 0 10px rgba(255,255,255,0.1)); }

        /* SECTION TITLE */
        .section-title { display: flex; align-items: center; gap: 12px; font-size: 12px; font-weight: 800; text-transform: uppercase; letter-spacing: 2px; color: var(--text3); padding: 0 8px; }
        .section-title::after { content: ''; flex: 1; height: 1px; background: linear-gradient(90deg, var(--border2), transparent); }
        .section-title ion-icon { font-size: 16px; color: var(--text2); }
"""

content = re.sub(r'(?s)<style>.*?</style>', f'<style>\n{new_css}\n    </style>', content)

with open('src/web/templates/intelligence_lab.html', 'w', encoding='utf-8') as f:
    f.write(content)

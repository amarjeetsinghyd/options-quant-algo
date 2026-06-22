import os
import pandas as pd
import mplfinance as mpf
from datetime import timedelta

def generate_trade_chart(df, t, exit_time, net_pl, result, filename):
    try:
        chart_df = df.copy()
        chart_df.set_index('timestamp', inplace=True)
        
        # Slice the dataframe: 15 mins before entry, 5 mins after exit
        start_time = t['entry_time'] - timedelta(minutes=15)
        end_time = exit_time + timedelta(minutes=5)
        
        # Round to minute for pandas slicing
        start_time = start_time.replace(second=0, microsecond=0)
        end_time = end_time.replace(second=0, microsecond=0)
        
        sliced_df = chart_df.loc[start_time:end_time]
        if sliced_df.empty:
            print("Chart generation failed: No data in sliced timeframe.")
            return
            
        # Add-plots: VWAP, EMA_9, VFI
        addplots = [
            mpf.make_addplot(sliced_df['vwap'], color='#00a2ff', width=1.5),
            mpf.make_addplot(sliced_df['ema_9'], color='#ff9900', width=1.5),
            mpf.make_addplot(sliced_df['vfi'], panel=1, color='#b200ff', ylabel='VFI', type='line')
        ]
        
        out_dir = "src/web/static/charts"
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, filename)
        
        # Modern dark theme custom style
        mc = mpf.make_marketcolors(up='#00ff88', down='#ff3366', inherit=True)
        s  = mpf.make_mpf_style(marketcolors=mc, base_mpf_style='nightclouds', gridstyle=':')
        
        title = f"{t['symbol']} | {result} | Net P&L: Rs {net_pl:.2f}"
        
        mpf.plot(sliced_df, type='candle', addplot=addplots, 
                 title=title, style=s, volume=False, 
                 savefig=dict(fname=out_path, dpi=120, bbox_inches='tight'))
                 
        print(f"Chart saved to {out_path}")
    except Exception as e:
        print(f"Error generating chart: {e}")

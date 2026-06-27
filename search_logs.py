import json
import os

brain_dir = r'C:\Users\Amarjeet Singh\.gemini\antigravity\brain'
print("Searching all conversation transcripts...")

for folder in os.listdir(brain_dir):
    folder_path = os.path.join(brain_dir, folder)
    if os.path.isdir(folder_path):
        transcript_path = os.path.join(folder_path, '.system_generated', 'logs', 'transcript.jsonl')
        if os.path.exists(transcript_path):
            try:
                with open(transcript_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        try:
                            data = json.loads(line)
                            if data.get('type') == 'USER_INPUT':
                                content = data.get('content', '').lower()
                                if '10 minute' in content or '5 minute' in content or ('ema' in content and 'vwap' in content):
                                    print(f"\n--- Found in {folder} (Step {data.get('step_index')}) ---")
                                    print(data.get('content')[:800])
                        except:
                            pass
            except:
                pass
print("Done.")

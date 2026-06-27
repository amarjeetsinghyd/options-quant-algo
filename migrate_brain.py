import os
import shutil

DOCS_DIR = "docs"
BRAIN_DIR = "project-brain"

def append_file(src, dest, header=None):
    if not os.path.exists(src): return
    with open(src, 'r', encoding='utf-8') as f:
        content = f.read()
    with open(dest, 'a', encoding='utf-8') as f:
        if header:
            f.write(f"\n\n# {header}\n\n")
        f.write(content)

# 1. Architecture
arch_dest = os.path.join(BRAIN_DIR, "memory", "architecture.md")
append_file(os.path.join(DOCS_DIR, "architecture", "canonical_observation_dataset_v3.1_frozen.md"), arch_dest, "Canonical Observation Dataset v3.1")
append_file(os.path.join(DOCS_DIR, "architecture", "replay_engine_specification.md"), arch_dest, "Replay Engine Specification")

# 2. Institutional (to Overview)
overview_dest = os.path.join(BRAIN_DIR, "memory", "overview.md")
inst_dir = os.path.join(DOCS_DIR, "institution")
if os.path.exists(inst_dir):
    for doc in sorted(os.listdir(inst_dir)):
        append_file(os.path.join(inst_dir, doc), overview_dest, doc.replace(".md", ""))

# 3. Tasks
completed_dest = os.path.join(BRAIN_DIR, "tasks", "completed.md")
append_file(os.path.join(DOCS_DIR, "milestones", "Milestone-01-Foundation-Complete.md"), completed_dest, "Milestone 1 - Foundation Complete")

active_dest = os.path.join(BRAIN_DIR, "tasks", "active.md")
append_file(os.path.join(DOCS_DIR, "milestones", "Roadmap.md"), active_dest, "Project Roadmap")

# 4. Delete old docs folder
shutil.rmtree(DOCS_DIR)

print("Migration complete!")

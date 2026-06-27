import os
import re

def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)

# Create directory structure
ensure_dir("docs/institution")
ensure_dir("docs/architecture")
ensure_dir("docs/research/hypotheses")
ensure_dir("docs/research/experiments")
ensure_dir("docs/research/discoveries")
ensure_dir("docs/research/prompts")

ensure_dir("project-brain/graph/code_graph")
ensure_dir("project-brain/graph/capability_graph")
ensure_dir("project-brain/graph/knowledge_graph")

# Split overview.md -> docs/institution/
overview_path = "project-brain/memory/overview.md"
if os.path.exists(overview_path):
    with open(overview_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    sections = re.split(r'\n# (Document [\d\.]+ - [^\n]+)', content)
    
    for i in range(1, len(sections), 2):
        title = sections[i].strip()
        body = sections[i+1].strip()
        filename = f"docs/institution/{title}.md"
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"# {title}\n\n{body}")
            
    os.remove(overview_path)

# Split architecture.md -> docs/architecture/
arch_path = "project-brain/memory/architecture.md"
if os.path.exists(arch_path):
    with open(arch_path, 'r', encoding='utf-8') as f:
        content = f.read()
        
    sections = re.split(r'\n# (Canonical Observation Dataset v3.1|Replay Engine Specification)', content)
    
    for i in range(1, len(sections), 2):
        title = sections[i].strip()
        body = sections[i+1].strip()
        if "Canonical" in title:
            filename = "docs/architecture/Canonical Observation Dataset.md"
        else:
            filename = "docs/architecture/Replay Engine Specification.md"
            
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"# {title}\n\n{body}")
            
    os.remove(arch_path)

# Add new architecture stubs
with open("docs/architecture/QuantOS Runtime.md", "w") as f:
    f.write("# QuantOS Runtime\n\n*(Placeholder for runtime specs)*\n")
with open("docs/architecture/Engineering Specifications.md", "w") as f:
    f.write("# Engineering Specifications\n\n*(Placeholder for engineering specs)*\n")

# Create runtime memory stubs in project-brain/memory
with open("project-brain/memory/current_state.md", "w") as f:
    f.write("# Current State\n\nRepository is currently frozen after Architectural Refinement.\n")
with open("project-brain/memory/open_issues.md", "w") as f:
    f.write("# Open Issues\n\nNone.\n")

# Cleanup old graph files
for file in ["graph.json", "graph-index.json", "embeddings.json", "nodes.json", "edges.json"]:
    p = f"project-brain/graph/{file}"
    if os.path.exists(p): os.remove(p)

print("Extraction and structural refinement complete.")

$dirs = @(
    "project-brain/system",
    "project-brain/graph",
    "project-brain/memory",
    "project-brain/tasks",
    "project-brain/standards",
    "project-brain/reviews",
    "project-brain/templates",
    "project-brain/runtime",
    "project-brain/cache"
)

foreach ($d in $dirs) {
    New-Item -ItemType Directory -Force -Path $d
}

$files = @(
    "project-brain/system/system.md",
    "project-brain/system/planner.md",
    "project-brain/system/workflow.md",
    "project-brain/graph/graph.json",
    "project-brain/graph/graph-index.json",
    "project-brain/graph/embeddings.json",
    "project-brain/graph/nodes.json",
    "project-brain/graph/edges.json",
    "project-brain/runtime/context-loader.md",
    "project-brain/runtime/execution-engine.md",
    "project-brain/runtime/graph-retriever.md",
    "project-brain/runtime/memory-updater.md",
    "project-brain/runtime/graph-updater.md",
    "project-brain/runtime/review-engine.md",
    "project-brain/runtime/task-classifier.md",
    "project-brain/cache/recent-context.md",
    "project-brain/cache/last-plan.md",
    "project-brain/cache/recent-files.md",
    "project-brain/cache/recent-review.md",
    "project-brain/standards/typescript.md",
    "project-brain/standards/python.md",
    "project-brain/standards/security.md",
    "project-brain/standards/performance.md",
    "project-brain/standards/naming.md",
    "project-brain/standards/documentation.md",
    "project-brain/reviews/architecture-review.md",
    "project-brain/reviews/performance-review.md",
    "project-brain/reviews/security-review.md",
    "project-brain/reviews/code-quality.md",
    "project-brain/reviews/documentation-review.md",
    "project-brain/tasks/active.md",
    "project-brain/tasks/completed.md",
    "project-brain/tasks/failed.md",
    "project-brain/tasks/changelog.md",
    "project-brain/memory/overview.md",
    "project-brain/memory/architecture.md",
    "project-brain/memory/backend.md",
    "project-brain/memory/frontend.md",
    "project-brain/memory/database.md",
    "project-brain/memory/routing.md",
    "project-brain/memory/api.md",
    "project-brain/memory/dependencies.md",
    "project-brain/memory/patterns.md"
)

foreach ($f in $files) {
    if (-not (Test-Path $f)) {
        if ($f -match "\.json$") {
            Set-Content -Path $f -Value "{}"
        } else {
            Set-Content -Path $f -Value ""
        }
    }
}

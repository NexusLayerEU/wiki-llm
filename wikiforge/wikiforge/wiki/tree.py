"""Navigation tree and search index, in the shapes DATA_MODELS.md specifies."""
from collections import defaultdict
from datetime import datetime, timezone

from ..models import WikiPage
from .renderer import excerpt


def _slugify_category(name: str) -> str:
    from ..services.slugs import slugify

    return slugify(name)


def build_navigation_tree(project_name: str, pages: list[WikiPage]) -> dict:
    grouped: dict[str, list[WikiPage]] = defaultdict(list)
    for page in pages:
        grouped[page.category or "Uncategorised"].append(page)

    categories = []
    for name in sorted(grouped):
        children = sorted(grouped[name], key=lambda page: page.title.lower())
        categories.append(
            {
                "name": name,
                "slug": _slugify_category(name),
                "children": [
                    {
                        "name": page.title,
                        "slug": page.slug,
                        "subcategory": page.subcategory,
                        "sources": len(page.source_file_ids or []),
                        "word_count": page.word_count,
                    }
                    for page in children
                ],
            }
        )

    return {
        "project": project_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "categories": categories,
    }


def build_search_index(pages: list[WikiPage]) -> list[dict]:
    return [
        {
            "slug": page.slug,
            "title": page.title,
            "category": page.category,
            "snippet": excerpt(page.content_md, 300),
            "topics": (page.frontmatter or {}).get("topics", []),
        }
        for page in pages
    ]


def build_graph(pages: list[WikiPage]) -> dict:
    """Cross-reference network. Edges are de-duplicated on the unordered pair, so a
    mutual link between two pages is one edge, not two."""
    known = {page.slug for page in pages}
    nodes = [
        {
            "slug": page.slug,
            "title": page.title,
            "category": page.category,
            "word_count": page.word_count,
            "degree": 0,
        }
        for page in pages
    ]
    by_slug = {node["slug"]: node for node in nodes}

    seen: set[tuple[str, str]] = set()
    edges = []
    for page in pages:
        for ref in page.cross_refs or []:
            target = ref.get("slug")
            if not target or target not in known or target == page.slug:
                continue
            key = tuple(sorted((page.slug, target)))
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                {
                    "source": page.slug,
                    "target": target,
                    "weight": round(float(ref.get("relevance", 0.0) or 0.0), 4),
                }
            )
            by_slug[page.slug]["degree"] += 1
            by_slug[target]["degree"] += 1

    return {"nodes": nodes, "edges": edges}

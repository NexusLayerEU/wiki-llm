# WikiForge — Wiki Engine

## Responsibilities

The wiki engine handles:
1. Rendering Markdown wiki pages to HTML
2. Building the navigation tree from wiki page categories
3. Inserting cross-reference links into page content
4. Serving wiki pages via the FastAPI application
5. Exporting wiki as a static site

## Markdown Renderer

```python
# wikiforge/wiki/renderer.py

import markdown
from markdown.extensions.codehilite import CodeHiliteExtension
from markdown.extensions.tables import TableExtension
from markdown.extensions.toc import TocExtension
from markdown.extensions.fenced_code import FencedCodeExtension


class WikiRenderer:
    """Renders wiki Markdown to HTML with styling and cross-references."""

    def __init__(self):
        self.md = markdown.Markdown(
            extensions=[
                FencedCodeExtension(),
                CodeHiliteExtension(linenums=False, css_class="highlight"),
                TableExtension(),
                TocExtension(permalink=True, slugify=self._slugify),
                "md_in_html",
            ]
        )

    def render(self, content_md: str, context: dict) -> str:
        """Render Markdown to full HTML page.

        Args:
            content_md: Markdown content
            context: Dict with keys: title, cross_refs, project_slug, nav_tree
        """
        # Inject cross-reference links
        content_md = self._inject_crosslinks(content_md, context.get("cross_refs", []))

        # Render Markdown → HTML body
        self.md.reset()
        body_html = self.md.convert(content_md)
        toc = self.md.toc  # Table of contents HTML

        # Wrap in full page template
        return self._page_template(
            title=context.get("title", "Wiki Page"),
            body=body_html,
            toc=toc,
            cross_refs=context.get("cross_refs", []),
            project_slug=context.get("project_slug", ""),
        )

    def render_fragment(self, content_md: str) -> str:
        """Render Markdown to HTML fragment (no page wrapper)."""
        self.md.reset()
        return self.md.convert(content_md)

    def _inject_crosslinks(self, content: str, cross_refs: list[dict]) -> str:
        """Append cross-reference section to Markdown content."""
        if not cross_refs:
            return content

        links_md = "\n\n---\n\n## Related Pages\n\n"
        for ref in sorted(cross_refs, key=lambda r: r.get("relevance", 0), reverse=True):
            slug = ref["slug"]
            title = ref["title"]
            relevance = ref.get("relevance", 0)
            reason = ref.get("reason", "")
            links_md += f"- [{title}](./{slug}.html)"
            if reason:
                links_md += f" — {reason}"
            links_md += "\n"

        return content + links_md

    def _page_template(self, title: str, body: str, toc: str,
                       cross_refs: list, project_slug: str) -> str:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — WikiForge</title>
<link rel="stylesheet" href="/static/wiki.css">
</head>
<body>
<nav class="wiki-sidebar">
  <div class="wiki-toc">{toc}</div>
</nav>
<main class="wiki-main">
  <article class="wiki-content">{body}</article>
</main>
<script src="/static/wiki.js"></script>
</body>
</html>"""

    @staticmethod
    def _slugify(value, separator="-"):
        import re
        value = re.sub(r"[^\w\s-]", "", value.lower())
        return re.sub(r"[\s_]+", separator, value).strip(separator)
```

## Navigation Tree Builder

```python
# wikiforge/wiki/tree.py

from dataclasses import dataclass, field


@dataclass
class TreeNode:
    name: str
    slug: str
    children: list["TreeNode"] = field(default_factory=list)
    page_count: int = 0
    word_count: int = 0


def build_navigation_tree(wiki_pages: list) -> dict:
    """Build hierarchical navigation tree from flat list of wiki pages.

    Groups pages by category → subcategory → page.
    """
    categories: dict[str, dict] = {}

    for page in wiki_pages:
        cat = page.category
        subcat = page.subcategory

        if cat not in categories:
            categories[cat] = {
                "name": cat,
                "slug": _slugify(cat),
                "subcategories": {},
                "pages": [],
            }

        if subcat:
            if subcat not in categories[cat]["subcategories"]:
                categories[cat]["subcategories"][subcat] = {
                    "name": subcat,
                    "slug": _slugify(subcat),
                    "pages": [],
                }
            categories[cat]["subcategories"][subcat]["pages"].append({
                "name": page.title,
                "slug": page.slug,
                "word_count": page.word_count,
                "sources": len(page.source_file_ids) if page.source_file_ids else 0,
            })
        else:
            categories[cat]["pages"].append({
                "name": page.title,
                "slug": page.slug,
                "word_count": page.word_count,
                "sources": len(page.source_file_ids) if page.source_file_ids else 0,
            })

    # Convert to output format
    tree = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "categories": [],
    }

    for cat_name in sorted(categories.keys()):
        cat = categories[cat_name]
        cat_node = {
            "name": cat["name"],
            "slug": cat["slug"],
            "children": [],
        }

        # Add subcategories
        for subcat_name in sorted(cat["subcategories"].keys()):
            subcat = cat["subcategories"][subcat_name]
            subcat_node = {
                "name": subcat["name"],
                "slug": subcat["slug"],
                "children": sorted(subcat["pages"], key=lambda p: p["name"]),
            }
            cat_node["children"].append(subcat_node)

        # Add direct pages (no subcategory)
        for page in sorted(cat["pages"], key=lambda p: p["name"]):
            cat_node["children"].append(page)

        tree["categories"].append(cat_node)

    return tree
```

## Cross-Linker

```python
# wikiforge/wiki/crosslinker.py

import numpy as np


class CrossLinker:
    """Manages cross-references between wiki pages using embeddings."""

    def __init__(self, similarity_threshold: float = 0.5):
        self.threshold = similarity_threshold

    def find_related(self, page_embedding: np.ndarray,
                     all_pages: list, exclude_slug: str) -> list[dict]:
        """Find pages related to the given embedding.

        Returns list of {slug, title, similarity} sorted by similarity.
        """
        results = []

        for page in all_pages:
            if page.slug == exclude_slug:
                continue
            if page.embedding is None:
                continue

            other_emb = np.frombuffer(page.embedding, dtype=np.float32)
            similarity = self._cosine_similarity(page_embedding, other_emb)

            if similarity >= self.threshold:
                results.append({
                    "slug": page.slug,
                    "title": page.title,
                    "similarity": round(float(similarity), 3),
                })

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:10]  # Top 10 most related

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def update_bidirectional(self, page_slug: str, related: list[dict], db) -> None:
        """Update cross-references in both directions.

        If page A references page B, page B should also reference page A.
        """
        for ref in related:
            other_page = db.get_by(WikiPage, slug=ref["slug"])
            if other_page and other_page.cross_refs is not None:
                # Check if reverse reference already exists
                existing_slugs = [r["slug"] for r in other_page.cross_refs]
                if page_slug not in existing_slugs:
                    other_page.cross_refs.append({
                        "slug": page_slug,
                        "title": db.get_by(WikiPage, slug=page_slug).title,
                        "relevance": ref["similarity"],
                    })
        db.commit()
```

## Static Site Exporter

```python
# wikiforge/wiki/exporter.py

class StaticSiteExporter:
    """Export wiki as a self-contained static site."""

    def export(self, project, output_path: str):
        """Export all wiki pages as a static HTML site.

        Creates:
        output_path/
        ├── index.html          # Wiki home page with navigation
        ├── pages/
        │   ├── page-slug.html  # Individual wiki pages
        │   └── ...
        ├── search.json         # Search index for client-side search
        ├── tree.json           # Navigation tree
        └── assets/
            ├── wiki.css        # Styles
            └── wiki.js         # Client-side search + navigation
        """
        output = Path(output_path)
        output.mkdir(parents=True, exist_ok=True)
        (output / "pages").mkdir(exist_ok=True)
        (output / "assets").mkdir(exist_ok=True)

        renderer = WikiRenderer()
        pages = db.query(WikiPage).all()
        tree = build_navigation_tree(pages)

        # Render each page
        for page in pages:
            html = renderer.render(page.content_md, {
                "title": page.title,
                "cross_refs": page.cross_refs or [],
                "project_slug": project.slug,
                "nav_tree": tree,
            })
            (output / "pages" / f"{page.slug}.html").write_text(html)

        # Generate index page
        index_html = self._render_index(project, tree, pages)
        (output / "index.html").write_text(index_html)

        # Write search index
        search_index = [{
            "slug": p.slug,
            "title": p.title,
            "category": p.category,
            "content": p.content_md[:500],
            "topics": p.frontmatter.get("topics", []) if p.frontmatter else [],
        } for p in pages]
        (output / "search.json").write_text(json.dumps(search_index))

        # Write tree
        (output / "tree.json").write_text(json.dumps(tree, indent=2))

        # Copy static assets
        self._copy_assets(output / "assets")
```

## Search Index

The search system supports two modes:

### Client-Side Search (Static Export)
Uses a JSON index (`search.json`) with simple substring matching in JavaScript.

### Server-Side Semantic Search (Live Wiki)
```python
# wikiforge/services/search_service.py

class SearchService:
    """Semantic search over wiki pages using embeddings."""

    def __init__(self, llm_provider, db):
        self.provider = llm_provider
        self.db = db

    async def search(self, query: str, project_id: str,
                     max_results: int = 5) -> list[dict]:
        """Search wiki pages by semantic similarity to query.

        1. Embed the query
        2. Compare with all page embeddings
        3. Return top matches with relevance scores
        """
        query_embedding = await self.provider.embed(query)
        query_vec = np.array(query_embedding, dtype=np.float32)

        pages = self.db.query(WikiPage).all()
        results = []

        for page in pages:
            if page.embedding is None:
                continue

            page_vec = np.frombuffer(page.embedding, dtype=np.float32)
            similarity = float(np.dot(query_vec, page_vec) / (
                np.linalg.norm(query_vec) * np.linalg.norm(page_vec)
            ))

            if similarity > 0.3:
                results.append({
                    "slug": page.slug,
                    "title": page.title,
                    "category": page.category,
                    "relevance": round(similarity, 3),
                    "snippet": page.content_md[:200] + "...",
                })

        results.sort(key=lambda x: x["relevance"], reverse=True)
        return results[:max_results]

    async def rag_query(self, question: str, project_id: str,
                        format: str = "markdown") -> dict:
        """Answer a question using RAG over wiki content.

        1. Find relevant pages via semantic search
        2. Build context from top pages
        3. Send to LLM with RAG prompt
        """
        # Find relevant pages
        relevant = await self.search(question, project_id, max_results=5)
        if not relevant:
            return {"answer": "No relevant information found in the wiki.", "sources": []}

        # Build context
        context_pages = []
        for r in relevant:
            page = self.db.get_by(WikiPage, slug=r["slug"])
            if page:
                context_pages.append({
                    "title": page.title,
                    "slug": page.slug,
                    "content": page.content_md,
                })

        # RAG query to LLM
        prompt = render_template("rag_query.j2", {
            "context_pages": context_pages,
            "question": question,
            "format": format,
        })

        response = await self.provider.complete(LLMRequest(
            system_prompt="You are a wiki knowledge assistant. Answer using only the provided context.",
            user_prompt=prompt,
            temperature=0.2,
        ))

        return {
            "answer": response.content,
            "sources": [{"filename": r["title"], "wiki_page": r["slug"],
                         "relevance": r["relevance"]} for r in relevant],
            "confidence": relevant[0]["relevance"] if relevant else 0.0,
            "wiki_pages": [r["slug"] for r in relevant],
        }
```

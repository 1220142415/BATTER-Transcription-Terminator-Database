// Preserve directory bookmarks from before the separate home page existed.
const homeQuery = new URLSearchParams(location.search);
if (location.hash === "#genome-directory" || ["q", "search", "query", "accession", "assembly", "taxon", "study", "assay", "evidence", "signal", "sort", "order"].some((key) => homeQuery.has(key))) {
  location.replace(`genomes.html${location.search}${location.hash}`);
}

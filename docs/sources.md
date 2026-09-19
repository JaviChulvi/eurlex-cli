# Source attribution

`eurlex-cli` queries and retrieves from the Publications Office of the European Union:

- CELLAR public SPARQL: <https://publications.europa.eu/webapi/rdf/sparql>
- CELLAR publication retrieval: <https://op.europa.eu/en/web/cellar/cellar-data/publications>
- CELLAR overview: <https://op.europa.eu/en/web/cellar/cellar-data>
- EUR-Lex reuse details: <https://eur-lex.europa.eu/content/help/data-reuse/reuse-contents-eurlex-details.html>

The software records the exact discovered item URI, actual normalized HTTPS request URL, exact final response URL, and whether transport was upgraded. It also keeps selected and response MIME types distinct. `cdm:work_date_document` is exposed as `document_date` only after shape/cardinality validation; publication, entry-into-force, and other dates are not guessed. Repository fixtures are synthetic and do not redistribute EU document bodies. A user's locally retrieved artifacts remain under that user's control and responsibility. Free public retrieval is not a blanket statement about reuse rights for every source item.

// Citation counts from Semantic Scholar. Each element's data-semantic-scholar-id
// is either a Semantic Scholar paper id or "DOI:<doi>"; both are accepted by the
// batch API, which returns results in request order (null when not found).
const citationCountElements = document.querySelectorAll('[data-semantic-scholar-id]');
citationCountElements.forEach(element => {
    const id = element.getAttribute('data-semantic-scholar-id');
    if (id) {
        element.setAttribute('data-semantic-scholar-id', id.toLowerCase());
    }
});

const semanticScholarIds = Array.from(new Set(Array.from(citationCountElements).map(element => element.getAttribute('data-semantic-scholar-id')).filter(id => id)));
const cacheKeyFor = id => `semanticScholarCitationCount:${id}`;
const cacheMaxAge = 1 * 60 * 60 * 1000;  // 1 hour

const readCache = id => {
    try {
        return JSON.parse(localStorage.getItem(cacheKeyFor(id)));
    } catch (e) {
        return null;
    }
};

const uncachedSemanticScholarIds = semanticScholarIds.filter(id => {
    const cached = readCache(id);
    return !cached || !cached.paperId || Date.now() - cached.timestamp > cacheMaxAge;
});

let showSemanticScholarCitationCount = () => {
    semanticScholarIds.forEach(id => {
        const cached = readCache(id);
        if (!cached || cached.citationCount == null || !cached.paperId) {
            return;
        }
        document.querySelectorAll(`[data-semantic-scholar-id="${id}"]`).forEach(element => {
            element.innerHTML = `<a class="badge badge-pill badge-publication badge-info" href="https://www.semanticscholar.org/paper/${cached.paperId}" target="_blank"><i class="ai ai-semantic-scholar"></i> ${parseInt(cached.citationCount).toLocaleString()} citations</a>`;
        });
    });
};

// The batch endpoint takes at most 500 ids per request.
const fetchCitationCounts = ids => fetch('https://api.semanticscholar.org/graph/v1/paper/batch?fields=citationCount', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json'
    },
    // Ids are lowercased for matching; send the DOI prefix in the API's documented case.
    body: JSON.stringify({ ids: ids.map(id => id.replace(/^doi:/, 'DOI:')) })
}).then(response => {
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }
    return response.json();
}).then(data => {
    data.forEach((paper, i) => {
        if (!paper) {
            return;
        }
        localStorage.setItem(cacheKeyFor(ids[i]), JSON.stringify({
            paperId: paper.paperId,
            citationCount: paper.citationCount,
            timestamp: Date.now()
        }));
    });
});

if (uncachedSemanticScholarIds.length > 0) {
    const batches = [];
    for (let i = 0; i < uncachedSemanticScholarIds.length; i += 500) {
        batches.push(uncachedSemanticScholarIds.slice(i, i + 500));
    }
    Promise.all(batches.map(fetchCitationCounts)).catch(error => {
        console.error('Error fetching Semantic Scholar data:', error);
    }).finally(showSemanticScholarCitationCount);
} else {
    showSemanticScholarCitationCount();
}

# Rubric-grounded LLM-as-judge retrieval comparison

Judge model: `gpt-5.6-luna`. Retrieval unit: multi sub-query per engine (k=10). Topics scored: 30 (683a58c9a7e7fe4e7695846f, 683a58c9a7e7fe4e76958488, 683a58c9a7e7fe4e7695848b, 683a58c9a7e7fe4e76958498, 684397d188c1deceb49af31d, 684397d188c1deceb49af325, 684397d188c1deceb49af32d, 6847465956a0f6376a60535d, 6847465956a0f6376a605360, 6847465956a0f6376a605367, 6847465956a0f6376a605387, 6847465956a0f6376a605391, 6847465956a0f6376a6053a0, 6847465956a0f6376a6053c9, 6847465956a0f6376a6053ca, 6847465956a0f6376a6053fb, 6847465956a0f6376a605404, 6847465956a0f6376a60542a, 6847465956a0f6376a60542d, 6847465956a0f6376a605433, 6847465956a0f6376a60543d, 6847465956a0f6376a605440, 6847465956a0f6376a605476, 6847465956a0f6376a60547e, 6847465956a0f6376a60547f, 6847465956a0f6376a605492, 6847465956a0f6376a605493, 6847465956a0f6376a6054a7, 6847465956a0f6376a6054ad, 6847465956a0f6376a6054be).

Coverage = Σ weight of info criteria covered by >=1 of the engine's retrieved docs, / Σ weight of all info criteria. lenient = judge grade>=1, strict = grade>=2. mUMBRELA = mean holistic 0-3 relevance over the engine's unique retrieved docs. nDCG@10 = per-sub-need, UMBRELA as gain, averaged over sub-needs.

## Aggregate per engine

| engine | cov(lenient) | cov(strict) | mUMBRELA | nDCG@10 |
|---|--:|--:|--:|--:|
| semantic | 0.902 | 0.464 | 1.799 | 0.958 |
| keyword | 0.913 | 0.545 | 1.805 | 0.964 |
| ssr | 0.836 | 0.388 | 1.548 | 0.908 |
| lucene_bool | 0.774 | 0.326 | 1.371 | 0.906 |

## Per-topic detail

### 683a58c9a7e7fe4e7695846f — domain=STEM, breadth=Moderate, nesting=Intermediate, expl=Medium (8 info criteria)

| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |
|---|--:|--:|--:|--:|--:|--:|
| semantic | 56 | 56 | 1.000 | 0.724 | 1.714 | 0.944 |
| keyword | 60 | 60 | 1.000 | 0.724 | 1.683 | 0.940 |
| ssr | 59 | 59 | 0.862 | 0.724 | 1.407 | 0.839 |
| lucene_bool | 60 | 60 | 1.000 | 0.517 | 1.600 | 0.944 |

### 683a58c9a7e7fe4e76958488 — domain=AI & ML, breadth=Moderate, nesting=Shallow, expl=Low (15 info criteria)

| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |
|---|--:|--:|--:|--:|--:|--:|
| semantic | 58 | 58 | 0.898 | 0.388 | 1.552 | 0.909 |
| keyword | 58 | 58 | 1.000 | 0.571 | 1.569 | 0.945 |
| ssr | 31 | 31 | 0.959 | 0.429 | 1.806 | 0.961 |
| lucene_bool | 40 | 40 | 0.653 | 0.102 | 1.200 | 0.902 |

### 683a58c9a7e7fe4e7695848b — domain=AI & ML, breadth=Moderate, nesting=Deep, expl=High (13 info criteria)

| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |
|---|--:|--:|--:|--:|--:|--:|
| semantic | 58 | 58 | 0.935 | 0.457 | 1.690 | 0.962 |
| keyword | 58 | 58 | 0.935 | 0.674 | 1.845 | 0.968 |
| ssr | 52 | 52 | 0.717 | 0.435 | 1.558 | 0.909 |
| lucene_bool | 42 | 42 | 0.652 | 0.500 | 1.286 | 0.904 |

### 683a58c9a7e7fe4e76958498 — domain=General Consumer Research, breadth=Simple, nesting=Shallow, expl=Low (23 info criteria)

| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |
|---|--:|--:|--:|--:|--:|--:|
| semantic | 58 | 58 | 0.897 | 0.824 | 2.000 | 1.000 |
| keyword | 60 | 60 | 0.971 | 0.971 | 2.000 | 1.000 |
| ssr | 60 | 60 | 0.853 | 0.676 | 1.783 | 0.963 |
| lucene_bool | 60 | 60 | 0.971 | 0.794 | 1.900 | 0.995 |

### 684397d188c1deceb49af31d — domain=Historical Analysis, breadth=Moderate, nesting=Intermediate, expl=Medium (28 info criteria)

| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |
|---|--:|--:|--:|--:|--:|--:|
| semantic | 35 | 35 | 0.829 | 0.395 | 1.829 | 0.975 |
| keyword | 50 | 50 | 0.803 | 0.303 | 1.460 | 0.933 |
| ssr | 44 | 44 | 0.789 | 0.289 | 1.636 | 0.967 |
| lucene_bool | 40 | 40 | 0.711 | 0.250 | 1.300 | 0.969 |

### 684397d188c1deceb49af325 — domain=Other, breadth=Moderate, nesting=Intermediate, expl=Medium (22 info criteria)

| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |
|---|--:|--:|--:|--:|--:|--:|
| semantic | 54 | 54 | 0.883 | 0.500 | 1.407 | 0.814 |
| keyword | 45 | 45 | 0.968 | 0.691 | 1.889 | 0.975 |
| ssr | 57 | 57 | 0.926 | 0.351 | 1.368 | 0.859 |
| lucene_bool | 48 | 48 | 0.968 | 0.489 | 1.688 | 0.962 |

### 684397d188c1deceb49af32d — domain=Hypotheticals & Philosophy, breadth=Moderate, nesting=Deep, expl=High (19 info criteria)

| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |
|---|--:|--:|--:|--:|--:|--:|
| semantic | 60 | 60 | 0.920 | 0.700 | 1.933 | 0.982 |
| keyword | 60 | 60 | 0.920 | 0.920 | 1.700 | 0.941 |
| ssr | 60 | 60 | 0.880 | 0.580 | 1.233 | 0.857 |
| lucene_bool | 60 | 60 | 0.860 | 0.500 | 1.200 | 0.948 |

### 6847465956a0f6376a60535d — domain=AI & ML, breadth=Moderate, nesting=Intermediate, expl=Medium (18 info criteria)

| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |
|---|--:|--:|--:|--:|--:|--:|
| semantic | 50 | 50 | 1.000 | 0.800 | 1.860 | 0.994 |
| keyword | 50 | 50 | 0.880 | 0.780 | 1.980 | 0.999 |
| ssr | 50 | 50 | 1.000 | 0.560 | 1.200 | 0.964 |
| lucene_bool | 49 | 49 | 0.600 | 0.220 | 1.245 | 0.896 |

### 6847465956a0f6376a605360 — domain=Historical Analysis, breadth=Simple, nesting=Shallow, expl=Low (19 info criteria)

| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |
|---|--:|--:|--:|--:|--:|--:|
| semantic | 50 | 50 | 0.763 | 0.474 | 1.980 | 0.995 |
| keyword | 50 | 50 | 0.842 | 0.632 | 1.980 | 0.998 |
| ssr | 49 | 49 | 0.789 | 0.474 | 1.980 | 1.000 |
| lucene_bool | 50 | 50 | 0.737 | 0.342 | 1.620 | 0.960 |

### 6847465956a0f6376a605367 — domain=Historical Analysis, breadth=Moderate, nesting=Deep, expl=Medium (18 info criteria)

| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |
|---|--:|--:|--:|--:|--:|--:|
| semantic | 60 | 60 | 1.000 | 0.604 | 1.833 | 0.978 |
| keyword | 60 | 60 | 0.958 | 0.625 | 1.950 | 0.996 |
| ssr | 60 | 60 | 0.958 | 0.521 | 1.900 | 0.989 |
| lucene_bool | 60 | 60 | 0.854 | 0.458 | 1.850 | 0.986 |

### 6847465956a0f6376a605387 — domain=Business Planning & Research, breadth=Moderate, nesting=Shallow, expl=Medium (15 info criteria)

| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |
|---|--:|--:|--:|--:|--:|--:|
| semantic | 60 | 60 | 1.000 | 0.375 | 1.967 | 1.000 |
| keyword | 59 | 59 | 0.917 | 0.562 | 1.915 | 0.983 |
| ssr | 51 | 51 | 0.792 | 0.208 | 1.745 | 0.957 |
| lucene_bool | 59 | 59 | 0.833 | 0.062 | 1.305 | 0.893 |

### 6847465956a0f6376a605391 — domain=Business Planning & Research, breadth=Simple, nesting=Intermediate, expl=Medium (17 info criteria)

| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |
|---|--:|--:|--:|--:|--:|--:|
| semantic | 54 | 54 | 1.000 | 0.408 | 1.815 | 0.987 |
| keyword | 58 | 58 | 1.000 | 0.310 | 1.759 | 0.944 |
| ssr | 60 | 60 | 1.000 | 0.197 | 1.417 | 0.890 |
| lucene_bool | 59 | 59 | 0.958 | 0.197 | 1.203 | 0.880 |

### 6847465956a0f6376a6053a0 — domain=Technical Documentation, breadth=Simple, nesting=Intermediate, expl=Medium (17 info criteria)

| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |
|---|--:|--:|--:|--:|--:|--:|
| semantic | 56 | 56 | 1.000 | 0.239 | 1.839 | 0.963 |
| keyword | 60 | 60 | 0.958 | 0.366 | 1.967 | 0.996 |
| ssr | 60 | 60 | 0.831 | 0.282 | 1.867 | 0.987 |
| lucene_bool | 60 | 60 | 0.873 | 0.183 | 1.433 | 0.941 |

### 6847465956a0f6376a6053c9 — domain=Technical Documentation, breadth=Moderate, nesting=Deep, expl=Medium (22 info criteria)

| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |
|---|--:|--:|--:|--:|--:|--:|
| semantic | 58 | 58 | 0.897 | 0.397 | 1.948 | 0.988 |
| keyword | 60 | 60 | 0.926 | 0.574 | 2.000 | 1.000 |
| ssr | 60 | 60 | 0.956 | 0.353 | 1.833 | 0.984 |
| lucene_bool | 60 | 60 | 0.897 | 0.426 | 1.700 | 0.968 |

### 6847465956a0f6376a6053ca — domain=AI & ML, breadth=Simple, nesting=Deep, expl=Low (16 info criteria)

| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |
|---|--:|--:|--:|--:|--:|--:|
| semantic | 57 | 57 | 0.924 | 0.576 | 1.789 | 0.978 |
| keyword | 58 | 58 | 0.924 | 0.621 | 1.552 | 0.974 |
| ssr | 55 | 55 | 0.864 | 0.485 | 1.164 | 0.841 |
| lucene_bool | 52 | 52 | 0.864 | 0.379 | 1.000 | 0.871 |

### 6847465956a0f6376a6053fb — domain=Current Events, breadth=Moderate, nesting=Deep, expl=High (25 info criteria)

| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |
|---|--:|--:|--:|--:|--:|--:|
| semantic | 59 | 59 | 0.829 | 0.533 | 1.983 | 0.987 |
| keyword | 60 | 60 | 0.876 | 0.752 | 1.867 | 0.980 |
| ssr | 56 | 56 | 0.867 | 0.524 | 1.696 | 0.950 |
| lucene_bool | 60 | 60 | 0.686 | 0.429 | 1.200 | 0.846 |

### 6847465956a0f6376a605404 — domain=Historical Analysis, breadth=Moderate, nesting=Intermediate, expl=Low (27 info criteria)

| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |
|---|--:|--:|--:|--:|--:|--:|
| semantic | 57 | 57 | 0.923 | 0.800 | 1.930 | 0.955 |
| keyword | 60 | 60 | 0.954 | 0.938 | 1.983 | 1.000 |
| ssr | 52 | 52 | 0.892 | 0.662 | 1.423 | 0.890 |
| lucene_bool | 20 | 20 | 0.738 | 0.554 | 1.850 | 0.952 |

### 6847465956a0f6376a60542a — domain=Technical Documentation, breadth=Moderate, nesting=Intermediate, expl=Medium (22 info criteria)

| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |
|---|--:|--:|--:|--:|--:|--:|
| semantic | 60 | 60 | 1.000 | 0.614 | 1.950 | 0.992 |
| keyword | 60 | 60 | 1.000 | 0.301 | 1.800 | 0.952 |
| ssr | 60 | 60 | 0.964 | 0.349 | 1.850 | 0.939 |
| lucene_bool | 55 | 55 | 0.916 | 0.145 | 1.564 | 0.901 |

### 6847465956a0f6376a60542d — domain=Creative Writing, breadth=Moderate, nesting=Deep, expl=Medium (18 info criteria)

| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |
|---|--:|--:|--:|--:|--:|--:|
| semantic | 56 | 56 | 1.000 | 0.088 | 1.857 | 0.976 |
| keyword | 50 | 50 | 0.965 | 0.140 | 1.920 | 0.993 |
| ssr | 56 | 56 | 1.000 | 0.158 | 1.804 | 0.970 |
| lucene_bool | 58 | 58 | 0.965 | 0.140 | 1.638 | 0.968 |

### 6847465956a0f6376a605433 — domain=Business Planning & Research, breadth=Moderate, nesting=Intermediate, expl=High (18 info criteria)

| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |
|---|--:|--:|--:|--:|--:|--:|
| semantic | 60 | 60 | 0.846 | 0.115 | 1.650 | 0.960 |
| keyword | 60 | 60 | 1.000 | 0.481 | 1.700 | 0.974 |
| ssr | 55 | 55 | 0.885 | 0.096 | 1.218 | 0.905 |
| lucene_bool | 60 | 60 | 0.769 | 0.115 | 0.983 | 0.839 |

### 6847465956a0f6376a60543d — domain=Creative Writing, breadth=Simple, nesting=Intermediate, expl=Medium (14 info criteria)

| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |
|---|--:|--:|--:|--:|--:|--:|
| semantic | 50 | 50 | 0.932 | 0.682 | 1.920 | 0.984 |
| keyword | 50 | 50 | 1.000 | 0.682 | 1.900 | 0.990 |
| ssr | 50 | 50 | 0.864 | 0.273 | 1.500 | 0.893 |
| lucene_bool | 50 | 50 | 0.864 | 0.250 | 1.260 | 0.864 |

### 6847465956a0f6376a605440 — domain=Hypotheticals & Philosophy, breadth=Moderate, nesting=Deep, expl=Medium (17 info criteria)

| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |
|---|--:|--:|--:|--:|--:|--:|
| semantic | 58 | 58 | 0.947 | 0.500 | 1.983 | 0.999 |
| keyword | 60 | 60 | 1.000 | 0.711 | 1.917 | 0.964 |
| ssr | 59 | 59 | 0.921 | 0.605 | 1.576 | 0.818 |
| lucene_bool | 60 | 60 | 0.868 | 0.553 | 1.600 | 0.922 |

### 6847465956a0f6376a605476 — domain=Hypotheticals & Philosophy, breadth=Simple, nesting=Intermediate, expl=High (23 info criteria)

| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |
|---|--:|--:|--:|--:|--:|--:|
| semantic | 59 | 59 | 0.682 | 0.242 | 1.559 | 0.930 |
| keyword | 60 | 60 | 0.682 | 0.242 | 1.800 | 0.966 |
| ssr | 60 | 60 | 0.424 | 0.212 | 1.383 | 0.849 |
| lucene_bool | 60 | 60 | 0.394 | 0.167 | 1.300 | 0.931 |

### 6847465956a0f6376a60547e — domain=Technical Documentation, breadth=Simple, nesting=Deep, expl=Medium (27 info criteria)

| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |
|---|--:|--:|--:|--:|--:|--:|
| semantic | 45 | 45 | 0.628 | 0.138 | 1.689 | 0.959 |
| keyword | 50 | 50 | 0.638 | 0.202 | 1.720 | 0.965 |
| ssr | 40 | 40 | 0.372 | 0.064 | 1.600 | 0.977 |
| lucene_bool | 48 | 48 | 0.330 | 0.064 | 1.000 | 0.948 |

### 6847465956a0f6376a60547f — domain=Hypotheticals & Philosophy, breadth=Moderate, nesting=Shallow, expl=Low (20 info criteria)

| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |
|---|--:|--:|--:|--:|--:|--:|
| semantic | 57 | 57 | 0.915 | 0.186 | 1.789 | 0.966 |
| keyword | 60 | 60 | 0.898 | 0.373 | 1.900 | 0.981 |
| ssr | 59 | 59 | 0.780 | 0.186 | 1.186 | 0.751 |
| lucene_bool | 60 | 60 | 0.678 | 0.169 | 0.900 | 0.756 |

### 6847465956a0f6376a605492 — domain=AI & ML, breadth=High, nesting=Deep, expl=Low (15 info criteria)

| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |
|---|--:|--:|--:|--:|--:|--:|
| semantic | 49 | 49 | 0.818 | 0.341 | 1.837 | 0.972 |
| keyword | 49 | 49 | 0.818 | 0.341 | 1.857 | 0.941 |
| ssr | 40 | 40 | 0.682 | 0.250 | 1.275 | 0.749 |
| lucene_bool | 40 | 40 | 0.659 | 0.159 | 0.775 | 0.686 |

### 6847465956a0f6376a605493 — domain=STEM, breadth=Simple, nesting=Intermediate, expl=Low (14 info criteria)

| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |
|---|--:|--:|--:|--:|--:|--:|
| semantic | 58 | 58 | 1.000 | 1.000 | 1.793 | 0.945 |
| keyword | 60 | 60 | 1.000 | 1.000 | 2.017 | 0.990 |
| ssr | 59 | 59 | 1.000 | 1.000 | 1.831 | 0.956 |
| lucene_bool | 60 | 60 | 0.891 | 0.891 | 1.633 | 0.971 |

### 6847465956a0f6376a6054a7 — domain=Other, breadth=Moderate, nesting=Intermediate, expl=Medium (22 info criteria)

| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |
|---|--:|--:|--:|--:|--:|--:|
| semantic | 55 | 55 | 0.761 | 0.284 | 1.218 | 0.723 |
| keyword | 55 | 55 | 0.806 | 0.522 | 1.218 | 0.742 |
| ssr | 59 | 59 | 0.716 | 0.463 | 1.424 | 0.797 |
| lucene_bool | 57 | 57 | 0.806 | 0.418 | 1.368 | 0.892 |

### 6847465956a0f6376a6054ad — domain=Technical Documentation, breadth=Simple, nesting=Intermediate, expl=Medium (21 info criteria)

| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |
|---|--:|--:|--:|--:|--:|--:|
| semantic | 58 | 58 | 0.917 | 0.286 | 1.897 | 0.968 |
| keyword | 60 | 60 | 0.786 | 0.179 | 1.650 | 0.946 |
| ssr | 50 | 50 | 0.595 | 0.226 | 1.440 | 0.851 |
| lucene_bool | 50 | 50 | 0.369 | 0.143 | 1.180 | 0.769 |

### 6847465956a0f6376a6054be — domain=STEM, breadth=Simple, nesting=Deep, expl=Low (15 info criteria)

| engine | #docs | #judged | cov(len) | cov(str) | mUMBRELA | nDCG |
|---|--:|--:|--:|--:|--:|--:|
| semantic | 40 | 40 | 0.913 | 0.261 | 1.750 | 0.965 |
| keyword | 47 | 47 | 0.978 | 0.152 | 1.660 | 0.950 |
| ssr | 46 | 46 | 0.935 | 0.022 | 1.326 | 0.968 |
| lucene_bool | 40 | 40 | 0.870 | 0.152 | 1.350 | 0.914 |

## Breakdown by official label (cov=lenient weighted coverage)

### domain

| value | n_topics | metric | semantic | keyword | ssr | lucene_bool |
|---|--:|---|--:|--:|--:|--:|
| STEM | 3 | cov_lenient | 0.971 | 0.993 | 0.932 | 0.920 |
| STEM | 3 | mean_umbrela | 1.752 | 1.787 | 1.521 | 1.528 |
| STEM | 3 | ndcg | 0.952 | 0.960 | 0.921 | 0.943 |
| AI & ML | 5 | cov_lenient | 0.915 | 0.911 | 0.844 | 0.686 |
| AI & ML | 5 | mean_umbrela | 1.746 | 1.761 | 1.401 | 1.101 |
| AI & ML | 5 | ndcg | 0.963 | 0.966 | 0.885 | 0.852 |
| General Consumer Research | 1 | cov_lenient | 0.897 | 0.971 | 0.853 | 0.971 |
| General Consumer Research | 1 | mean_umbrela | 2.000 | 2.000 | 1.783 | 1.900 |
| General Consumer Research | 1 | ndcg | 1.000 | 1.000 | 0.963 | 0.995 |
| Historical Analysis | 4 | cov_lenient | 0.879 | 0.889 | 0.857 | 0.760 |
| Historical Analysis | 4 | mean_umbrela | 1.893 | 1.843 | 1.735 | 1.655 |
| Historical Analysis | 4 | ndcg | 0.976 | 0.982 | 0.961 | 0.967 |
| Other | 2 | cov_lenient | 0.822 | 0.887 | 0.821 | 0.887 |
| Other | 2 | mean_umbrela | 1.313 | 1.554 | 1.396 | 1.528 |
| Other | 2 | ndcg | 0.769 | 0.858 | 0.828 | 0.927 |
| Hypotheticals & Philosophy | 4 | cov_lenient | 0.866 | 0.875 | 0.751 | 0.700 |
| Hypotheticals & Philosophy | 4 | mean_umbrela | 1.816 | 1.829 | 1.345 | 1.250 |
| Hypotheticals & Philosophy | 4 | ndcg | 0.970 | 0.963 | 0.819 | 0.889 |
| Business Planning & Research | 3 | cov_lenient | 0.949 | 0.972 | 0.892 | 0.853 |
| Business Planning & Research | 3 | mean_umbrela | 1.810 | 1.791 | 1.460 | 1.164 |
| Business Planning & Research | 3 | ndcg | 0.982 | 0.967 | 0.917 | 0.871 |
| Technical Documentation | 5 | cov_lenient | 0.888 | 0.862 | 0.744 | 0.677 |
| Technical Documentation | 5 | mean_umbrela | 1.865 | 1.827 | 1.718 | 1.375 |
| Technical Documentation | 5 | ndcg | 0.974 | 0.972 | 0.948 | 0.905 |
| Current Events | 1 | cov_lenient | 0.829 | 0.876 | 0.867 | 0.686 |
| Current Events | 1 | mean_umbrela | 1.983 | 1.867 | 1.696 | 1.200 |
| Current Events | 1 | ndcg | 0.987 | 0.980 | 0.950 | 0.846 |
| Creative Writing | 2 | cov_lenient | 0.966 | 0.982 | 0.932 | 0.914 |
| Creative Writing | 2 | mean_umbrela | 1.889 | 1.910 | 1.652 | 1.449 |
| Creative Writing | 2 | ndcg | 0.980 | 0.992 | 0.932 | 0.916 |

### conceptual_breadth

| value | n_topics | metric | semantic | keyword | ssr | lucene_bool |
|---|--:|---|--:|--:|--:|--:|
| Moderate | 18 | cov_lenient | 0.921 | 0.934 | 0.881 | 0.803 |
| Moderate | 18 | mean_umbrela | 1.783 | 1.794 | 1.548 | 1.415 |
| Moderate | 18 | ndcg | 0.950 | 0.959 | 0.906 | 0.914 |
| Simple | 11 | cov_lenient | 0.878 | 0.889 | 0.775 | 0.738 |
| Simple | 11 | mean_umbrela | 1.821 | 1.818 | 1.572 | 1.353 |
| Simple | 11 | ndcg | 0.970 | 0.974 | 0.925 | 0.913 |
| High | 1 | cov_lenient | 0.818 | 0.818 | 0.682 | 0.659 |
| High | 1 | mean_umbrela | 1.837 | 1.857 | 1.275 | 0.775 |
| High | 1 | ndcg | 0.972 | 0.941 | 0.749 | 0.686 |

### logical_nesting

| value | n_topics | metric | semantic | keyword | ssr | lucene_bool |
|---|--:|---|--:|--:|--:|--:|
| Intermediate | 14 | cov_lenient | 0.912 | 0.917 | 0.839 | 0.775 |
| Intermediate | 14 | mean_umbrela | 1.742 | 1.772 | 1.497 | 1.401 |
| Intermediate | 14 | ndcg | 0.938 | 0.953 | 0.899 | 0.908 |
| Shallow | 5 | cov_lenient | 0.895 | 0.926 | 0.835 | 0.774 |
| Shallow | 5 | mean_umbrela | 1.858 | 1.873 | 1.700 | 1.385 |
| Shallow | 5 | ndcg | 0.974 | 0.981 | 0.926 | 0.901 |
| Deep | 11 | cov_lenient | 0.892 | 0.904 | 0.832 | 0.773 |
| Deep | 11 | mean_umbrela | 1.845 | 1.817 | 1.542 | 1.327 |
| Deep | 11 | ndcg | 0.977 | 0.970 | 0.910 | 0.906 |

### exploration

| value | n_topics | metric | semantic | keyword | ssr | lucene_bool |
|---|--:|---|--:|--:|--:|--:|
| Medium | 16 | cov_lenient | 0.925 | 0.913 | 0.847 | 0.801 |
| Medium | 16 | mean_umbrela | 1.795 | 1.795 | 1.598 | 1.433 |
| Medium | 16 | ndcg | 0.953 | 0.957 | 0.918 | 0.919 |
| Low | 9 | cov_lenient | 0.895 | 0.932 | 0.862 | 0.785 |
| Low | 9 | mean_umbrela | 1.824 | 1.835 | 1.530 | 1.359 |
| Low | 9 | ndcg | 0.965 | 0.975 | 0.898 | 0.890 |
| High | 5 | cov_lenient | 0.842 | 0.883 | 0.755 | 0.672 |
| High | 5 | mean_umbrela | 1.763 | 1.782 | 1.418 | 1.194 |
| High | 5 | ndcg | 0.964 | 0.966 | 0.894 | 0.894 |

## Breakdown by rubric axis (mean per-axis lenient coverage)

| axis | semantic | keyword | ssr | lucene_bool |
|---|--:|--:|--:|--:|
| Explicit Criteria | 0.947 | 0.934 | 0.859 | 0.808 |
| Implicit Criteria | 0.912 | 0.931 | 0.831 | 0.786 |
| Synthesis of Information | 0.841 | 0.823 | 0.755 | 0.644 |

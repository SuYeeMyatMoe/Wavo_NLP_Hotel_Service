# Hotel complaint classification and service dispatch

## 1. Business understanding

Hotel complaints mix operational problems with praise, room details and travel commentary. A front-desk employee reading queues in arrival order can miss the one sentence that calls for immediate action. The classifier predicts two separate answers: how quickly staff should respond and which team should receive the request. Guests can then track a reference, and supervisors can inspect the original evidence.

The assessment targets a held-out macro F1 of at least 0.80 on each target and warm p95 inference under 100 ms. Critical recall is reported separately because a missed hazard has a greater operational cost. Timing includes the evidence displayed to staff and excludes network and database time.

## 2. Data understanding

Ping Li's public dataset covers 19,728 de-identified English reviews of 32 Taipei hotels across Agoda and Trip.com. It contains platform and review identifiers, scores, publication month, hotel and text. We use the text for inference. We sample operational signals with explicit candidate rules, deduplicate normalized text and record whether each row has undergone human review. The documented sample has 1,045 unique records after final normalization. [Dataset, attribution and license](https://data.mendeley.com/datasets/z47pkh4x95/1)

The provisional urgency counts are 480 Low, 388 Moderate, 169 Urgent and 8 Critical. Thus a rare safety label contributes little to weighted averages. Sampling deliberately enriches complaints and limits repetitive praise. These frequencies do not estimate the prevalence of incidents in hotels. The notebook plots both target distributions, word and character histograms, and inspects raw samples for markup, URLs, symbols and informal wording. Positive words such as “enjoyed” can occur in negative or sarcastic reviews.

## 3. Data preparation and feature extraction

The common Python pipeline normalizes Unicode, expands English contractions, removes URLs, HTML tags, email and phone patterns, extracts room references for dispatch, strips punctuation and normalizes whitespace. Word tokens give hotel staff readable evidence. A small explicit stop list removes articles and some auxiliary words. Retaining negation protects meaning in complaints such as “not working”.

The notebook shows the Porter stem and WordNet lemma for each word of the same example. WordNet yields more readable feature names. The chosen verb-then-noun lookup is lightweight, does not disambiguate every part of speech, and leaves unseen forms untouched. A training-derived offline lookup keeps deployed preprocessing reproducible. TF-IDF uses sublinear term frequency and normalized vectors. Cross-validation compares unigrams with unigrams plus adjacent word pairs.

## 4. Modeling

The original joint-stratified split is locked at 835 training and 210 test reviews using source IDs and text fingerprints. Logistic Regression and LinearSVC use the same original training cohort and stratified validation folds. Grid search compares C and unigram versus unigram/bigram TF-IDF. Vocabulary, IDF and supervised feature weights are fitted inside training folds.

Weighted-term logistic regression is an additional experiment, fitted first on the same original cohort and then with 31 disjoint supplemental safety training rows. These are separate experiments. The 16-review safety challenge supplies no fitting or tuning data. Selection uses training CV only: urgency prioritizes Critical recall at least two-thirds and precision at least one-half, then macro F1; department uses macro F1. The selected urgency model is weighted logistic regression on the original cohort. The department model is LinearSVC.

The test set was inspected in earlier project work. Results are historical locked-holdout comparisons, not a claim of newly unseen evaluation. No choices in this upgrade were selected using the new test or challenge scores.

## 5. Evaluation and ethical reflection

All results measure agreement with **provisional labels**. Independent human annotation and a fresh final holdout remain necessary before deployment claims.

| Target / model / training cohort | Accuracy | Macro precision | Macro recall | Macro F1 | Weighted precision | Weighted recall | Weighted F1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| urgency / LogisticRegression / original training cohort | 0.876 | 0.902 | 0.780 | 0.820 | 0.877 | 0.876 | 0.876 |
| urgency / LinearSVC / original training cohort | 0.890 | 0.679 | 0.649 | 0.660 | 0.886 | 0.890 | 0.885 |
| urgency / WeightedTermLogistic / original training cohort | 0.929 | 0.938 | 0.938 | 0.938 | 0.929 | 0.929 | 0.929 |
| urgency / WeightedTermLogistic / supplemental safety training | 0.957 | 0.960 | 0.964 | 0.962 | 0.957 | 0.957 | 0.957 |
| department / LogisticRegression / original training cohort | 0.857 | 0.840 | 0.824 | 0.829 | 0.863 | 0.857 | 0.858 |
| department / LinearSVC / original training cohort | 0.881 | 0.897 | 0.842 | 0.861 | 0.886 | 0.881 | 0.881 |

The selected urgency model scores 0.938 macro F1 against the historical LinearSVC baseline's 0.660, detecting 2/2 Critical holdout cases with zero false Critical alerts. It detects 3/5 Critical cases on the disjoint safety challenge with zero false Critical alerts. The separately reported augmented experiment reaches 0.962 holdout macro F1 but previously detected only 1/5 challenge cases. The challenge result does not determine selection. Both deployed targets meet the 0.80 target on provisional labels, with limited Critical-class support.

The executed notebook includes champion confusion matrices and per-class support. Warm p95 of the expanded English analysis engine was 35.0 ms locally, including feature evidence, extraction and VADER, excluding speech, translation, network and database operations. Timing varies by hardware and text length.

### Qualitative error analysis

| Test review | Expected → predicted urgency | Evidence-based interpretation |
|---|---|---|
| A2805 | Low → Moderate | Construction is mentioned but mitigated by soundproofing; bag-of-ngrams features can still emphasize construction. |
| T04124 | Low → Moderate | Fleas and bites contradict the provisional Low label, which was influenced by a negated recommendation. |
| A0150 | Low → Moderate | “No issues” and “not particularly old” contain negated problem cues in a positive review. |
| A0329 | Low → Moderate | Praise coexists with parking delays and weak breakfast; the provisional Low label needs review. |
| A6993 | Moderate → Low | A breakfast queue is buried in extensive praise for the stay. |

These are actual errors from the selected model. Interpretations are hypotheses supported by text and feature contributions, not causal proof.

### Fairness, privacy and safeguards

The notebook includes 12 paired standard-English/Manglish probes (24 sentences), raw urgency/department predictions, final safety decisions, vocabulary coverage and paired disagreements. The probe labels are illustrative rather than independently reviewed. This small audit cannot estimate population fairness. Hindi, Mandarin, Malay and Burmese voice input requires separate human-labeled speech and translation evaluations.

Feature preprocessing strips email and phone patterns and retains negation. Contact details are masked in stored call transcripts. Transcript storage defaults off. Without consent, conversation content is processed transiently and only minimal issue, room, constraints and service facts are persisted. Revocation removes retained transcript and detailed model evidence. Necessary staff-reviewed service records remain. Callback consent is a separate preference. Hosted voice providers have their own processing terms; local controls cannot promise deletion at a provider.

Unknown vocabulary and active safety hazards trigger staff review. Sentiment does not control queue urgency. PII masking cannot reliably remove names or all contextual identifiers, and rule-based negation can still misunderstand complex phrasing.

## 6. Deployment and monitoring

The app imports a frozen artifact bundle containing both fitted pipelines, the WordNet lookup, model version and evaluation results. Streamlit displays actual nonzero TF-IDF weights and signed class contributions. Contributions plus the intercept recover the displayed class score. LinearSVC margins are displayed in their native scale.

In the presentation, run Room 305 through NLP Studio, create one ticket, open it in the staff queue, and verify the guest sees its resolution. The authenticated deployment uses FastAPI, Supabase PostgreSQL, LangGraph and a separate LiveKit/Gemini worker. The local preview persists tickets in SQLite and identifies its mode in the account menu.

Before enabling real guest operations, review labels, validate the tenant and guest policies on the target Supabase project, exercise a consented two-browser audio call, and test human alert delivery. Monitor staff corrections, critical misses, unmapped vocabulary, drift and latency. Version the entire bundle together and roll back to the prior bundle if a new one regresses. Re-evaluate using newly reviewed cases that were unavailable during tuning.


## Voice concierge deployment

Wavo provides a local conversation using speech recognition, translation and approved responses. The connected option uses LiveKit and Gemini Live for conversation. FastAPI passes guest utterances through the shared plain-Python operational services and NLP classifiers. Hotel-scoped service estimates, room readiness and approved guidance are stored in Supabase PostgreSQL. Local preview seeds clearly documented demonstration records. Case notes record conversations. Unresolved issues and physical work create tasks, and human handoff shares the summary. The database atomically reserves a ready room after staff approval. Local WebRTC transfer is for localhost demonstrations. Real hosted voice and Supabase remain to be verified with configured credentials.

## Operational extraction and verified resolution

Staff work orders combine the trained urgency and department classifiers with deterministic word-pattern extraction. Extracted topics, locations, room references and guest constraints retain exact supporting text. The linked reservation supplies the service room. A conflicting room in the complaint is displayed for review. Extraction from translated messages is labeled through the original and English working text. This rule-based component has functional regression checks. It has no separately measured corpus-level extraction F1.

Hotel procedures use exact issue categories and explicit condition rules, scoped to the hotel. A single most-specific approved match is selected. Conflicts, multiple active issue categories and missing procedures require staff review. Legacy policy rows remain available for manager categorization. Runtime vector retrieval and the pgvector requirement were removed. TF-IDF remains the classification representation.

Intent and issue-state rules expose their evidence. VADER supplies sentence-level sentiment and frustration cues with no new accuracy claim. Staff review structured notes with versioned corrections. Original analysis snapshots remain separate, except that guest privacy revocation intentionally removes retained evidence.

Open work is ranked Critical, Unassessed, Urgent, Moderate and Low, then oldest first. The dispatch service assigns eligible on-shift staff using skills, availability and workload. Staff report starting or completion through a work assistant; deterministic validation checks the assignee and record version. Completion remains staff-reported until the guest confirms. A negative confirmation reopens the request and creates another assignment attempt. Ownership, version checks, append-only outcomes and hotel-scoped authorization remain enforced. Unlinked public feedback requires reservation review before physical service.

NLP Studio offers Analyze, What-if and Evaluation. What-if performs side-effect-free analysis. Evaluation displays the deployed models only; comparisons and research charts stay in Colab. Insights reports category counts, unresolved requests, resolution duration, reopening and sentiment, with denominators and missing-data labels. These operational features introduce no new predictive-performance claims.

## Autonomous service recovery and annotation review

Operational decisions use Python services, not LangGraph, RAG or additional trained classifiers. A durable outbox stores notifications and bounded delivery retries. A separate monitoring worker handles acknowledgment deadlines, one reminder and at most one replacement per service attempt. Started work is never automatically reassigned. Guest silence is not resolution. Agent timelines contain actual database-confirmed events; they are not generated narratives. Local fallback interactions are labeled Test mode.

An offline worksheet retains the existing 1,045 texts, original provisional labels and frozen split hashes. Reviewer identity, timestamps, corrected labels and rationale are initially blank. No human validation is claimed. A reviewed release must receive a new dataset version and separate evaluation; historical scores remain historical. The frozen holdout is not a fresh unseen benchmark because earlier development already inspected its results.

This change adds no newly measured predictive results and does not retrain the selected bundle. The existing notebook execution is local Jupyter execution; actual Google Colab and hosted voice/Supabase verification require their respective runtimes and credentials.

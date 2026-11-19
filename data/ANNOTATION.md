# Operational annotation guide

The source is Ping Li's *Online review dataset from Agoda and Trip.com for tourist hotels in Taipei* (2026, version 1, CC BY 4.0). This project selects English reviews, deduplicates normalized text, and adds operational labels. Store the source and review ID with every record. [Source and license](https://data.mendeley.com/datasets/z47pkh4x95/1)

Read the entire review. Identify the most time-sensitive actionable issue and the department that can address it. Preserve the original text. A star rating is insufficient evidence. Historical public reviews create internal work only.

| Priority | Decision |
|---|---|
| Critical | A credible immediate or serious safety risk. Examples include exposed live wiring, gas leaks, and an injury hazard requiring immediate inspection. |
| Urgent | Loss of essential room service needing prompt repair, such as failed cooling, flooding, or unavailable hot water. |
| Moderate | A service problem needing routine action, such as dirty bedding, slow internet or an unresolved service complaint. |
| Low | Minor feedback, praise, preferences or a suggestion without a current service failure. |

Assign Maintenance for repairs, Housekeeping for cleaning or amenities, Front Desk for reservations or coordinating safety, Guest Relations for complaints and recovery, and Marketing for general destination or value feedback. For a mixed review, prioritize the highest credible severity, then choose the team for that issue.

The supplied CSV contains provisional labels produced by the documented rules in the preparation module. Review the text independently, correct both labels, then set reviewed to True. Obtain a second reading for critical reviews, negations, sarcasm and mixed issues. Keep disputed rows unreviewed until resolved. Review the entire sample, including the test partition, before using the verified notebook mode. For a final assessment after inspecting these provisional errors, reserve a fresh blind evaluation sample. Do not claim a human evaluation from the provisional export.

The urgency upgrade also uses 47 additional reviews from the same public source. They were identified by searching for reported injury, fall, equipment and cleaning issues, and selecting noncritical contrasts. An AI assistant provisionally annotated their operational urgency before scoring. A seeded within-class split reserved 16 as a separate challenge and assigned 31 to training. Source, review ID, original text, label, review status and partition are in `research/safety_reviews.csv`. The training script checks ID and normalized-text disjointness. In verified mode, unreviewed supplemental records are excluded from training. The challenge is deliberately enriched for safety cases and is reported separately.


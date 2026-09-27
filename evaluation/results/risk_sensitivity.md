# Regulatory Risk Score: sensitivity analysis

The score is S x L x G with S in 1-5 and L, G in 1-3, giving 45 possible combinations and 19 distinct scores. The space is small enough to enumerate exactly, so what follows is complete rather than sampled.

## Band distribution

| Band | Combinations | Share |
|---|---|---|
| Immediate | 8 | 18% |
| Medium-term | 14 | 31% |
| Long-term | 23 | 51% |

## Effect of the escalation rule

Escalation changes the band for 2 of 45 combinations (4%). All of them have S = 5, which is the intended scope of the rule.

| S | L | G | Score | Band from score alone | Band assigned |
|---|---|---|---|---|---|
| 5 | 1 | 1 | 5 | Long-term | Medium-term |
| 5 | 1 | 3 | 15 | Medium-term | Immediate |

## Achievable scores

The formula cannot produce every integer. The distinct achievable scores are: 1, 2, 3, 4, 5, 6, 8, 9, 10, 12, 15, 16, 18, 20, 24, 27, 30, 36, 45.

Near the Immediate cut point of 24 the achievable scores are 20, 24, 27, 30. This matters for interpreting the threshold: a cut point placed anywhere in a gap between achievable scores classifies identically, so the exact number carries less weight than it appears to.

## Moving the thresholds

Each cut point was moved across its plausible range while the other was held fixed. The table reports how many of the 45 combinations fall in each band.

### Immediate cut point (default 24)

| Cut | Immediate | Medium-term | Long-term | Changed vs default |
|---|---|---|---|---|
| 15 | 14 | 8 | 23 | 6 |
| 16 | 13 | 9 | 23 | 5 |
| 17 | 12 | 10 | 23 | 4 |
| 18 | 12 | 10 | 23 | 4 |
| 19 | 9 | 13 | 23 | 1 |
| 20 | 9 | 13 | 23 | 1 |
| 21 | 8 | 14 | 23 | 0 |
| 22 | 8 | 14 | 23 | 0 |
| 23 | 8 | 14 | 23 | 0 |
| 24 | 8 | 14 | 23 | 0 |
| 25 | 6 | 16 | 23 | 2 |
| 26 | 6 | 16 | 23 | 2 |
| 27 | 6 | 16 | 23 | 2 |
| 28 | 5 | 17 | 23 | 3 |
| 29 | 5 | 17 | 23 | 3 |
| 30 | 5 | 17 | 23 | 3 |
| 31 | 4 | 18 | 23 | 4 |
| 32 | 4 | 18 | 23 | 4 |
| 33 | 4 | 18 | 23 | 4 |
| 34 | 4 | 18 | 23 | 4 |
| 35 | 4 | 18 | 23 | 4 |
| 36 | 4 | 18 | 23 | 4 |

### Medium-term cut point (default 10)

| Cut | Immediate | Medium-term | Long-term | Changed vs default |
|---|---|---|---|---|
| 4 | 8 | 30 | 7 | 16 |
| 5 | 8 | 26 | 11 | 12 |
| 6 | 8 | 26 | 11 | 12 |
| 7 | 8 | 20 | 17 | 6 |
| 8 | 8 | 20 | 17 | 6 |
| 9 | 8 | 17 | 20 | 3 |
| 10 | 8 | 14 | 23 | 0 |
| 11 | 8 | 14 | 23 | 0 |
| 12 | 8 | 14 | 23 | 0 |
| 13 | 8 | 9 | 28 | 5 |
| 14 | 8 | 9 | 28 | 5 |
| 15 | 8 | 9 | 28 | 5 |

## Worked examples

| Gap | Standard | S | L | G | Score | Priority Band |
|---|---|---|---|---|---|---|
| No documented customer due diligence procedure | SBP AML/CFT Regulations | 5 | 3 | 3 | 45 | Immediate |
| CDD procedure exists but omits enhanced due diligence for high risk customers | SBP AML/CFT Regulations | 5 | 3 | 2 | 30 | Immediate |
| Customer data retention schedule undocumented | SBP Data Localisation | 5 | 1 | 1 | 5 | Medium-term (escalated) |
| Encryption at rest not applied to backup media | ISO 27001 A.8.24 | 4 | 2 | 3 | 24 | Immediate |
| Access review records incomplete for one quarter | ISO 27001 A.5.18 | 4 | 2 | 1 | 8 | Long-term |
| Business continuity plan not version controlled | ISO 22301 | 3 | 1 | 2 | 6 | Long-term |
| Incident log missing reviewer initials | Internal policy | 1 | 1 | 1 | 1 | Long-term |

- **No documented customer due diligence procedure** (5 x 3 x 3 = 45, Immediate). Severe obligation, active regulator focus, control entirely absent.
- **CDD procedure exists but omits enhanced due diligence for high risk customers** (5 x 3 x 2 = 30, Immediate). Same obligation, partially present rather than absent.
- **Customer data retention schedule undocumented** (5 x 1 x 1 = 5, Medium-term). The case the escalation rule exists for: severe obligation, low enforcement likelihood, minor gap. Scores 5, which the raw formula would place in Long-term. Escalation applies.
- **Encryption at rest not applied to backup media** (4 x 2 x 3 = 24, Immediate). Core security control, moderate enforcement focus, absent.
- **Access review records incomplete for one quarter** (4 x 2 x 1 = 8, Long-term). Same control family, minor gap.
- **Business continuity plan not version controlled** (3 x 1 x 2 = 6, Long-term). Governance item, low enforcement focus.
- **Incident log missing reviewer initials** (1 x 1 x 1 = 1, Long-term). Floor of the scale.

## Severity scale

| S | Obligation type |
|---|---|
| 5 | AML/CFT, sanctions, financial crime, customer data protection |
| 4 | core security controls (access control, encryption, incident response) |
| 3 | governance and operational resilience |
| 2 | reporting and record keeping |
| 1 | administrative or procedural |
